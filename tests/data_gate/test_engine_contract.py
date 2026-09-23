"""Контракт со слоем симуляции: снимок Data Gate грузится движком V1 без адаптации.

Тесты пропускаются, пока в ветке нет engine/ (слой симуляции в другой ветке),
и включаются сами после слияния.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.data_gate.helpers import REPO_ROOT, memory_gate, passport, source_bytes

try:
    from engine.v1 import Selection, create_official_service
except ImportError:  # слой симуляции ещё не слит
    create_official_service = None

ENGINE_SNAPSHOT = REPO_ROOT / "data" / "v1" / "official-v1.snapshot.json"
CONTROL = (("M7", "nura"), ("M8", "nura"), ("M10", "nura"), ("M12", None), ("M5", "saryarka"))


def published_payload():
    gate = memory_gate()
    return gate.publish(gate.create_import(source_bytes(), "source-text-v1", passport()).id).payload


@unittest.skipIf(create_official_service is None, "engine/v1 ещё не в этой ветке")
class EngineContractTest(unittest.TestCase):
    def test_golden_numbers_from_data_gate_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(json.dumps(published_payload(), ensure_ascii=False), encoding="utf-8")
            service = create_official_service(path)
            self.assertAlmostEqual(service.inspect_baseline().score, 52.55768, places=5)
            result = service.evaluate(tuple(Selection(m, d) for m, d in CONTROL))
            self.assertTrue(result.valid)
            self.assertAlmostEqual(result.score, 56.54307, places=5)
            self.assertEqual(result.cost, 95)


@unittest.skipUnless(ENGINE_SNAPSHOT.exists(), "data/v1/official-v1.snapshot.json ещё не в этой ветке")
class HandWrittenSnapshotTest(unittest.TestCase):
    def test_source_and_hand_written_snapshot_agree(self) -> None:
        engine = json.loads(ENGINE_SNAPSHOT.read_text(encoding="utf-8"))
        ours = dict(published_payload())
        for key, expected in engine.items():
            actual = ours[key]
            if key in ("districts", "measures"):
                actual = [{k: v for k, v in item.items() if k in expected[0]} for item in actual]
            self.assertEqual(actual, expected, key)
