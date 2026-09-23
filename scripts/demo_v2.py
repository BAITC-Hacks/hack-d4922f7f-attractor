"""Run the real HTTP snow experiment; backend API and V2 worker must be running.

Usage: python -m scripts.demo_v2 --url http://127.0.0.1:8000 --out artifacts/v2-demo.json
All displayed values come from the server. This script does not implement simulation rules.
"""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZipFile


class DemoClient:
    def __init__(self, base_url, token=None, timeout=90):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, path, payload=None, *, key=None, binary=False):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = Request(self.base_url + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                return response.read() if binary else json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{request.get_method()} {path}: HTTP {error.code}: {detail}") from error

    def settled(self, run_id):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            run = self.request(f"/runs/{run_id}")
            if run["status"] in ("failed", "cancelled"):
                raise RuntimeError(f"Run stopped: {run.get('error', run['status'])}")
            if not run["pendingCommand"]:
                return run
            time.sleep(.2)
        raise TimeoutError("Run did not finish its step. Check API/worker logs and database configuration.")

    def command(self, run_id, kind, payload=None):
        run = self.request(f"/runs/{run_id}")
        key = "demo-command-" + uuid4().hex
        body = {"commandId": key, "idempotencyKey": key,
                "expectedStateVersion": run["stateVersion"], "type": kind,
                "payload": payload or {}, "issuedBy": "local-user"}
        accepted = self.request(f"/runs/{run_id}/commands", body, key=key)
        if not accepted["accepted"]:
            raise RuntimeError(f"Command was not accepted: {accepted}")
        return self.settled(run_id)

    def experiment(self, body):
        result = self.request("/experiments", body, key="demo-experiment-" + uuid4().hex)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            result = self.request(f"/experiments/{result['experimentId']}")
            if result["status"] == "completed":
                return result
            if result["status"] in ("failed", "cancelled"):
                raise RuntimeError(f"Experiment stopped: {result.get('error', result['status'])}")
            time.sleep(.2)
        raise TimeoutError("Experiment exceeded the demo wait budget. Check worker logs.")


def demonstrate(client):
    catalog = client.request("/v2/catalog")
    scenario = client.request("/scenarios", {"mode": "dynamic-v2", "name": "Snow response HTTP demo",
                                            "weatherScenarioId": "snow", "timeMode": "operational"})
    created = client.request("/runs", {"scenarioId": scenario["id"], "seed": 42, "horizon": 1440},
                             key="demo-run-" + uuid4().hex)
    run_id = created["runId"]
    warmup = client.command(run_id, "clock.step", {"minutes": 120})
    if warmup["simMinute"] != 120:
        raise AssertionError("The 120-minute step must advance exactly 120 model minutes")
    checkpoint = client.request(f"/runs/{run_id}/checkpoints", {})
    branches = [client.request(f"/runs/{run_id}/branches", {"checkpointId": checkpoint["id"]},
                               key="demo-branch-" + uuid4().hex)["runId"] for _ in range(2)]
    # Crew and destination exist in authoritative state, not invented resource IDs.
    district_ids = {district["id"] for district in warmup["state"]["districts"]}
    if "nura" not in district_ids:
        raise AssertionError("The documented demo needs the synthetic Nura district")
    donor = next(crew for crew in warmup["state"]["crews"] if crew["districtId"] != "nura")
    intervention = {"type": "crew.reassign", "payload": {"crewId": donor["id"], "districtId": "nura"}}
    client.command(branches[1], intervention["type"], intervention["payload"])
    final_states = [client.command(branch, "clock.step", {"minutes": 720}) for branch in branches]
    if any(run["simMinute"] != 840 for run in final_states):
        raise AssertionError("Branches must be compared at the same model minute")
    comparison = []
    for branch in branches:
        projection = client.request(f"/runs/{branch}/metrics")
        latest = {}
        for evidence in projection["evidence"]:
            if evidence["districtId"] is None:
                latest[evidence["metric"]] = evidence
        comparison.append({"runId": branch, "metrics": list(latest.values())})
    events = client.request(f"/runs/{branches[1]}/events?stream=false")["events"]
    causal_event = next((event for event in reversed(events)
                         if event["type"] == "appeal.created" and event["causedBy"]), None)
    if causal_event is None:
        raise AssertionError("Snow demo did not produce an experience-backed appeal")
    trace = client.request(f"/runs/{branches[1]}/trace/{causal_event['id']}")
    if len(trace["events"]) < 2:
        raise AssertionError("Causal trace must include the event and its upstream cause")
    experiment = client.experiment({"scenarioId": scenario["id"], "seeds": [11, 23, 37],
                                    "warmup": 120, "horizon": 840, "intervention": intervention})
    if len(experiment["pairs"]) != 3 or not experiment["summary"]:
        raise AssertionError("Expected a paired three-seed report with outcome intervals")
    assistant = client.request("/assistant/messages", {"runId": branches[1],
                                                       "message": "Что произошло после снегопада и на какие данные опирается вывод?"})
    if not assistant["claims"] or assistant["mode"] != "rule-based":
        raise AssertionError("Expected an evidence-backed, explicitly rule-based explanation")
    archive = client.request(f"/runs/{branches[1]}/export", binary=True)
    with ZipFile(BytesIO(archive)) as exported:
        if exported.testzip() is not None:
            raise AssertionError("Export archive has a checksum error")
        exported_files = exported.namelist()
        if set(exported_files) != {"manifest.json", "run.json", "scenario.json", "metrics.json"}:
            raise AssertionError("Export is missing a required reproducibility artifact")
    return {
        "mode": "dynamic-v2", "dataStatus": "synthetic-not-calibrated",
        "modelVersion": catalog["modelVersion"], "dataSnapshotId": scenario["dataSnapshotId"],
        "scenarioId": scenario["id"], "runId": run_id, "checkpointId": checkpoint["id"],
        "simMinute": 840, "branches": comparison, "intervention": intervention,
        "causalTrace": trace, "experiment": experiment,
        "assistantMode": assistant["mode"], "assistantClaims": assistant["claims"],
        "exportFiles": exported_files, "exportBytes": len(archive),
    }, archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, help="Save server-derived JSON evidence")
    parser.add_argument("--archive", type=Path, help="Save exported run ZIP")
    parser.add_argument("--timeout", type=float, default=90, help="Maximum wait per operation, seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    output, archive = demonstrate(DemoClient(args.url, os.getenv("AKIM_RUN_TOKEN"), args.timeout))
    text = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        args.archive.write_bytes(archive)
    print(text)


if __name__ == "__main__":
    main()
