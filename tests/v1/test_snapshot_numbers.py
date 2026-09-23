import json
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from engine.v1 import load_snapshot
from engine.v1.infrastructure.json_snapshot import SnapshotFormatError


class SnapshotNumberTests(unittest.TestCase):
    def test_rejects_invalid_numbers_in_every_numeric_section(self):
        paths = [
            ("budget",), ("criticalThreshold",), ("criticalPenalty",),
            ("horizonQuarters",), ("requiredSelectionCount",),
            ("maxMeasuresPerDirection",), ("weights", "T1"),
            ("districts", 0, "populationShare"),
            ("districts", 0, "indicators", "T1"),
            ("measures", 0, "cost"), ("measures", 0, "lagQuarters"),
            ("measures", 0, "effects", "T1"), ("synergies", 0, "bonus"),
        ]
        source = files("data").joinpath("v1", "official-v1.snapshot.json").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            for keys in paths:
                for invalid in (float("nan"), float("inf"), -float("inf"), "NaN", "18", True, None):
                    with self.subTest(field=keys, invalid=invalid):
                        raw = json.loads(source)
                        target = raw
                        for key in keys[:-1]:
                            target = target[key]
                        target[keys[-1]] = invalid
                        path.write_text(json.dumps(raw))
                        with self.assertRaises(SnapshotFormatError):
                            load_snapshot(path)

    def test_fractional_lag_is_not_silently_truncated(self):
        raw = json.loads(files("data").joinpath("v1", "official-v1.snapshot.json").read_text())
        raw["measures"][0]["lagQuarters"] = 2.5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(json.dumps(raw))
            with self.assertRaises(SnapshotFormatError):
                load_snapshot(path)
