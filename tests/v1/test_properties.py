import json
import unittest
from dataclasses import replace
from pathlib import Path

from engine.v1 import create_official_service
from engine.v1.application.service import SimulationService
from engine.v1.domain.model import District, Selection, immutable_numbers
from engine.v1.domain.scoring import calculate_score


CONTROL_SELECTIONS = (
    Selection("M7", "nura"),
    Selection("M8", "nura"),
    Selection("M10", "nura"),
    Selection("M12"),
    Selection("M5", "saryarka"),
)


class CalculationPropertyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = create_official_service()

    def test_selection_order_does_not_change_result(self) -> None:
        expected = self.service.evaluate(CONTROL_SELECTIONS).to_api_dict()

        actual = self.service.evaluate(
            tuple(reversed(CONTROL_SELECTIONS))
        ).to_api_dict()

        self.assertEqual(actual, expected)

    def test_evaluation_does_not_mutate_snapshot(self) -> None:
        before = [
            (district.id, dict(district.indicators))
            for district in self.service.snapshot.districts
        ]

        self.service.evaluate(CONTROL_SELECTIONS)

        after = [
            (district.id, dict(district.indicators))
            for district in self.service.snapshot.districts
        ]
        self.assertEqual(after, before)

    def test_city_measure_has_equal_effect_in_every_district(self) -> None:
        baseline = calculate_score(self.service.snapshot, ())
        with_measure = calculate_score(self.service.snapshot, (Selection("M12"),))

        deltas = {
            district.id: with_measure.indicators[district.id]["C2"]
            - baseline.indicators[district.id]["C2"]
            for district in self.service.snapshot.districts
        }
        self.assertEqual(set(deltas.values()), {4.375})

    def test_threshold_is_strictly_below_40(self) -> None:
        districts = []
        for district in self.service.snapshot.districts:
            if district.id != "nura":
                districts.append(district)
                continue
            values = dict(district.indicators)
            values["S1"] = 40
            values["S2"] = 40
            districts.append(replace(district, indicators=immutable_numbers(values)))
        snapshot = replace(self.service.snapshot, districts=tuple(districts))

        self.assertEqual(calculate_score(snapshot, ()).critical_count, 0)

    def test_clip_happens_after_effects_are_summed(self) -> None:
        districts: list[District] = []
        for district in self.service.snapshot.districts:
            if district.id != "almaty":
                districts.append(district)
                continue
            values = dict(district.indicators)
            values["T1"] = 97
            districts.append(replace(district, indicators=immutable_numbers(values)))
        snapshot = replace(self.service.snapshot, districts=tuple(districts))

        state = calculate_score(
            snapshot,
            (Selection("M1", "almaty"), Selection("M11", "almaty")),
        )

        self.assertEqual(state.indicators["almaty"]["T1"], 99.75)

    def test_all_synergies_are_applied_to_the_target_district(self) -> None:
        cases = (
            (
                (Selection("M1", "esil"), Selection("M2")),
                "esil",
                "T1",
                54.5,
            ),
            (
                (Selection("M10", "nura"), Selection("M12")),
                "nura",
                "B1",
                67.5,
            ),
            (
                (Selection("M5", "saryarka"), Selection("M6")),
                "saryarka",
                "E2",
                52.25,
            ),
        )
        for selections, district_id, indicator, expected in cases:
            with self.subTest(selections=selections):
                state = calculate_score(self.service.snapshot, selections)
                self.assertEqual(
                    state.indicators[district_id][indicator], expected
                )

    def test_synergy_is_applied_only_once(self) -> None:
        state = calculate_score(
            self.service.snapshot,
            (Selection("M10", "nura"), Selection("M12"), Selection("M12")),
        )

        self.assertEqual(state.indicators["nura"]["B1"], 67.5)

    def test_documented_special_cases(self) -> None:
        m11 = calculate_score(
            self.service.snapshot, (Selection("M11", "almaty"),)
        )
        m9 = calculate_score(self.service.snapshot, (Selection("M9", "nura"),))
        m7 = calculate_score(self.service.snapshot, (Selection("M7", "nura"),))
        m8 = calculate_score(self.service.snapshot, (Selection("M8", "nura"),))

        self.assertEqual(m11.indicators["almaty"]["T1"], 38.25)
        self.assertEqual(m9.indicators["nura"]["S1"], 40.625)
        self.assertEqual(m9.indicators["nura"]["S2"], 37.625)
        self.assertEqual(m7.indicators["nura"]["S1"], 48)
        self.assertEqual(m8.indicators["nura"]["S2"], 43.75)

    def test_contract_files_are_valid_json(self) -> None:
        contract_dir = Path(__file__).resolve().parents[2] / "packages" / "contracts"

        for path in contract_dir.glob("*.json"):
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)


if __name__ == "__main__":
    unittest.main()
