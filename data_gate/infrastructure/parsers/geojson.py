"""GeoJSON территории (границы районов, здания, дороги, светофоры, зелень).

Каждый объект обязан иметь id; слой берётся из properties.layer. Проверки
геометрии и CRS — в domain/quality.py.
"""

from __future__ import annotations

from data_gate.application.ports import ParsedSource
from data_gate.domain.errors import SourceParseError
from data_gate.domain.quality import TERRITORY_GEOJSON_V1
from data_gate.infrastructure.parsers.city_json import load_json


class TerritoryGeoJsonParser:
    format_id = "geojson-v1"

    def __init__(self, known_district_ids: tuple[str, ...] = ()) -> None:
        self._known_district_ids = known_district_ids

    def parse(self, content: bytes) -> ParsedSource:
        raw = load_json(content)
        if not isinstance(raw, dict):
            raise SourceParseError("Ожидается GeoJSON-объект")
        payload = {key: raw[key] for key in ("type", "crs", "features") if key in raw}
        return ParsedSource(
            schema=TERRITORY_GEOJSON_V1,
            payload=payload,
            mapped_fields=tuple(payload),
            unmapped_fields=tuple(sorted(k for k in raw if k not in payload)),
            observations={"knownDistrictIds": self._known_district_ids},
        )
