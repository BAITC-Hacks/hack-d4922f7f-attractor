import unittest

from engine.v1 import create_official_service


class OfficialSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = create_official_service().snapshot

    def test_source_dimensions_and_weights_are_exact(self) -> None:
        self.assertEqual(len(self.snapshot.districts), 5)
        self.assertEqual(len(self.snapshot.weights), 10)
        self.assertEqual(len(self.snapshot.measures), 14)
        self.assertEqual(
            dict(self.snapshot.weights),
            {
                "T1": 0.10,
                "T2": 0.10,
                "E1": 0.09,
                "E2": 0.11,
                "S1": 0.11,
                "S2": 0.11,
                "B1": 0.09,
                "B2": 0.09,
                "C1": 0.10,
                "C2": 0.10,
            },
        )

    def test_measure_catalog_matches_source_field_by_field(self) -> None:
        expected = {
            "M1": ("transport", "district", 18, 2, {"T1": 6, "T2": 9}),
            "M2": ("transport", "city", 22, 2, {"T1": 4, "B2": 3}),
            "M3": (
                "transport",
                "district",
                30,
                4,
                {"T1": 16, "T2": 20, "E2": 4},
            ),
            "M4": (
                "environment",
                "district",
                15,
                2,
                {"E1": 12, "E2": 3, "B1": 2},
            ),
            "M5": ("environment", "district", 25, 3, {"E2": 14, "C1": 4}),
            "M6": ("environment", "city", 20, 4, {"E1": 5, "E2": 3}),
            "M7": ("social", "district", 24, 3, {"S1": 16}),
            "M8": ("social", "district", 20, 3, {"S2": 14}),
            "M9": (
                "social",
                "district",
                10,
                1,
                {"S1": 3, "S2": 3, "B1": 3},
            ),
            "M10": ("safety", "district", 12, 1, {"B1": 12, "B2": 2}),
            "M11": ("safety", "district", 10, 1, {"B2": 12, "T1": -2}),
            "M12": ("services", "city", 14, 1, {"C2": 5}),
            "M13": ("services", "district", 28, 4, {"C1": 18, "E2": 2}),
            "M14": ("services", "city", 16, 1, {"C1": 5, "C2": 2}),
        }
        actual = {
            measure.id: (
                measure.direction,
                measure.scope,
                measure.cost,
                measure.lag_quarters,
                dict(measure.effects),
            )
            for measure in self.snapshot.measures
        }

        self.assertEqual(actual, expected)

    def test_district_catalog_matches_source_field_by_field(self) -> None:
        expected = {
            "esil": (
                "Есиль",
                0.27,
                {"T1": 45, "T2": 62, "E1": 68, "E2": 72, "S1": 48,
                 "S2": 55, "B1": 78, "B2": 60, "C1": 75, "C2": 70},
            ),
            "almaty": (
                "Алматы",
                0.24,
                {"T1": 40, "T2": 75, "E1": 50, "E2": 55, "S1": 60,
                 "S2": 65, "B1": 62, "B2": 52, "C1": 50, "C2": 60},
            ),
            "saryarka": (
                "Сарыарка",
                0.20,
                {"T1": 50, "T2": 70, "E1": 42, "E2": 40, "S1": 62,
                 "S2": 68, "B1": 58, "B2": 55, "C1": 45, "C2": 55},
            ),
            "baikonur": (
                "Байконур",
                0.13,
                {"T1": 52, "T2": 68, "E1": 55, "E2": 50, "S1": 58,
                 "S2": 60, "B1": 52, "B2": 58, "C1": 55, "C2": 58},
            ),
            "nura": (
                "Нура",
                0.16,
                {"T1": 55, "T2": 40, "E1": 45, "E2": 65, "S1": 38,
                 "S2": 35, "B1": 55, "B2": 50, "C1": 60, "C2": 50},
            ),
        }
        actual = {
            district.id: (
                district.name,
                district.population_share,
                dict(district.indicators),
            )
            for district in self.snapshot.districts
        }

        self.assertEqual(actual, expected)

    def test_snapshot_numbers_cannot_be_mutated(self) -> None:
        with self.assertRaises(TypeError):
            self.snapshot.weights["T1"] = 0.5  # type: ignore[index]
        with self.assertRaises(TypeError):
            self.snapshot.districts[0].indicators["T1"] = 0  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
