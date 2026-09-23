import copy
import unittest

from data_gate.domain.model import Severity
from data_gate.domain.quality import CITY_V1, TERRITORY_GEOJSON_V1, check_payload
from tests.data_gate.helpers import official_payload


def codes(issues, severity=Severity.CRITICAL):
    return {i.code for i in issues if i.severity is severity}


class CityQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = official_payload()

    def check(self, payload, observations=None):
        return check_payload(CITY_V1, payload, observations or {})

    def test_official_payload_is_clean(self) -> None:
        issues = self.check(self.payload)
        self.assertFalse(codes(issues))
        self.assertFalse(codes(issues, Severity.WARNING))

    def test_weights_must_sum_to_one(self) -> None:
        self.payload["weights"]["T1"] = 0.2
        self.assertIn("weights_sum", codes(self.check(self.payload)))

    def test_population_must_sum_to_one(self) -> None:
        self.payload["districts"][0]["populationShare"] = 0.5
        self.assertIn("population_sum", codes(self.check(self.payload)))

    def test_missing_value_is_not_zero(self) -> None:
        self.payload["districts"][0]["indicators"]["T1"] = None
        self.assertIn("missing_value", codes(self.check(self.payload)))

    def test_out_of_scale(self) -> None:
        self.payload["districts"][1]["indicators"]["E1"] = 140
        self.assertIn("out_of_range", codes(self.check(self.payload)))

    def test_broken_references(self) -> None:
        self.payload["synergies"][0]["measureIds"] = ["M1", "M99"]
        self.payload["districtConflicts"].append(["M4", "M77"])
        self.payload["measures"][0]["effects"]["X9"] = 1
        found = codes(self.check(self.payload))
        self.assertTrue({"broken_reference", "unknown_indicator"} <= found)

    def test_duplicate_ids(self) -> None:
        self.payload["measures"].append(copy.deepcopy(self.payload["measures"][0]))
        self.assertIn("duplicate_id", codes(self.check(self.payload)))

    def test_lag_beyond_horizon(self) -> None:
        self.payload["measures"][0]["lagQuarters"] = 9
        self.assertIn("out_of_range", codes(self.check(self.payload)))

    def test_declared_total_mismatch_is_warning(self) -> None:
        issues = self.check(self.payload, {"declaredDistrictScores": {"esil": 70.0}})
        self.assertIn("declared_total_mismatch", codes(issues, Severity.WARNING))
        self.assertFalse(codes(issues))

    def test_missing_required_field(self) -> None:
        del self.payload["budget"]
        self.assertIn("missing_field", codes(self.check(self.payload)))


def square(x=71.4, y=51.1, d=0.01):
    return [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]


def feature(fid, geometry, **props):
    return {"type": "Feature", "id": fid, "geometry": geometry, "properties": {"layer": "districts", **props}}


class GeoJsonQualityTest(unittest.TestCase):
    def check(self, payload, known=()):
        return check_payload(TERRITORY_GEOJSON_V1, payload, {"knownDistrictIds": known})

    def test_valid_collection(self) -> None:
        payload = {"type": "FeatureCollection", "features": [
            feature("esil", {"type": "Polygon", "coordinates": square()}, districtId="esil"),
            feature("tl-1", {"type": "Point", "coordinates": [71.43, 51.12]}),
        ]}
        self.assertFalse(codes(self.check(payload, ("esil",))))

    def test_open_ring_and_bad_coordinates(self) -> None:
        ring = square()[0][:-1]
        payload = {"type": "FeatureCollection", "features": [
            feature("a", {"type": "Polygon", "coordinates": [ring]}),
            feature("b", {"type": "Point", "coordinates": [500, 51]}),
        ]}
        self.assertIn("invalid_geometry", codes(self.check(payload)))

    def test_non_wgs84_crs_rejected(self) -> None:
        payload = {"type": "FeatureCollection",
                   "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                   "features": [feature("a", {"type": "Point", "coordinates": [71.4, 51.1]})]}
        self.assertIn("unsupported_crs", codes(self.check(payload)))

    def test_ids_and_district_references(self) -> None:
        payload = {"type": "FeatureCollection", "features": [
            feature("a", {"type": "Point", "coordinates": [71.4, 51.1]}, districtId="mars"),
            feature("a", {"type": "Point", "coordinates": [71.4, 51.1]}),
        ]}
        found = codes(self.check(payload, ("esil",)))
        self.assertTrue({"duplicate_id", "broken_reference"} <= found)

    def test_missing_layer_is_warning(self) -> None:
        f = feature("a", {"type": "Point", "coordinates": [71.4, 51.1]})
        f["properties"] = {}
        issues = self.check({"type": "FeatureCollection", "features": [f]})
        self.assertIn("missing_layer", codes(issues, Severity.WARNING))
