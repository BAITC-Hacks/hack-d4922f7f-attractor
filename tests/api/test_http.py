import unittest

from fastapi.testclient import TestClient

from api.main import app


class SimulationHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_and_catalog_contract(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        catalog = self.client.get("/catalog").json()

        self.assertEqual(len(catalog["districts"]), 5)
        self.assertEqual(len(catalog["indicators"]), 10)
        self.assertEqual(len(catalog["measures"]), 14)
        self.assertIn("name", catalog["measures"][0])
        self.assertEqual(catalog["districts"][3]["id"], "baykonur")
        self.assertTrue(all("unit" in indicator and "weight" in indicator for indicator in catalog["indicators"]))

    def test_versioned_frontend_request_evaluates_to_frontend_dto(self) -> None:
        payload = {
            "versions": {
                "catalogVersion": "official-v1",
                "dataSnapshotId": "astana-v1-source-dataset",
                "modelVersion": "official-v1",
                "rulesVersion": "official-v1",
            },
            "selections": [
                {"measureId": "M7", "districtId": "nura"},
                {"measureId": "M8", "districtId": "nura"},
                {"measureId": "M10", "districtId": "nura"},
                {"measureId": "M12", "districtId": None},
                {"measureId": "M5", "districtId": "saryarka"},
            ],
        }
        response = self.client.post("/v1/evaluate", json=payload)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["score"], 56.54307)
        self.assertEqual(len(result["districtScores"]), 5)
        self.assertEqual(len(result["indicators"]), 5)
        self.assertIn("averageContribution", result["decomposition"]["delta"])

    def test_selections_only_snake_case_accepts_frontend_district_alias(self) -> None:
        payload = {
            "selections": [
                {"measure_id": "M1", "district_id": "baykonur"},
                {"measure_id": "M2", "district_id": None},
                {"measure_id": "M4", "district_id": "esil"},
                {"measure_id": "M5", "district_id": "saryarka"},
                {"measure_id": "M8", "district_id": "nura"},
            ]
        }

        result = self.client.post("/v1/validate", json=payload).json()

        self.assertTrue(result["valid"], result["issues"])
        self.assertEqual(result["cost"], 100)


if __name__ == "__main__":
    unittest.main()
