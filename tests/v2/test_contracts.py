"""One compact contract walk through real persisted V2 responses."""
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from data_gate import create_memory_gate
from engine.v2.application.controller import RunController
from engine.v2.infrastructure.datasets import load_demo_snapshot
from engine.v2.infrastructure.store import SqliteStore
from services.api.v2 import metric_projection
from services.api.v2_contracts import CommandRequest, RunRequest, ScenarioRequest

CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts"


class V2ContractsTest(unittest.TestCase):
    def test_real_responses_match_published_json_schemas(self):
        schemas = {}
        registry = Registry()
        for path in CONTRACTS.glob("v2-*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))

        def validate(name, value, definition=None):
            schema = schemas[f"v2-{name}.schema.json"]
            if definition:
                schema = {"$ref": f"{schema['$id']}#/$defs/{definition}"}
            Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)

        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(Path(directory) / "state.sqlite3")
            controller = RunController(store)
            published = load_demo_snapshot(create_memory_gate())
            scenario_input = ScenarioRequest(name="Contract fixture").model_dump()
            validate("scenario", scenario_input, "createRequest")
            scenario = controller.scenario(scenario_input, published)
            validate("scenario", scenario)
            request = RunRequest(scenarioId=scenario["id"], seed=42, horizon=240).model_dump()
            validate("run", request, "createRequest")
            run = controller.create_run(request, "contract-run")
            validate("run", run)
            validate("run-manifest", run["manifest"])
            command = CommandRequest(commandId="contract-step", idempotencyKey="contract-step",
                                     expectedStateVersion=0, type="clock.step", payload={"minutes":120}).model_dump()
            validate("command", command)
            validate("command", controller.command(run["runId"], command), "accepted")
            while controller.work_run(run["runId"]):
                pass
            run = controller.view(run["runId"])
            validate("run", run)
            checkpoint = controller.checkpoint(run["runId"])
            validate("checkpoint", checkpoint)
            branch = controller.branch(run["runId"], checkpoint["id"], "contract-branch")
            validate("run", branch)
            events = controller.events(run["runId"])
            self.assertTrue(events)
            for event in events:
                validate("event", event)
            metrics = metric_projection(store.read("run", run["runId"]))
            self.assertTrue(metrics["series"])
            validate("metrics", metrics)
            for evidence in metrics["evidence"]:
                validate("evidence", evidence)
