import tempfile
import unittest
import copy
import json
from dataclasses import replace
from pathlib import Path

from data_gate import create_file_gate
from data_gate.domain.errors import ImmutabilityViolation, InvalidPassport, SourceParseError
from data_gate.domain.quality import CITY_V1, TERRITORY_GEOJSON_V1, check_payload
from data_gate.infrastructure.parsers.city_json import load_json
from data_gate.infrastructure.parsers.source_text_v1 import _integer
from engine.v1.infrastructure.json_snapshot import SnapshotFormatError, snapshot_from_payload
from tests.data_gate.helpers import memory_gate, official_payload, passport, source_bytes


class RegressionTests(unittest.TestCase):
    def test_json_duplicate_keys_overflow_and_deep_nesting_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"a":1e999}', '{"a":NaN}', "[" * 1100 + "0" + "]" * 1100):
            with self.subTest(raw=raw[:30]), self.assertRaises(SourceParseError):
                load_json(raw.encode())

    def test_fractional_lag_is_not_truncated(self):
        with self.assertRaises(SourceParseError):
            _integer("2.5", "лаг")

    def test_raw_engine_loader_rejects_bool_nonfinite_and_fractional_rules(self):
        for field, value in (("budget", True), ("budget", float("nan")), ("budget", "100"),
                             ("horizonQuarters", 8.5), ("requiredSelectionCount", 0),
                             ("budget", 10 ** 400)):
            with self.subTest(field=field, value=value), self.assertRaises(SnapshotFormatError):
                payload = official_payload()
                payload[field] = value
                snapshot_from_payload(payload)

    def test_large_numbers_and_duplicate_synergies_are_critical(self):
        for changes in ({"weights": {"T1": 1e308, "T2": 1e308}},
                        {"budget": 10 ** 400},
                        {"synergies": official_payload()["synergies"] * 2}):
            payload = official_payload()
            payload.update(changes)
            with self.subTest(changes=changes):
                self.assertTrue(any(i.severity.value == "critical" for i in check_payload(CITY_V1, payload, {})))

    def test_malformed_json_leaves_never_crash_quality_gate(self):
        payload = official_payload()
        probes = [None, True, [], {}, "bad", 10 ** 400]
        locations = [(key,) for key in payload]
        locations += [(name, 0, key) for name in ("districts", "measures", "synergies")
                      for key in payload[name][0]]
        for path in locations:
            for probe in probes:
                candidate = copy.deepcopy(payload)
                parent = candidate
                for part in path[:-1]:
                    parent = parent[part]
                parent[path[-1]] = probe
                with self.subTest(path=path, probe=probe):
                    check_payload(CITY_V1, candidate, {})

    def test_staging_payload_tamper_is_rejected_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = create_file_gate(Path(tmp))
            record = gate.create_import(source_bytes(), "source-text-v1", passport())
            path = Path(tmp) / "imports" / f"{record.id}.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["payload"]["budget"] = 999
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ImmutabilityViolation):
                gate.publish(record.id)

    def test_malformed_city_produces_critical_report(self):
        cases = [
            ("districts", []),
            ("synergies", [{"measureIds": ["M1", {}], "bonus": 2}]),
            ("synergies", [{"measureIds": ["M1", "M2"], "targetMeasureId": "M1",
                            "indicator": "T1", "bonus": "free"}]),
            ("globalConflicts", [["M1", []]]),
            ("criticalPenalty", -1),
            ("criticalThreshold", 101),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = official_payload()
                payload[field] = value
                issues = check_payload(CITY_V1, payload, {})
                self.assertTrue(any(i.severity.value == "critical" for i in issues))

    def test_geojson_non_object_properties_is_reported(self):
        payload = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "p1",
             "geometry": {"type": "Point", "coordinates": [71, 51]},
             "properties": ["bad"]}
        ]}
        self.assertTrue(check_payload(TERRITORY_GEOJSON_V1, payload, {}))

    def test_returned_payload_cannot_mutate_stored_import_or_snapshot(self):
        gate = memory_gate()
        record = gate.create_import(source_bytes(), "source-text-v1", passport())
        record.payload["budget"] = 999
        self.assertEqual(gate.get_import(record.id).payload["budget"], 100)
        snapshot = gate.publish(record.id)
        snapshot.payload["districts"][0]["indicators"]["T1"] = 0
        self.assertEqual(gate.get_snapshot(snapshot.id).payload["districts"][0]["indicators"]["T1"], 45)
        listed = gate.list_snapshots()[0]
        listed.payload["budget"] = 999
        self.assertEqual(gate.current_snapshot("official-v1").payload["budget"], 100)

    def test_import_identity_includes_provenance(self):
        gate = memory_gate()
        first = gate.create_import(source_bytes(), "source-text-v1", passport())
        second = gate.create_import(
            source_bytes(), "source-text-v1",
            replace(passport(), source_uri="different-source"),
        )
        self.assertNotEqual(first.id, second.id)
        a, b = gate.publish(first.id), gate.publish(second.id)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(b.passport.input.source_uri, "different-source")

    def test_tampered_file_is_rejected_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = create_file_gate(Path(tmp))
            snap = gate.publish(gate.create_import(source_bytes(), "source-text-v1", passport()).id)
            path = Path(tmp) / "snapshots" / f"{snap.id}.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('"budget": 100', '"budget": 999'), encoding="utf-8")
            with self.assertRaises(ImmutabilityViolation):
                gate.get_snapshot(snap.id)

    def test_passport_rejects_bad_dates_nulls_and_reversed_interval(self):
        for changes in ({"retrieved_at": "yesterday"}, {"source_uri": None},
                        {"valid_to": "2020-01-01"}, {"dataset_id": "ok\n"}):
            with self.subTest(changes=changes), self.assertRaises(InvalidPassport):
                replace(passport(), **changes)
