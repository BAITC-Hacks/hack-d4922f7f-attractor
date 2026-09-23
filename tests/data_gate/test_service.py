import tempfile
import unittest
from pathlib import Path

from data_gate import ImportStatus, PublishBlocked, create_file_gate
from data_gate.domain.errors import ImmutabilityViolation, NothingToRollback, UnsupportedFormat
from data_gate.infrastructure.clock import FixedClock
from tests.data_gate.helpers import as_json, memory_gate, official_payload, passport, source_bytes


class ImportLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = memory_gate()

    def test_reimport_is_idempotent(self) -> None:
        first = self.gate.create_import(source_bytes(), "source-text-v1", passport())
        second = self.gate.create_import(source_bytes(), "source-text-v1", passport())
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.gate.list_imports()), 1)
        self.assertEqual(first.status, ImportStatus.READY)

    def test_unknown_format(self) -> None:
        with self.assertRaises(UnsupportedFormat):
            self.gate.create_import(b"{}", "xlsx", passport())

    def test_critical_error_blocks_publish(self) -> None:
        payload = official_payload()
        payload["weights"]["T1"] = 0.5
        record = self.gate.create_import(as_json(payload), "city-json-v1", passport())
        self.assertEqual(record.status, ImportStatus.REJECTED)
        with self.assertRaises(PublishBlocked):
            self.gate.publish(record.id)
        self.assertIsNone(self.gate.dataset_ref("official-v1").current)

    def test_warning_needs_explicit_acceptance(self) -> None:
        feature = {"type": "Feature", "id": "p1", "geometry": {"type": "Point", "coordinates": [71.4, 51.1]}, "properties": {}}
        record = self.gate.create_import(
            as_json({"type": "FeatureCollection", "features": [feature]}), "geojson-v1", passport("astana-layers")
        )
        with self.assertRaises(PublishBlocked):
            self.gate.publish(record.id)
        snapshot = self.gate.publish(record.id, accepted_warnings=["missing_layer"])
        self.assertEqual(snapshot.accepted_warnings, ("missing_layer",))

    def test_unmapped_fields_stay_out_of_model(self) -> None:
        payload = official_payload()
        payload["secretCoefficient"] = 42
        record = self.gate.create_import(as_json(payload), "city-json-v1", passport())
        self.assertIn("secretCoefficient", record.mapping.unmapped)
        self.assertNotIn("secretCoefficient", record.payload)

    def test_report_contains_preview(self) -> None:
        record = self.gate.create_import(source_bytes(), "source-text-v1", passport())
        report = self.gate.get_report(record.id)
        self.assertIsNone(report["preview"]["baseSnapshotId"])
        self.assertGreater(report["preview"]["changeCount"], 0)


class PublishAndRollbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = memory_gate()
        self.v1 = self.gate.publish(self.gate.create_import(source_bytes(), "source-text-v1", passport()).id)
        changed = official_payload()
        changed["districts"][4]["indicators"]["S1"] = 42
        self.change_import = self.gate.create_import(as_json(changed), "city-json-v1", passport())

    def test_preview_shows_only_real_changes(self) -> None:
        preview = self.gate.preview(self.change_import.id)
        self.assertEqual(preview.base_snapshot_id, self.v1.id)
        self.assertEqual([c.path for c in preview.changes], ["districts.nura.indicators.S1"])
        self.assertEqual((preview.changes[0].before, preview.changes[0].after), (38, 42))

    def test_publish_moves_pointer_and_rollback_restores(self) -> None:
        v2 = self.gate.publish(self.change_import.id)
        v1 = self.v1.id
        self.assertNotEqual(v1, v2.id)
        self.assertEqual(self.gate.current_snapshot("official-v1").id, v2.id)
        ref = self.gate.rollback("official-v1")
        self.assertEqual(ref.current, v1)
        self.assertEqual([e.action for e in ref.history], ["publish", "publish", "rollback"])
        self.assertEqual(len(self.gate.list_snapshots("official-v1")), 2)  # lineage не удалён
        with self.assertRaises(NothingToRollback):
            self.gate.rollback("official-v1")

    def test_snapshot_payload_is_immutable_by_id(self) -> None:
        self.assertEqual(self.gate.get_snapshot(self.v1.id).payload, self.v1.payload)
        republished = self.gate.publish(self.gate.create_import(source_bytes(), "source-text-v1", passport()).id)
        self.assertEqual(republished.id, self.v1.id)

    def test_nothing_to_rollback_on_first_snapshot(self) -> None:
        with self.assertRaises(NothingToRollback):
            self.gate.rollback("official-v1")


class FileStoreTest(unittest.TestCase):
    def test_state_survives_new_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            gate = create_file_gate(root, FixedClock())
            snapshot = gate.publish(gate.create_import(source_bytes(), "source-text-v1", passport()).id)

            again = create_file_gate(root, FixedClock())
            self.assertEqual(again.current_snapshot("official-v1").payload, snapshot.payload)
            self.assertEqual(again.get_import(snapshot.import_id).status, ImportStatus.PUBLISHED)
            self.assertEqual((root / ".gitignore").read_text(), "*\n")

    def test_snapshot_file_cannot_be_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = create_file_gate(root, FixedClock())
            snapshot = gate.publish(gate.create_import(source_bytes(), "source-text-v1", passport()).id)
            path = root / "snapshots" / f"{snapshot.id}.json"
            path.write_text(path.read_text(encoding="utf-8").replace('"budget": 100', '"budget": 999'), encoding="utf-8")
            from data_gate.infrastructure.filesystem import FileSnapshotRepository, FileStore

            with self.assertRaises(ImmutabilityViolation):
                FileSnapshotRepository(FileStore(root)).add(snapshot)
