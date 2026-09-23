import unittest

from data_gate.domain.errors import SourceParseError
from data_gate.infrastructure.parsers import SourceTextV1Parser
from tests.data_gate.helpers import source_bytes


class SourceTextV1ParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parsed = SourceTextV1Parser().parse(source_bytes())
        self.payload = self.parsed.payload

    def test_structure_matches_task(self) -> None:
        self.assertEqual(len(self.payload["districts"]), 5)
        self.assertEqual(len(self.payload["weights"]), 10)
        self.assertEqual(len(self.payload["measures"]), 14)
        self.assertEqual(len(self.payload["synergies"]), 3)
        self.assertEqual(self.payload["globalConflicts"], [["M1", "M3"]])
        self.assertEqual(self.payload["districtConflicts"], [["M4", "M7"], ["M5", "M13"]])

    def test_rules(self) -> None:
        p = self.payload
        self.assertEqual(
            (p["horizonQuarters"], p["budget"], p["requiredSelectionCount"],
             p["maxMeasuresPerDirection"], p["criticalThreshold"], p["criticalPenalty"]),
            (8, 100, 5, 2, 40, 1),
        )

    def test_district_ids_are_stable(self) -> None:
        self.assertEqual(
            [d["id"] for d in self.payload["districts"]],
            ["esil", "almaty", "saryarka", "baikonur", "nura"],
        )
        nura = self.payload["districts"][-1]
        self.assertEqual(nura["indicators"]["S2"], 35)
        self.assertIn("аутсайдер", nura["profile"])

    def test_unicode_minus_effect(self) -> None:
        m11 = next(m for m in self.payload["measures"] if m["id"] == "M11")
        self.assertEqual(m11["effects"], {"B2": 12, "T1": -2})
        self.assertEqual((m11["scope"], m11["direction"]), ("district", "safety"))

    def test_declared_values_go_to_observations_not_model(self) -> None:
        self.assertEqual(self.parsed.observations["declaredDistrictScores"]["nura"], 49.18)
        self.assertEqual(self.parsed.observations["declaredBaselineScore"], 52.56)
        self.assertNotIn("declaredDistrictScores", self.payload)

    def test_crlf_source(self) -> None:
        crlf = source_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        self.assertEqual(SourceTextV1Parser().parse(crlf).payload, self.payload)

    def test_broken_structure_fails_loudly(self) -> None:
        broken = source_bytes().replace("Синергии".encode(), b"XX")
        with self.assertRaises(SourceParseError):
            SourceTextV1Parser().parse(broken)
