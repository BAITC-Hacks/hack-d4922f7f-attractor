from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from data_gate.domain.errors import PublishBlocked, SourceParseError
from data_gate.domain.quality import check_payload
from data_gate.domain.v2_quality import observations_available_at
from data_gate.infrastructure.parsers.v2 import CsvParser, XlsxParser
from engine.v2.domain.fixtures import build_demo_dataset
from engine.v2.infrastructure.datasets import load_demo_snapshot
from tests.data_gate.helpers import as_json, memory_gate, passport


def observation(**changes):
    row = {
        "id": "one", "districtId": "arbitrary-sixth-district", "metric": "backlog",
        "value": 12, "unit": "request", "measureKind": "stock", "statistic": "total",
        "sourceType": "observed", "eventTime": "2026-01-01T00:00:00Z",
        "observedAt": "2026-01-02T00:00:00Z", "ingestedAt": "2026-01-03T00:00:00Z",
    }
    return row | changes


class V2CityDataGateTest(unittest.TestCase):
    def test_published_six_district_snapshot_is_idempotent_and_isolated(self):
        gate = memory_gate()
        published = load_demo_snapshot(gate)
        self.assertEqual(len(published.payload["districts"]), 6)
        self.assertEqual(published.id, load_demo_snapshot(gate).id)
        self.assertEqual(published.passport.schema, "v2-city-v1")
        old_population = published.payload["districts"][0]["population"]
        changed = dict(published.payload)
        changed["districts"][0]["population"] += 10
        record = gate.create_import(as_json(changed), "v2-city-json", published.passport.input)
        replacement = gate.publish(record.id)
        self.assertNotEqual(replacement.id, published.id)
        self.assertEqual(gate.get_snapshot(published.id).payload["districts"][0]["population"], old_population)
        self.assertIsNone(gate.dataset_ref("official-v1").current)

    def test_missing_and_invalid_values_block_publication(self):
        for key, bad_value in (("population", None), ("crews", -1), ("schoolCapacity", True)):
            with self.subTest(key=key):
                payload = build_demo_dataset()
                payload["districts"][0][key] = bad_value
                gate = memory_gate()
                record = gate.create_import(as_json(payload), "v2-city-json", passport("bad-v2"))
                self.assertTrue(record.report.blocks_publication)
                with self.assertRaises(PublishBlocked):
                    gate.publish(record.id)

    def test_unknown_district_names_do_not_require_v1_changes(self):
        payload = build_demo_dataset()
        payload["districts"][5]["id"] = "new-independent-district"
        gate = memory_gate()
        record = gate.create_import(as_json(payload), "v2-city-json", passport("six-districts"))
        self.assertFalse(record.report.blocks_publication, record.report.to_api_dict())

    def test_demo_matches_contract(self):
        from jsonschema import Draft202012Validator, FormatChecker
        schema_path = Path(__file__).resolve().parents[2] / "packages/contracts/v2-dataset.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(load_demo_snapshot(memory_gate()).payload)


class ObservationAdapterTest(unittest.TestCase):
    def test_csv_header_selection_and_missing_value_is_not_zero(self):
        row = observation(value=None)
        source = "metadata\n" + ",".join(row) + "\n" + ",".join("" if v is None else str(v) for v in row.values())
        parsed = CsvParser(header_row=2).parse(source.encode())
        self.assertIsNone(parsed.payload["records"][0]["value"])
        self.assertFalse(check_payload(parsed.schema, parsed.payload, {}))

    def test_three_times_prevent_future_information_leak(self):
        payload = {"records": [observation()]}
        self.assertEqual(observations_available_at(payload, "2026-01-02T12:00:00Z"), [])
        self.assertEqual(len(observations_available_at(payload, "2026-01-03T00:00:00Z")), 1)

    def test_flow_without_period_and_estimation_without_method_are_rejected(self):
        for changes, expected in (({"measureKind": "flow"}, "missing_flow_period"),
                                  ({"sourceType": "estimated"}, "missing_imputation"),
                                  ({"observedAt": None}, "invalid_time")):
            with self.subTest(changes=changes):
                issues = check_payload("observations-v1", {"records": [observation(**changes)]}, {})
                self.assertIn(expected, {issue.code for issue in issues})
        estimated = observation(sourceType="estimated", imputation={"field": "value", "method": "group-median",
                                                                     "parameters": {"district": "demo"}})
        self.assertFalse(check_payload("observations-v1", {"records": [estimated]}, {}))

    def test_xlsx_sheet_header_and_formula_rejection(self):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.create_sheet("observations")
        row = observation()
        sheet.append(["metadata"])
        sheet.append(list(row))
        sheet.append(list(row.values()))
        stream = io.BytesIO()
        book.save(stream)
        parsed = XlsxParser(sheet="observations", header_row=2).parse(stream.getvalue())
        self.assertEqual(parsed.payload["records"][0]["value"], 12)
        self.assertFalse(check_payload(parsed.schema, parsed.payload, {}))
        sheet["D3"] = "=1+1"
        stream = io.BytesIO()
        book.save(stream)
        with self.assertRaisesRegex(SourceParseError, "Formula"):
            XlsxParser(sheet="observations", header_row=2).parse(stream.getvalue())

    def test_registered_csv_runs_through_gate_quality_and_publication(self):
        row = observation()
        source = ",".join(row) + "\n" + ",".join(str(v) for v in row.values())
        gate = memory_gate()
        record = gate.create_import(source.encode(), "csv-v1", passport("observations"))
        snapshot = gate.publish(record.id)
        self.assertEqual(snapshot.payload["records"][0]["value"], 12)
