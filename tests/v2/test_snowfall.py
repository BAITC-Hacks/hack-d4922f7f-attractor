from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api.main import app


def _check_snowfall_run_is_deterministic_and_causal() -> None:
    client = TestClient(app)
    scenario = client.post("/scenarios", json={"weatherScenarioId": "snowfall-demo"})
    assert scenario.status_code == 200
    scenario_id = scenario.json()["id"]

    first = client.post("/runs", json={"scenarioId": scenario_id, "seed": 7, "horizon": 6})
    second = client.post("/runs", json={"scenarioId": scenario_id, "seed": 7, "horizon": 6})
    assert first.status_code == second.status_code == 200
    first_id = first.json()["runId"]
    second_id = second.json()["runId"]
    run = client.get(f"/runs/{first_id}").json()
    assert run["status"] == "completed"
    assert run["modules"]["population"] == "not-implemented"

    events = client.get(f"/runs/{first_id}/events").json()["events"]
    repeat = client.get(f"/runs/{second_id}/events").json()["events"]
    assert [(event["type"], event["payload"]) for event in events] == [
        (event["type"], event["payload"]) for event in repeat
    ]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    by_type = {event["type"]: event for event in reversed(events)}
    assert by_type["snowfall.started"]["id"] in by_type["road.capacity_reduced"]["causedBy"]
    assert by_type["road.capacity_reduced"]["id"] in by_type["transport.delayed"]["causedBy"]
    assert by_type["transport.delayed"]["id"] in by_type["service.backlog"]["causedBy"]
    assert by_type["service.backlog"]["id"] in by_type["appeal.created"]["causedBy"]
    assert by_type["appeal.created"]["payload"]["sourceExperienceId"]
    assert client.get(f"/runs/{first_id}/events?after=2").json()["events"][0]["seq"] == 3

    metrics = client.get(f"/runs/{first_id}/metrics").json()
    assert metrics["dataStatus"] == "synthetic"
    assert metrics["modelStatus"] == "experimental"
    assert max(point["value"] for point in metrics["series"]["travelTimeMinutes"]) > 20
    assert metrics["series"]["serviceBacklogTasks"][-1]["value"] >= 0


def _check_snowfall_sse_replays_after_last_event_id() -> None:
    client = TestClient(app)
    scenario_id = client.post("/scenarios", json={"weatherScenarioId": "snowfall-demo"}).json()["id"]
    run_id = client.post("/runs", json={"scenarioId": scenario_id, "seed": 1, "horizon": 3}).json()["runId"]
    response = client.get(
        f"/runs/{run_id}/events",
        headers={"Accept": "text/event-stream", "Last-Event-ID": "2"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 3\n" in response.text
    assert "id: 1\n" not in response.text


class SnowfallTests(unittest.TestCase):
    def test_run_is_deterministic_and_causal(self) -> None:
        _check_snowfall_run_is_deterministic_and_causal()

    def test_sse_replays_after_last_event_id(self) -> None:
        _check_snowfall_sse_replays_after_last_event_id()
