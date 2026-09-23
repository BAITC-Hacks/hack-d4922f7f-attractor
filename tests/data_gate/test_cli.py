import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BootstrapCLITests(unittest.TestCase):
    def test_bootstrap_from_another_directory_respects_store_and_out(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "PYTHONPATH": str(repo)}
            env.pop("AKIM_DATA_GATE_DIR", None)
            store = Path(tmp) / "custom-store"
            command = [sys.executable, "-m", "data_gate", "--store", str(store), "bootstrap"]
            run = subprocess.run(command, cwd=tmp, env=env, text=True, capture_output=True, check=True)
            first = json.loads(run.stdout)
            exported = Path(first["exportedTo"])
            self.assertEqual(exported, store / "exports" / "official-v1.snapshot.json")
            self.assertTrue(exported.is_file())
            self.assertFalse((Path(tmp) / "var").exists())
            out = Path(tmp) / "explicit.json"
            again = subprocess.run(command + ["--out", str(out)], cwd=tmp, env=env,
                                   text=True, capture_output=True, check=True)
            second = json.loads(again.stdout)
            self.assertEqual(first["snapshot"]["id"], second["snapshot"]["id"])
            self.assertEqual(Path(second["exportedTo"]), out)
            self.assertEqual(json.loads(out.read_text()), json.loads(exported.read_text()))

    def test_default_store_is_under_current_directory(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "PYTHONPATH": str(repo)}
            env.pop("AKIM_DATA_GATE_DIR", None)
            run = subprocess.run([sys.executable, "-m", "data_gate", "bootstrap"],
                                 cwd=tmp, env=env, text=True, capture_output=True, check=True)
            self.assertEqual(Path(json.loads(run.stdout)["exportedTo"]).resolve(),
                             (Path(tmp) / "var/data-gate/exports/official-v1.snapshot.json").resolve())
