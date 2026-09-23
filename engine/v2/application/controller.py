"""Immutable scenarios, durable commands and bounded, replayable run execution."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import platform
from statistics import median

from engine.v2.application.ports import DocumentStore
from engine.v2.domain.simulation import MODEL_VERSION, RNG_VERSION, initial_state, advance, apply_decision

PARAMETER_SET = "synthetic-city/1.0"


class RunError(ValueError):
    def __init__(self, code, field, message, status=422):
        super().__init__(message)
        self.code, self.field, self.message, self.status = code, field, message, status


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def sim_time(run, minute):
    start = datetime.fromisoformat(run["manifest"]["startSimTime"].replace("Z", "+00:00"))
    return (start + timedelta(minutes=minute)).isoformat()


def required(document, field="runId"):
    if not document:
        raise RunError("not_found", field, "Объект не найден", 404)
    return document


class RunController:
    def __init__(self, store: DocumentStore, *, code_revision=MODEL_VERSION):
        self.store, self.code_revision = store, code_revision

    def scenario(self, request, published):
        body = deepcopy(request)
        body.update({"mode": "dynamic-v2", "dataSnapshotId": published.id,
                     "modelVersion": MODEL_VERSION, "rulesVersion": "dynamic/1.0",
                     "parameterSetId": PARAMETER_SET, "snapshot": deepcopy(published.payload),
                     "dataHash": digest(published.payload)})
        if body.get("weatherScenarioId") == "clear":
            body["parameters"] = {**body.get("parameters", {}), "snowIntensity": 0}
        body["parameters"] = {**body.get("parameters", {}), "timeMode": body.get("timeMode", "operational")}
        identity = "scenario-" + digest(body)[:24]
        with self.store.transaction("scenario", identity) as record:
            if not record:
                record.update({**body, "id": identity, "createdAt": now()})
        return {k: v for k, v in self.store.read("scenario", identity).items() if k != "snapshot"}

    def create_run(self, request, key):
        scenario = required(self.store.read("scenario", request["scenarioId"]), "scenarioId")
        identity = "run-" + digest(["create", key])[:24]
        fingerprint = digest(request)
        with self.store.transaction("run", identity) as record:
            if record:
                if record["requestHash"] != fingerprint:
                    raise RunError("idempotency_conflict", "Idempotency-Key", "Ключ уже использован", 409)
            else:
                seed, horizon = request["seed"], request["horizon"]
                # Family identity is stable for paired runs and independent of wall clock/run UUID.
                family = digest([scenario["id"], seed])[:24]
                state = initial_state(deepcopy(scenario["snapshot"]), seed, family,
                                      deepcopy(scenario.get("parameters", {})))
                record.update({"runId": identity, "scenarioId": scenario["id"], "requestHash": fingerprint,
                               "status": "paused", "stateVersion": 0, "horizon": horizon,
                               "state": state, "commands": {}, "pending": None, "speed": 60,
                               "checkpoints": {}, "recordedAt": now(), "eventRecordedAt": {}, "operations": [],
                               "manifest": {"runId": identity, "scenarioId": scenario["id"],
                                   "mode": "dynamic-v2", "codeRevision": self.code_revision,
                                   "modelVersion": MODEL_VERSION, "dataSnapshotId": scenario["dataSnapshotId"],
                                   "dataHash": scenario["dataHash"], "parameterHash": digest({
                                       "parameters": state["parameters"], "timeMode": state["timeMode"],
                                       "representativeCount": len(state["agents"])}),
                                   "parameterSetId": PARAMETER_SET, "seed": seed, "rngVersion": RNG_VERSION,
                                   "runtimeVersion": platform.python_version(), "llmPolicyVersion": "rules-only/1",
                                   "startSimTime": scenario["snapshot"].get("startSimTime", "2026-01-01T00:00:00Z"),
                                   "endSimTime": None, "familyId": family}})
                record["manifest"]["endSimTime"] = sim_time(record, horizon)
                self._record_events(record)
                self._checkpoint(record)
        return self.view(identity)

    def view(self, run_id, full=True):
        run = required(self.store.read("run", run_id))
        result = {key: run[key] for key in ("runId", "scenarioId", "status", "stateVersion", "horizon", "manifest")}
        result.update({"simMinute": run["state"]["simMinute"], "pendingCommand": run["pending"] is not None,
                       "speed": run["speed"], "simTime": sim_time(run, run["state"]["simMinute"]),
                       "checkpoints": [{k: c[k] for k in ("id", "simMinute", "stateVersion", "hash")}
                                       for c in run["checkpoints"].values()]})
        if full:
            result["state"] = {k: v for k, v in run["state"].items() if k not in ("events", "metrics")}
        if run.get("error"):
            result["error"] = run["error"]
        return result

    def command(self, run_id, command):
        with self.store.transaction("run", run_id) as run:
            required(run)
            key, fingerprint = command["idempotencyKey"], digest(command)
            if key in run["commands"]:
                previous = run["commands"][key]
                if previous["hash"] != fingerprint:
                    raise RunError("idempotency_conflict", "idempotencyKey", "Повторный ключ с другим телом", 409)
                return previous["result"]
            if command["expectedStateVersion"] != run["stateVersion"]:
                raise RunError("state_version_conflict", "expectedStateVersion", "Состояние изменилось; обновите прогон", 409)
            kind, payload = command["type"], command["payload"]
            if run["status"] in ("completed", "cancelled", "failed"):
                raise RunError("run_terminal", "type", "Прогон завершён; создайте ветку checkpoint", 409)
            if run["pending"] and kind not in ("clock.pause", "clock.cancel", "clock.resume"):
                raise RunError("run_busy", "type", "Дождитесь завершения шага", 409)
            if kind == "clock.pause":
                run["status"] = "paused"
                if run["pending"]:
                    run["pending"]["suspended"] = True
            elif kind == "clock.cancel":
                run["status"], run["pending"] = "cancelled", None
            elif kind == "clock.resume":
                run["status"] = "running"
                if run["pending"]:
                    run["pending"]["suspended"] = False
            elif kind == "clock.speed":
                speed = payload.get("speed")
                if type(speed) is not int or not 1 <= speed <= 43200:
                    raise RunError("invalid_speed", "payload.speed", "Скорость: 1–43200 минут за пакет")
                run["speed"] = speed
            elif kind == "clock.step":
                minutes = payload.get("minutes")
                if type(minutes) is not int or minutes < 1 or minutes > run["horizon"] - run["state"]["simMinute"]:
                    raise RunError("invalid_step", "payload.minutes", "Шаг должен помещаться в горизонт")
                run["status"] = "paused"
                run["pending"] = {"remaining": minutes, "commandId": command["commandId"], "suspended": False}
            elif kind.startswith("clock."):
                raise RunError("unsupported_command", "type", "Неизвестная команда часов")
            else:
                apply_decision(run["state"], command)
                run["operations"].append({"type": "decision", "command": deepcopy(command)})
            run["stateVersion"] += 1
            self._record_events(run)
            result = {"commandId": command["commandId"], "accepted": True,
                      "stateVersion": run["stateVersion"], "status": run["status"]}
            run["commands"][key] = {"hash": fingerprint, "result": result}
            return result

    @staticmethod
    def _record_events(run):
        timestamp = now()
        recorded = run.setdefault("eventRecordedAt", {})
        for event in run["state"]["events"]:
            recorded.setdefault(event["id"], timestamp)

    def _checkpoint(self, run):
        state = deepcopy(run["state"])
        checksum = digest(state)
        identity = "checkpoint-" + digest([run["runId"], checksum, len(run["operations"])])[:24]
        checkpoint = {"id": identity, "simMinute": state["simMinute"], "stateVersion": run["stateVersion"],
                      "hash": checksum, "state": state, "operationIndex": len(run["operations"])}
        run["checkpoints"][identity] = checkpoint
        return {key: checkpoint[key] for key in ("id", "simMinute", "stateVersion", "hash")}

    def checkpoint(self, run_id):
        with self.store.transaction("run", run_id) as run:
            required(run)
            if run["pending"]:
                raise RunError("run_busy", "checkpoint", "Дождитесь завершения шага", 409)
            if len(run["checkpoints"]) >= 32:
                raise RunError("checkpoint_limit", "checkpoint", "Лимит: 32 checkpoint на прогон")
            return self._checkpoint(run)

    def branch(self, run_id, checkpoint_id, key):
        parent = required(self.store.read("run", run_id))
        checkpoint = required(parent["checkpoints"].get(checkpoint_id), "checkpointId")
        if digest(checkpoint["state"]) != checkpoint["hash"]:
            raise RunError("checkpoint_corrupted", "checkpointId", "Контрольная сумма не совпадает", 409)
        identity = "run-" + digest(["branch", run_id, key])[:24]
        fingerprint = digest([run_id, checkpoint_id])
        with self.store.transaction("run", identity) as child:
            if child and child["requestHash"] != fingerprint:
                raise RunError("idempotency_conflict", "Idempotency-Key", "Ключ уже использован для другого checkpoint", 409)
            if not child:
                child.update(deepcopy(parent))
                child.update({"runId": identity, "state": deepcopy(checkpoint["state"]), "status": "paused",
                              "stateVersion": 0, "commands": {}, "pending": None, "checkpoints": {},
                              "operations": [], "recordedAt": now(), "requestHash": fingerprint})
                past_ids = {event["id"] for event in checkpoint["state"]["events"]}
                child["eventRecordedAt"] = {k: v for k, v in parent.get("eventRecordedAt", {}).items() if k in past_ids}
                child.pop("error", None)
                child["manifest"].update({"runId": identity,
                                         "branchOf": {"runId": run_id, "checkpointId": checkpoint_id}})
                self._checkpoint(child)
        return self.view(identity)

    def work_run(self, run_id):
        with self.store.transaction("run", run_id) as run:
            if not run or run["status"] in ("completed", "cancelled", "failed"):
                return False
            pending = run["pending"]
            if pending and pending.get("suspended"):
                return False
            if not pending and run["status"] != "running":
                return False
            # Fixed work budget: no long HTTP handlers, checks between each batch.
            strategic = run["state"].get("timeMode") == "strategic"
            cap = 43200 if strategic else 60
            amount = min(pending["remaining"] if pending else run["speed"], cap,
                         run["horizon"] - run["state"]["simMinute"])
            before = deepcopy(run["state"])
            try:
                advance(run["state"], amount)
            except Exception as error:
                run["state"], run["status"] = before, "failed"
                run["error"] = {"code": "simulation_failed", "message": str(error)[:500]}
                self._checkpoint(run)
                return True
            run["operations"].append({"type": "advance", "minutes": amount})
            self._record_events(run)
            run["stateVersion"] += 1
            if pending:
                pending["remaining"] -= amount
                if pending["remaining"] == 0:
                    run["pending"] = None
            if run["state"]["simMinute"] >= run["horizon"]:
                run["status"], run["pending"] = "completed", None
            return True

    def events(self, run_id, after=0, limit=1000):
        run = required(self.store.read("run", run_id))
        return [{**event, "runId": run_id, "simTime": sim_time(run, event["simMinute"]),
                 "recordedAt": run.get("eventRecordedAt", {}).get(event["id"], run["recordedAt"])}
                for event in run["state"]["events"]
                if event["seq"] > after][:limit]

    def trace(self, run_id, event_id):
        run = required(self.store.read("run", run_id))
        by_id = {event["id"]: event for event in run["state"]["events"]}
        required(by_id.get(event_id), "eventId")
        pending, visited = [event_id], set()
        while pending and len(visited) < 500:
            identity = pending.pop()
            if identity in visited or identity not in by_id:
                continue
            visited.add(identity)
            pending.extend(by_id[identity]["causedBy"])
        return {"events": sorted([by_id[key] for key in visited], key=lambda e: e["seq"]),
                "limitation": "Причинная трасса внутри модели, не доказательство для реального города"}

    def replay(self, run_id, checkpoint_id):
        run = required(self.store.read("run", run_id))
        checkpoint = required(run["checkpoints"].get(checkpoint_id), "checkpointId")
        if digest(checkpoint["state"]) != checkpoint["hash"]:
            raise RunError("checkpoint_corrupted", "checkpointId", "Контрольная сумма не совпадает", 409)
        state = deepcopy(checkpoint["state"])
        for operation in run["operations"][checkpoint["operationIndex"]:]:
            if operation["type"] == "advance":
                advance(state, operation["minutes"])
            else:
                apply_decision(state, operation["command"])
        return {"matches": digest(state) == digest(run["state"]), "replayedHash": digest(state),
                "currentHash": digest(run["state"]), "checkpointId": checkpoint_id}


def interval(values):
    ordered = sorted(values)
    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lo = int(position)
        hi = min(lo + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
    return {"median": median(ordered), "p05": percentile(.05), "p95": percentile(.95),
            "min": ordered[0], "max": ordered[-1], "n": len(ordered),
            "intervalType": "empirical-outcome-interval-not-confidence-interval"}
