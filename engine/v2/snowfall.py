"""Small deterministic snowfall vertical slice for the V2 demo.

Coefficients are assumptions for an interactive demonstration, not calibrated
estimates of Astana's transport or municipal services.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any


START = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)


def simulate_snowfall(run_id: str, seed: int, horizon: int) -> dict[str, Any]:
    rng = Random(seed)
    events: list[dict[str, Any]] = []
    series: dict[str, list[dict[str, Any]]] = {
        "roadCapacityPercent": [],
        "travelTimeMinutes": [],
        "serviceBacklogTasks": [],
        "appealsCount": [],
    }
    backlog = 0
    appeals = 0
    snow_start_id: str | None = None

    def emit(hour: int, kind: str, payload: dict[str, Any], causes: list[str] | None = None) -> str:
        seq = len(events) + 1
        event_id = f"{run_id}:{seq}"
        timestamp = (START + timedelta(hours=hour)).isoformat()
        events.append({
            "id": event_id,
            "runId": run_id,
            "seq": seq,
            "simTime": timestamp,
            "recordedAt": datetime.now(timezone.utc).isoformat(),
            "type": kind,
            "actorId": None,
            "districtId": "saryarka",
            "causedBy": causes or [],
            "payloadSchemaVersion": "v2-demo-1",
            "payload": payload,
        })
        return event_id

    for hour in range(horizon):
        snowy = 1 <= hour <= 3
        if hour == 1:
            snow_start_id = emit(hour, "snowfall.started", {"intensityMmPerHour": 4})
        if snowy:
            capacity = 65
            travel = 31 + rng.randint(0, 4)
            new_tasks = 4
            served = 2
        else:
            capacity = 100
            travel = 20 + rng.randint(0, 2)
            new_tasks = 1
            served = 3
        backlog = max(0, backlog + new_tasks - served)

        if snowy:
            capacity_id = emit(hour, "road.capacity_reduced", {
                "capacityPercent": capacity,
                "baselinePercent": 100,
            }, [snow_start_id] if snow_start_id else [])
            delay_id = emit(hour, "transport.delayed", {
                "travelTimeMinutes": travel,
                "baselineMinutes": 20,
                "experienceId": f"resident-001:trip:{hour}",
            }, [capacity_id])
            backlog_id = emit(hour, "service.backlog", {
                "newTasks": new_tasks,
                "servedTasks": served,
                "backlogTasks": backlog,
            }, [delay_id])
            appeals += 1
            emit(hour, "appeal.created", {
                "appealId": f"appeal-{hour}",
                "sourceExperienceId": f"resident-001:trip:{hour}",
                "topic": "snow-transport-delay",
            }, [backlog_id, delay_id])
        elif hour == 4:
            emit(hour, "snowfall.ended", {"intensityMmPerHour": 0})

        timestamp = (START + timedelta(hours=hour)).isoformat()
        for name, value in (
            ("roadCapacityPercent", capacity),
            ("travelTimeMinutes", travel),
            ("serviceBacklogTasks", backlog),
            ("appealsCount", appeals),
        ):
            series[name].append({"simTime": timestamp, "value": value})

    return {
        "events": events,
        "series": series,
        "endSimTime": (START + timedelta(hours=horizon)).isoformat(),
    }
