"""In-process HTTP adapter for the synthetic V2 snowfall demo."""

from __future__ import annotations

import json
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from engine.v2 import simulate_snowfall


router = APIRouter()
_lock = Lock()
_scenarios: dict[str, dict[str, Any]] = {}
_runs: dict[str, dict[str, Any]] = {}


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weatherScenarioId: str = "snowfall-demo"


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarioId: str
    seed: int = 1
    horizon: int = Field(default=6, ge=1, le=24, description="Modelled hours")


def _run_or_404(run_id: str) -> dict[str, Any]:
    with _lock:
        run = _runs.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/scenarios")
def create_scenario(payload: ScenarioInput) -> dict[str, Any]:
    if payload.weatherScenarioId != "snowfall-demo":
        raise HTTPException(422, "Only snowfall-demo is implemented")
    scenario_id = str(uuid4())
    scenario = {
        "id": scenario_id,
        "mode": "dynamic-v2",
        "weatherScenarioId": payload.weatherScenarioId,
        "dataSnapshotId": "synthetic-snowfall-demo-1",
        "parameterSetId": "snowfall-assumptions-1",
        "rulesVersion": "v2-demo-1",
        "dataStatus": "synthetic",
        "modelStatus": "experimental",
        "modelVersion": "v2-snowfall-demo-1",
    }
    with _lock:
        _scenarios[scenario_id] = scenario
    return scenario


@router.post("/runs")
def create_run(payload: RunInput) -> dict[str, Any]:
    with _lock:
        scenario = _scenarios.get(payload.scenarioId)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    run_id = str(uuid4())
    simulation = simulate_snowfall(run_id, payload.seed, payload.horizon)
    run = {
        "runId": run_id,
        "scenarioId": scenario["id"],
        "status": "completed",
        "mode": "dynamic-v2",
        "dataStatus": "synthetic",
        "modelStatus": "experimental",
        "timeMode": "simulated",
        "modules": {
            "weather": "experimental",
            "transport": "experimental",
            "cityServices": "experimental",
            "appeals": "experimental",
            "population": "not-implemented",
            "budget": "not-implemented",
            "politics": "not-implemented",
        },
        "seed": payload.seed,
        "horizonHours": payload.horizon,
        "endSimTime": simulation["endSimTime"],
        "events": simulation["events"],
        "series": simulation["series"],
    }
    with _lock:
        _runs[run_id] = run
    return {key: value for key, value in run.items() if key not in {"events", "series"}}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    return {key: value for key, value in run.items() if key not in {"events", "series"}}


@router.get("/runs/{run_id}/events", response_model=None)
def get_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
    accept: str | None = Header(default=None),
    last_event_id: str | None = Header(default=None),
) -> dict[str, Any] | StreamingResponse:
    run = _run_or_404(run_id)
    if accept and "text/event-stream" in accept:
        if last_event_id is not None:
            try:
                after = max(after, int(last_event_id))
            except ValueError as exc:
                raise HTTPException(400, "Invalid Last-Event-ID") from exc
        events = [event for event in run["events"] if event["seq"] > after]

        def stream():
            for event in events:
                yield f'id: {event["seq"]}\nevent: {event["type"]}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'

        return StreamingResponse(stream(), media_type="text/event-stream")
    return {
        "runId": run_id,
        "events": [event for event in run["events"] if event["seq"] > after],
        "lastSeq": len(run["events"]),
    }


@router.get("/runs/{run_id}/metrics")
def get_metrics(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    return {
        "runId": run_id,
        "dataStatus": run["dataStatus"],
        "modelStatus": run["modelStatus"],
        "timeMode": run["timeMode"],
        "units": {
            "roadCapacityPercent": "percent",
            "travelTimeMinutes": "minutes",
            "serviceBacklogTasks": "tasks",
            "appealsCount": "appeals",
        },
        "series": run["series"],
    }
