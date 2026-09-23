import unittest

from engine.v1 import create_official_service
from engine.v1.domain.model import Selection


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


class PortfolioValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = create_official_service()

    def test_requires_exactly_five_measures(self) -> None:
        four = self.service.validate(
            (
                Selection("M4", "esil"),
                Selection("M9", "nura"),
                Selection("M10", "nura"),
                Selection("M12"),
            )
        )
        six = self.service.validate(
            (
                Selection("M4", "esil"),
                Selection("M6"),
                Selection("M9", "nura"),
                Selection("M10", "nura"),
                Selection("M12"),
                Selection("M14"),
            )
        )

        self.assertIn("selection_count", issue_codes(four))
        self.assertIn("selection_count", issue_codes(six))

    def test_rejects_duplicate_and_unknown_measure(self) -> None:
        duplicate = self.service.validate(
            (
                Selection("M9", "nura"),
                Selection("M9", "esil"),
                Selection("M10", "nura"),
                Selection("M12"),
                Selection("M14"),
            )
        )
        unknown = self.service.validate(
            (
                Selection("M404", "nura"),
                Selection("M9", "nura"),
                Selection("M10", "nura"),
                Selection("M12"),
                Selection("M14"),
            )
        )

        self.assertIn("duplicate_measure", issue_codes(duplicate))
        self.assertIn("unknown_measure", issue_codes(unknown))

    def test_checks_district_by_measure_scope(self) -> None:
        selections = (
            Selection("M4"),
            Selection("M9", "unknown"),
            Selection("M10", "nura"),
            Selection("M12", "nura"),
            Selection("M14"),
        )

        codes = issue_codes(self.service.validate(selections))

        self.assertIn("district_required", codes)
        self.assertIn("unknown_district", codes)
        self.assertIn("district_not_allowed", codes)

    def test_rejects_budget_and_direction_limit(self) -> None:
        over_budget = (
            Selection("M3", "esil"),
            Selection("M5", "saryarka"),
            Selection("M7", "nura"),
            Selection("M8", "nura"),
            Selection("M13", "esil"),
        )
        too_many_social = (
            Selection("M7", "nura"),
            Selection("M8", "nura"),
            Selection("M9", "esil"),
            Selection("M10", "nura"),
            Selection("M12"),
        )

        self.assertIn(
            "budget_exceeded", issue_codes(self.service.validate(over_budget))
        )
        self.assertIn(
            "direction_limit_exceeded",
            issue_codes(self.service.validate(too_many_social)),
        )

    def test_rejects_global_and_same_district_conflicts(self) -> None:
        global_conflict = (
            Selection("M1", "esil"),
            Selection("M3", "nura"),
            Selection("M5", "saryarka"),
            Selection("M10", "nura"),
            Selection("M12"),
        )
        self.assertIn(
            "measure_conflict_global",
            issue_codes(self.service.validate(global_conflict)),
        )
        district_conflicts = (
            (
                Selection("M4", "nura"),
                Selection("M7", "nura"),
                Selection("M10", "esil"),
                Selection("M12"),
                Selection("M14"),
            ),
            (
                Selection("M5", "nura"),
                Selection("M13", "nura"),
                Selection("M9", "esil"),
                Selection("M10", "nura"),
                Selection("M12"),
            ),
        )
        for selections in district_conflicts:
            with self.subTest(selections=selections):
                self.assertIn(
                    "measure_conflict_district",
                    issue_codes(self.service.validate(selections)),
                )

    def test_same_pair_in_different_districts_is_allowed(self) -> None:
        result = self.service.validate(
            (
                Selection("M4", "esil"),
                Selection("M7", "nura"),
                Selection("M10", "nura"),
                Selection("M12"),
                Selection("M14"),
            )
        )

        self.assertTrue(result.valid, result.issues)

    def test_budget_of_exactly_100_is_allowed(self) -> None:
        result = self.service.validate(
            (
                Selection("M1", "esil"),
                Selection("M2"),
                Selection("M4", "esil"),
                Selection("M5", "saryarka"),
                Selection("M8", "nura"),
            )
        )

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.cost, 100)
        self.assertEqual(result.remaining_budget, 0)


if __name__ == "__main__":
    unittest.main()
