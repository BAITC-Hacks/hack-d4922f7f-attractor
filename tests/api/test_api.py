import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema
from fastapi.testclient import TestClient

from data_gate.composition import create_memory_gate
from services.api.app import create_app
from services.api.runtime import Runtime
from tests.data_gate.helpers import official_payload
from tests.v1.test_golden import CONTROL_SELECTIONS

PORTFOLIO = {"selections": [{"measureId": s.measure_id, "districtId": s.district_id}
                            for s in CONTROL_SELECTIONS]}
PASSPORT = {"datasetId": "experiment", "sourceType": "synthetic", "sourceUri": "test:synthetic",
            "licenseOrPermission": "test", "retrievedAt": "2026-09-23", "validFrom": "2026-09-23"}


class APITests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"AKIM_LLM_ENABLED": "0", "AKIM_CORS_ORIGINS": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.runtime = Runtime(create_memory_gate())
        self.client = TestClient(create_app(self.runtime, admin_token="test-only"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def admin_post(self, path, body):
        return self.client.post(path, json=body, headers={"Authorization": "Bearer test-only"})

    def test_catalog_and_health_use_published_snapshot(self):
        catalog = self.client.get("/catalog").json()
        self.assertEqual(len(catalog["districts"]), 5)
        self.assertEqual(len(catalog["measures"]), 14)
        self.assertEqual(len(catalog["indicators"]), 10)
        self.assertEqual(catalog["sourceType"], "synthetic")
        self.assertEqual(catalog["versions"]["dataSnapshotId"], self.runtime.published.id)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_control_http_result_and_domain_schema(self):
        response = self.client.post("/v1/evaluate", json=PORTFOLIO)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["score"], 56.54307)
        self.assertEqual(result["aqolScore"], result["score"])
        self.assertEqual(result["cost"], 95)
        result.pop("versions")
        result.pop("aqolScore")
        schema = json.loads((Path(__file__).parents[2] / "packages/contracts/v1-result.schema.json").read_text())
        jsonschema.validate(result, schema)

    def test_invalid_portfolio_is_200_with_null_score(self):
        result = self.client.post("/v1/evaluate", json={"selections": []}).json()
        self.assertFalse(result["valid"])
        self.assertIsNone(result["score"])
        self.assertIsNone(result["aqolScore"])
        self.assertEqual(result["issues"][0]["code"], "selection_count")

    def test_strict_requests_unknown_fields_types_and_limits(self):
        for request in ({}, {"selections": [], "score": 999},
                        {"selections": [{"measureId": True, "districtId": None}]},
                        {"selections": [{"measureId": "M12"}]},
                        {"selections": PORTFOLIO["selections"] * 21}):
            with self.subTest(request=request):
                response = self.client.post("/v1/evaluate", json=request)
                self.assertEqual(response.status_code, 422)
                self.assertIn("error", response.json())
        response = self.client.post("/v1/evaluate", content="{bad", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_version_mismatch_is_409_on_every_v1_endpoint(self):
        versions = {**self.runtime.versions, "modelVersion": "stale"}
        for path in ("validate", "evaluate", "alternatives", "analysis"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(f"/v1/{path}",
                                                  json={**PORTFOLIO, "versions": versions}).status_code, 409)
        self.assertEqual(self.client.post("/v1/evaluate",
                                          json={**PORTFOLIO, "versions": self.runtime.versions}).status_code, 200)

    def test_search_result_is_valid_improves_and_stable(self):
        first = self.client.post("/v1/alternatives", json=PORTFOLIO).json()
        second = self.client.post("/v1/alternatives", json=PORTFOLIO).json()
        self.assertEqual(first, second)
        self.assertFalse(first["isGlobalOptimum"])
        self.assertGreater(first["evaluatedCandidates"], 0)
        self.assertTrue(first["results"])
        for alternative in first["results"]:
            actual = self.client.post("/v1/evaluate", json={"selections": alternative["selections"]}).json()
            self.assertEqual(alternative["evaluation"], actual)
            self.assertGreater(actual["score"], 56.54307)

    def test_bad_search_constraints_are_not_silently_ignored(self):
        for constraints in ({"maxReplacements": 2}, {"maxReplacements": True}, {"resultLimit": 99},
                            {"allowedDistricts": ["unknown"]}, {"unknown": "ignored?"}):
            with self.subTest(constraints=constraints):
                response = self.client.post("/v1/alternatives", json={**PORTFOLIO, "constraints": constraints})
                self.assertEqual(response.status_code, 422)

    def test_analysis_fallback_and_invalid_do_not_call_provider(self):
        result = self.client.post("/v1/analysis", json=PORTFOLIO).json()
        self.assertEqual(result["mode"], "rule-based")
        self.assertEqual(result["status"], "not_configured")
        self.assertTrue(result["claims"])
        invalid = self.client.post("/v1/analysis", json={"selections": []}).json()
        self.assertEqual(invalid["status"], "invalid_portfolio")
        self.assertEqual(invalid["claims"], [])

    def test_data_gate_requires_auth_and_reserves_official_dataset(self):
        body = {"content": json.dumps(official_payload()), "format": "city-json-v1", "passport": PASSPORT}
        self.assertEqual(self.client.post("/datasets/imports", json=body).status_code, 403)
        response = self.admin_post("/datasets/imports",
                                   {**body, "passport": {**PASSPORT, "datasetId": "official-v1"}})
        self.assertEqual(response.status_code, 403)

    def test_import_report_publish_end_to_end_does_not_change_official_score(self):
        before = self.client.post("/v1/evaluate", json=PORTFOLIO).json()
        payload = official_payload()
        payload["budget"] = 200
        body = {"content": json.dumps(payload), "format": "city-json-v1", "passport": PASSPORT}
        response = self.admin_post("/datasets/imports", body)
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()
        self.assertFalse(record["report"]["blocksPublication"])
        report = self.client.get(f"/datasets/imports/{record['id']}/report",
                                 headers={"Authorization": "Bearer test-only"})
        self.assertEqual(report.status_code, 200)
        published = self.admin_post(f"/datasets/imports/{record['id']}/publish", {})
        self.assertEqual(published.status_code, 200)
        self.assertEqual(self.admin_post("/datasets/imports", body).json()["id"], record["id"])
        self.assertEqual(self.client.post("/v1/evaluate", json=PORTFOLIO).json(), before)

    def test_bad_data_cannot_be_published(self):
        payload = official_payload()
        payload["districts"] = []
        record = self.admin_post("/datasets/imports", {
            "content": json.dumps(payload), "format": "city-json-v1", "passport": PASSPORT}).json()
        self.assertTrue(record["report"]["blocksPublication"])
        self.assertEqual(self.admin_post(f"/datasets/imports/{record['id']}/publish", {}).status_code, 409)

    def test_oversized_and_invalid_json_imports(self):
        self.assertEqual(self.client.post("/v1/evaluate", content=b"x" * 1_200_001).status_code, 413)
        for content in ('{"budget":NaN}', '{"budget":1e999}', '{"budget":1,"budget":2}'):
            with self.subTest(content=content):
                self.assertEqual(self.admin_post("/datasets/imports", {
                    "content": content, "format": "city-json-v1", "passport": PASSPORT}).status_code, 422)

    def test_openapi_has_evaluate_response_and_required_request_fields(self):
        spec = self.client.get("/openapi.json").json()
        self.assertIn("/v1/evaluate", spec["paths"])
        self.assertIn("score", spec["components"]["schemas"]["EvaluationResponse"]["properties"])
        self.assertEqual(set(spec["components"]["schemas"]["SelectionInput"]["required"]),
                         {"measureId", "districtId"})

    def test_llm_limit_misconfiguration_fails_closed(self):
        with patch.dict(os.environ, {"AKIM_LLM_ENABLED": "1", "OPENAI_API_KEY": "do-not-use",
                                    "OPENAI_MODEL": "do-not-use", "AKIM_LLM_MAX_ANALYSES": "invalid"}):
            report = self.runtime.analysis(tuple(s for s in CONTROL_SELECTIONS))
        self.assertEqual(report["status"], "llm_budget_exhausted")
