"""V2 HTTP adapter. Local demo has one operator; set AKIM_RUN_TOKEN for control access."""
import asyncio
from datetime import datetime, timezone
from hmac import compare_digest
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Annotated
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse

from engine.v2.application.controller import MODEL_VERSION, PARAMETER_SET, RunController, RunError, required, sim_time
from engine.v2.application.experiments import Experiments
from engine.v2.domain.simulation import initial_state
from engine.v2.infrastructure.datasets import load_demo_snapshot
from engine.v2.infrastructure.store import create_store
from services.api.v2_contracts import (
    AssistantRequest, BranchRequest, CommandRequest, ExperimentRequest, RunRequest, ScenarioRequest,
)


class V2Runtime:
    def __init__(self, gate, store=None):
        self.gate, self.published = gate, load_demo_snapshot(gate)
        self.store = store if store is not None else create_store()
        # A content hash identifies even a dirty/local build when no release commit is supplied.
        source_root = Path(__file__).resolve().parents[2]
        source = sha256()
        for package in ("engine", "data_gate", "services", "ai"):
            for path in sorted((source_root / package).rglob("*.py")):
                source.update(path.relative_to(source_root).as_posix().encode())
                source.update(path.read_bytes().replace(b"\r\n", b"\n"))
        self.controller = RunController(self.store, code_revision=os.getenv("AKIM_CODE_REVISION") or
                                        "source-sha256:" + source.hexdigest())
        self.experiments = Experiments(self.store)
        self.preview = initial_state(self.published.payload, 42, "catalog", {})


def metric_projection(run):
    series, evidence = {}, []
    for index, point in enumerate(run["state"].get("metrics", [])):
        metric = point.get("metricId", point.get("metric"))
        if not metric:
            continue
        district = point.get("districtId")
        minute = point.get("simMinute", 0)
        identifier = f"{run['runId']}:metric:{index}"
        window = [sim_time(run, point.get("windowStartMinute", 0)), sim_time(run, minute)]
        record = {"id": identifier, "runId": run["runId"], "metric": metric, "unit": point["unit"],
                  "window": window, "value": point.get("value"), "status": "simulated",
                  "districtId": district, "sourceIds": point.get("sourceIds", [])}
        evidence.append(record)
        key = (metric, district)
        if key not in series:
            series[key] = {"metricId": metric, "unit": point["unit"], "window": window,
                           "aggregation": point.get("aggregation", "model-output"),
                           "groupBy": {"districtId": district}, "points": [], "evidenceIds": []}
        series[key]["window"][1] = window[1]
        series[key]["points"].append({"simMinute": minute, "simTime": sim_time(run, minute),
                                     "value": point.get("value"), "evidenceId": identifier})
        series[key]["evidenceIds"].append(identifier)
    return {"series": list(series.values()), "evidence": evidence}


def router():
    api = APIRouter(tags=["V2 synthetic laboratory"])

    def runtime(request: Request):
        return request.app.state.v2

    def control(authorization: Annotated[str | None, Header()] = None):
        expected = os.getenv("AKIM_RUN_TOKEN")
        if expected and (not authorization or not compare_digest(
                authorization.encode(), f"Bearer {expected}".encode())):
            raise RunError("forbidden", "Authorization", "Требуется право управления прогоном", 403)

    def idempotency(idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]):
        return idempotency_key

    RT = Annotated[V2Runtime, Depends(runtime)]
    Key = Annotated[str, Depends(idempotency)]

    @api.get("/v2/catalog")
    def catalog(rt: RT):
        return {"mode": "dynamic-v2", "maturity": "V2-demo", "modelVersion": MODEL_VERSION,
                "parameterSetId": PARAMETER_SET, "dataSnapshotId": rt.published.id,
                "dataManifest": rt.published.manifest_api_dict(),
                "districts": rt.published.payload["districts"],
                "modules": rt.preview.get("moduleStatuses", {}),
                "parameters": rt.preview.get("parameterRegistry", {}),
                "timeModes": ["operational", "strategic"],
                "limitations": ["Синтетические данные. Не прогноз реальной Астаны.",
                                "Метрики V2 не являются официальным Score V1."]}

    @api.get("/v2/health")
    def health(rt: RT):
        worker = rt.store.read("system", "worker")
        age = None
        if worker:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(worker["heartbeat"])).total_seconds()
        return {"status": "ok" if age is not None and age < 30 else "worker-unavailable",
                "worker": worker, "heartbeatAgeSeconds": age}

    @api.post("/scenarios", dependencies=[Depends(control)], status_code=201)
    def scenario(body: ScenarioRequest, rt: RT):
        published = rt.published
        if body.dataSnapshotId and body.dataSnapshotId != published.id:
            published = rt.gate.get_snapshot(body.dataSnapshotId)
            if published.payload.get("mode") != "dynamic-v2":
                raise RunError("wrong_mode", "dataSnapshotId", "Нужен опубликованный снимок V2")
        # Validate assumptions at the boundary, before preserving an immutable scenario.
        request = body.model_dump()
        parameters = {**request["parameters"], "timeMode": body.timeMode}
        if body.weatherScenarioId == "clear":
            parameters["snowIntensity"] = 0
        initial_state(published.payload, 0, "validation", parameters)
        return rt.controller.scenario(request, published)

    @api.post("/runs", dependencies=[Depends(control)], status_code=202)
    def create_run(body: RunRequest, key: Key, rt: RT):
        scenario = required(rt.store.read("scenario", body.scenarioId), "scenarioId")
        if scenario["timeMode"] == "operational" and body.horizon > 10080:
            raise RunError("compute_budget", "horizon", "Оперативный прогон ограничен 7 сутками; используйте strategic")
        return rt.controller.create_run(body.model_dump(), key)

    @api.get("/runs/{run_id}")
    def run(run_id: str, rt: RT):
        return rt.controller.view(run_id)

    @api.post("/runs/{run_id}/commands", dependencies=[Depends(control)], status_code=202)
    def command(run_id: str, body: CommandRequest, key: Key, rt: RT):
        if body.idempotencyKey != key:
            raise RunError("idempotency_conflict", "idempotencyKey", "Ключ в заголовке и теле должен совпадать", 409)
        return rt.controller.command(run_id, body.model_dump())

    @api.post("/runs/{run_id}/checkpoints", dependencies=[Depends(control)], status_code=201)
    def checkpoint(run_id: str, rt: RT):
        return rt.controller.checkpoint(run_id)

    @api.post("/runs/{run_id}/branches", dependencies=[Depends(control)], status_code=201)
    def branch(run_id: str, body: BranchRequest, key: Key, rt: RT):
        return rt.controller.branch(run_id, body.checkpointId, key)

    @api.post("/runs/{run_id}/replay", dependencies=[Depends(control)])
    def replay(run_id: str, body: BranchRequest, rt: RT):
        return rt.controller.replay(run_id, body.checkpointId)

    @api.get("/runs/{run_id}/events")
    async def events(run_id: str, request: Request, rt: RT, after: int = Query(0, ge=0),
                     stream: bool = True, last_event_id: Annotated[str | None, Header()] = None):
        await asyncio.to_thread(rt.controller.view, run_id, False)
        if last_event_id is not None:
            try:
                cursor = int(last_event_id)
                if cursor < 0:
                    raise ValueError()
                after = max(after, cursor)
            except ValueError as error:
                raise RunError("invalid_cursor", "Last-Event-ID", "Ожидается неотрицательный seq") from error
        if not stream:
            items = await asyncio.to_thread(rt.controller.events, run_id, after)
            return {"events": items, "nextSeq": items[-1]["seq"] if items else after}

        async def generate():
            cursor = after
            while not await request.is_disconnected():
                items = await asyncio.to_thread(rt.controller.events, run_id, cursor)
                for item in items:
                    yield f"id: {item['seq']}\nevent: city-event\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                    cursor = item["seq"]
                if not items:
                    yield ": keepalive\n\n"
                await asyncio.sleep(.5)
        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.get("/runs/{run_id}/metrics")
    def metrics(run_id: str, rt: RT):
        return metric_projection(required(rt.store.read("run", run_id)))

    @api.get("/runs/{run_id}/trace/{event_id}")
    def trace(run_id: str, event_id: str, rt: RT):
        return rt.controller.trace(run_id, event_id)

    @api.get("/runs/{run_id}/agents/{agent_id}/experience")
    def experience(run_id: str, agent_id: str, rt: RT):
        state = required(rt.store.read("run", run_id))["state"]
        agent = next((a for a in state.get("agents", []) if a["id"] == agent_id), None)
        required(agent, "agentId")
        return {"runId": run_id, "agent": agent,
                "events": [e for e in state["events"] if e.get("actorId") == agent_id]}

    @api.get("/runs/{run_id}/population")
    def population(run_id: str, rt: RT):
        state = required(rt.store.read("run", run_id))["state"]
        return {"cohorts": state.get("cohorts", []), "migrationFlows": state.get("migrationFlows", []),
                "districts": state["districts"], "status": "synthetic", "unit": "persons"}

    @api.get("/runs/{run_id}/development")
    def development(run_id: str, rt: RT):
        state = required(rt.store.read("run", run_id))["state"]
        return {key: state.get(key, []) for key in ("parcels", "projects", "housingStock")}

    @api.get("/runs/{run_id}/flows")
    def flows(run_id: str, rt: RT):
        state = required(rt.store.read("run", run_id))["state"]
        balance = sum(state["accounts"].values()) - state["initialMoney"] - state["externalInflow"] + state["externalOutflow"]
        return {"transfers": state.get("transfers", []), "ledger": state["ledger"],
                "accounts": state.get("accounts", {}), "basePeriod": state["basePeriod"],
                "externalInflow": state["externalInflow"], "externalOutflow": state["externalOutflow"],
                "balanceError": balance, "priceIndex": state["priceIndex"]}

    @api.get("/runs/{run_id}/politics")
    def politics(run_id: str, rt: RT):
        state = required(rt.store.read("run", run_id))["state"]
        return {"politics": state.get("politics", {}), "status": "synthetic",
                "limitation": "Гипотезы модели: только синтетические акторы, не прогноз выборов"}

    @api.post("/experiments", dependencies=[Depends(control)], status_code=202)
    def create_experiment(body: ExperimentRequest, key: Key, rt: RT):
        return rt.experiments.create(body.model_dump(), key)

    @api.get("/experiments/{experiment_id}")
    def experiment(experiment_id: str, rt: RT):
        return rt.experiments.get(experiment_id)

    @api.post("/experiments/{experiment_id}/cancel", dependencies=[Depends(control)])
    def cancel_experiment(experiment_id: str, rt: RT):
        with rt.store.transaction("experiment", experiment_id) as document:
            required(document, "experimentId")
            if document["status"] in ("queued", "running"):
                document["status"] = "cancelled"
        return rt.experiments.get(experiment_id)

    @api.post("/assistant/messages")
    def assistant(body: AssistantRequest, rt: RT):
        run = required(rt.store.read("run", body.runId))
        projection = metric_projection(run)
        # Untrusted message is deliberately never interpreted as a tool command.
        latest = {}
        for item in projection["evidence"]:
            if item["districtId"] is None:
                latest[item["metric"]] = item
        claims = [{"text": f"{e['metric']}: {e['value']} {e['unit']}", "grade": "calculation",
                   "metricId": e["metric"], "value": e["value"], "unit": e["unit"],
                   "window": e["window"], "aggregation": "model-output", "evidenceIds": [e["id"]]}
                  for e in latest.values()]
        return {"summary": "Расчётная сводка текущего прогона. Решения не применяются автоматически.",
                "mode": "rule-based", "claims": claims, "evidence": list(latest.values()),
                "limitations": ["LLM для V2 не подключён; это детерминированный evidence-отчёт.",
                                "Параметры синтетические, эффект причинный только внутри модели."], "proposals": []}

    @api.get("/runs/{run_id}/export")
    def export(run_id: str, rt: RT):
        run = required(rt.store.read("run", run_id))
        scenario = required(rt.store.read("scenario", run["scenarioId"]), "scenarioId")
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for name, value in (("manifest.json", run["manifest"]), ("run.json", run),
                                ("scenario.json", scenario), ("metrics.json", metric_projection(run))):
                archive.writestr(name, json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return Response(buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})

    return api
