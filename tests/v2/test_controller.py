"""Persistence and command acceptance tests, independent of HTTP and wall-clock sleeps."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from data_gate import create_memory_gate
from engine.v2.application.controller import RunController, RunError, digest
from engine.v2.infrastructure.datasets import load_demo_snapshot
from engine.v2.infrastructure.store import SqliteStore


class RunControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.published = load_demo_snapshot(create_memory_gate())

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runs.sqlite3"
        self.store = SqliteStore(self.path)
        self.controller = RunController(self.store, code_revision="controller-test")
        self.scenario = self.controller.scenario({"name": "Snow", "weatherScenarioId": "snow"}, self.published)
        self.request = {"scenarioId": self.scenario["id"], "seed": 42, "horizon": 1440}
        self.run_id = self.controller.create_run(self.request, "create-test")["runId"]
        self.command_counter = 0

    def command(self, kind, payload=None, run_id=None):
        self.command_counter += 1
        identity = f"command-{self.command_counter}"
        run_id = run_id or self.run_id
        return {"commandId": identity, "idempotencyKey": identity,
                "expectedStateVersion": self.controller.view(run_id)["stateVersion"],
                "type": kind, "payload": payload or {}, "issuedBy": "local-user"}

    def step(self, minutes, run_id=None):
        run_id = run_id or self.run_id
        self.controller.command(run_id, self.command("clock.step", {"minutes": minutes}, run_id))
        self.drain(run_id)

    def drain(self, run_id):
        # Fixed upper bound catches stuck queues without an unbounded test.
        for _ in range(50):
            if not self.controller.view(run_id)["pendingCommand"]:
                return
            self.assertTrue(self.controller.work_run(run_id))
            self.assertNotEqual(self.controller.view(run_id)["status"], "failed")
        self.fail("Pending command did not finish in the bounded work budget")

    def test_scenario_and_run_creation_are_immutable_and_idempotent(self):
        again = self.controller.scenario({"name": "Snow", "weatherScenarioId": "snow"}, self.published)
        self.assertEqual(self.scenario, again)
        self.assertNotIn("snapshot", self.scenario)
        self.assertEqual(self.controller.create_run(self.request, "create-test")["runId"], self.run_id)
        with self.assertRaises(RunError) as error:
            self.controller.create_run({**self.request, "seed": 7}, "create-test")
        self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assertEqual(len(self.store.keys("run")), 1)

    def test_duplicate_command_does_not_apply_step_twice(self):
        command = self.command("clock.step", {"minutes": 120})
        accepted = self.controller.command(self.run_id, command)
        self.drain(self.run_id)
        version = self.controller.view(self.run_id)["stateVersion"]
        self.assertEqual(self.controller.command(self.run_id, command), accepted)
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 120)
        self.assertEqual(self.controller.view(self.run_id)["stateVersion"], version)
        with self.assertRaises(RunError) as error:
            self.controller.command(self.run_id, {**command, "payload": {"minutes": 240}})
        self.assertEqual(error.exception.code, "idempotency_conflict")

    def test_conflicting_version_and_invalid_step_leave_no_writes(self):
        before = self.store.read("run", self.run_id)
        stale = {**self.command("clock.speed", {"speed": 120}), "expectedStateVersion": 99}
        with self.assertRaises(RunError) as error:
            self.controller.command(self.run_id, stale)
        self.assertEqual(error.exception.status, 409)
        for minutes in (0, -1, 1441, True):
            with self.subTest(minutes=minutes), self.assertRaises(RunError):
                self.controller.command(self.run_id, self.command("clock.step", {"minutes": minutes}))
        self.assertEqual(self.store.read("run", self.run_id), before)

    def test_new_controller_resumes_durable_pending_step(self):
        self.controller.command(self.run_id, self.command("clock.step", {"minutes": 180}))
        self.assertTrue(self.controller.work_run(self.run_id))
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 60)
        self.controller = RunController(SqliteStore(self.path), code_revision="controller-test")
        self.assertTrue(self.controller.view(self.run_id)["pendingCommand"])
        self.drain(self.run_id)
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 180)
        self.assertEqual(self.controller.view(self.run_id)["manifest"]["codeRevision"], "controller-test")

    def test_paused_step_can_resume_and_cancel_is_terminal(self):
        self.controller.command(self.run_id, self.command("clock.step", {"minutes": 180}))
        self.controller.work_run(self.run_id)
        self.controller.command(self.run_id, self.command("clock.pause"))
        self.assertFalse(self.controller.work_run(self.run_id))
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 60)
        self.controller.command(self.run_id, self.command("clock.resume"))
        self.drain(self.run_id)
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 180)
        self.controller.command(self.run_id, self.command("clock.cancel"))
        self.assertFalse(self.controller.work_run(self.run_id))
        self.assertEqual(self.controller.view(self.run_id)["status"], "cancelled")
        with self.assertRaises(RunError) as error:
            self.controller.command(self.run_id, self.command("clock.resume"))
        self.assertEqual(error.exception.code, "run_terminal")

    def test_branches_share_past_but_not_future_and_replay_matches(self):
        self.step(120)
        checkpoint = self.controller.checkpoint(self.run_id)
        first = self.controller.branch(self.run_id, checkpoint["id"], "branch-first")["runId"]
        second = self.controller.branch(self.run_id, checkpoint["id"], "branch-second")["runId"]
        self.assertEqual(self.controller.branch(self.run_id, checkpoint["id"], "branch-first")["runId"], first)
        self.step(120, first)
        self.assertEqual(self.controller.view(second)["simMinute"], 120)
        self.step(120, second)
        self.assertEqual(self.store.read("run", first)["state"], self.store.read("run", second)["state"])
        first_checkpoint = self.controller.view(first)["checkpoints"][0]["id"]
        self.assertTrue(self.controller.replay(first, first_checkpoint)["matches"])
        self.assertEqual(self.controller.view(self.run_id)["simMinute"], 120)

    def test_corrupt_checkpoint_is_rejected_and_event_resume_has_no_gap(self):
        self.step(120)
        events = self.controller.events(self.run_id)
        self.assertGreater(len(events), 1)
        head = self.controller.events(self.run_id, limit=2)
        tail = self.controller.events(self.run_id, after=head[-1]["seq"])
        self.assertEqual(head + tail, events)
        self.assertEqual(len({event["id"] for event in events}), len(events))
        self.assertEqual(sorted(event["seq"] for event in events), [event["seq"] for event in events])
        trace = self.controller.trace(self.run_id, events[-1]["id"])
        self.assertIn(events[-1]["id"], [event["id"] for event in trace["events"]])
        checkpoint = self.controller.checkpoint(self.run_id)
        with self.store.transaction("run", self.run_id) as record:
            record["checkpoints"][checkpoint["id"]]["state"]["simMinute"] += 1
        with self.assertRaises(RunError) as error:
            self.controller.branch(self.run_id, checkpoint["id"], "corrupted")
        self.assertEqual(error.exception.code, "checkpoint_corrupted")

    def test_store_read_is_detached_and_exception_rolls_back(self):
        before = self.store.read("run", self.run_id)
        detached = self.store.read("run", self.run_id)
        detached["status"] = "cancelled"
        self.assertNotEqual(digest(detached), digest(self.store.read("run", self.run_id)))
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.transaction("run", self.run_id) as record:
                record["status"] = "cancelled"
                raise RuntimeError("rollback")
        self.assertEqual(self.store.read("run", self.run_id), before)


if __name__ == "__main__":
    unittest.main()
