import unittest

from engine.v1 import create_official_service
from engine.v1.domain.model import Selection


CONTROL_SELECTIONS = (
    Selection("M7", "nura"),
    Selection("M8", "nura"),
    Selection("M10", "nura"),
    Selection("M12"),
    Selection("M5", "saryarka"),
)


class GoldenCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = create_official_service()

    def test_baseline_matches_reference_table(self) -> None:
        baseline = self.service.inspect_baseline()

        expected_districts = {
            "esil": 62.99,
            "almaty": 57.06,
            "saryarka": 54.65,
            "baikonur": 56.63,
            "nura": 49.18,
        }
        for district_id, expected in expected_districts.items():
            self.assertAlmostEqual(
                baseline.district_scores[district_id], expected, delta=1e-8
            )
        self.assertAlmostEqual(baseline.average, 56.8624, delta=1e-8)
        self.assertEqual(baseline.critical_count, 2)
        self.assertAlmostEqual(baseline.score, 52.55768, delta=1e-8)

    def test_control_portfolio_matches_reference_table(self) -> None:
        result = self.service.evaluate(CONTROL_SELECTIONS)

        self.assertTrue(result.valid)
        self.assertEqual(result.cost, 95)
        self.assertEqual(result.remaining_budget, 5)
        expected_districts = {
            "esil": 63.4275,
            "almaty": 57.4975,
            "saryarka": 56.3,
            "baikonur": 57.0675,
            "nura": 52.9625,
        }
        for district_id, expected in expected_districts.items():
            self.assertAlmostEqual(
                result.district_scores[district_id], expected, delta=1e-8
            )
        self.assertAlmostEqual(result.average, 58.0776, delta=1e-8)
        self.assertEqual(result.critical_count, 0)
        self.assertAlmostEqual(result.score, 56.54307, delta=1e-8)
        self.assertAlmostEqual(result.district_score_deltas["nura"], 3.7825)
        self.assertAlmostEqual(result.indicator_deltas["nura"]["S1"], 10.0)
        self.assertAlmostEqual(result.indicator_deltas["nura"]["S2"], 8.75)
        self.assertAlmostEqual(result.indicator_deltas["nura"]["B1"], 12.5)

    def test_decomposition_reconciles_exact_score_delta(self) -> None:
        result = self.service.evaluate(CONTROL_SELECTIONS)
        decomposition = result.decomposition

        self.assertIsNotNone(decomposition)
        assert decomposition is not None
        self.assertAlmostEqual(decomposition.average_contribution.delta, 0.85064)
        self.assertAlmostEqual(decomposition.minimum_contribution.delta, 1.13475)
        self.assertAlmostEqual(decomposition.critical_penalty.delta, 2.0)
        self.assertAlmostEqual(decomposition.total.delta, 3.98539)
        self.assertAlmostEqual(
            decomposition.total.delta,
            decomposition.average_contribution.delta
            + decomposition.minimum_contribution.delta
            + decomposition.critical_penalty.delta,
        )

    def test_invalid_official_portfolio_has_no_score(self) -> None:
        result = self.service.evaluate(CONTROL_SELECTIONS[:4])

        self.assertFalse(result.valid)
        self.assertIsNone(result.score)
        self.assertIsNone(result.average)
        self.assertIsNone(result.minimum)
        self.assertIsNone(result.critical_count)
        self.assertIsNone(result.decomposition)
        self.assertEqual(dict(result.district_scores), {})
        self.assertEqual(dict(result.district_score_deltas), {})
        self.assertEqual(dict(result.indicators), {})
        self.assertEqual(dict(result.indicator_deltas), {})

    def test_api_shape_uses_documented_field_names(self) -> None:
        payload = self.service.evaluate(CONTROL_SELECTIONS).to_api_dict()

        self.assertEqual(
            set(payload),
            {
                "valid",
                "issues",
                "cost",
                "remainingBudget",
                "score",
                "districtScores",
                "districtScoreDeltas",
                "indicators",
                "indicatorDeltas",
                "average",
                "minimum",
                "criticalCount",
                "decomposition",
            },
        )

    def test_distinct_valid_portfolios_can_produce_distinct_scores(self) -> None:
        alternative = (
            Selection("M1", "esil"),
            Selection("M2"),
            Selection("M4", "esil"),
            Selection("M5", "saryarka"),
            Selection("M8", "nura"),
        )

        control = self.service.evaluate(CONTROL_SELECTIONS)
        other = self.service.evaluate(alternative)

        self.assertTrue(control.valid)
        self.assertTrue(other.valid)
        self.assertNotEqual(control.score, other.score)


if __name__ == "__main__":
    unittest.main()
