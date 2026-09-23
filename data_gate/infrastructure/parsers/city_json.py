"""JSON-снимок города (формат engine/v1). Неизвестные ключи остаются в raw и в модель не идут."""

from __future__ import annotations

import json
from typing import Any

from data_gate.application.ports import ParsedSource
from data_gate.domain.errors import SourceParseError
from data_gate.domain.quality import CITY_V1

KNOWN_KEYS = (
    "id", "rulesVersion", "horizonQuarters", "budget", "requiredSelectionCount",
    "maxMeasuresPerDirection", "criticalThreshold", "criticalPenalty", "weights",
    "indicatorCatalog", "districts", "measures", "synergies", "globalConflicts",
    "districtConflicts",
)


class CityJsonParser:
    format_id = "city-json-v1"

    def parse(self, content: bytes) -> ParsedSource:
        raw = load_json(content)
        if not isinstance(raw, dict):
            raise SourceParseError("Ожидается JSON-объект снимка города")
        payload = {key: raw[key] for key in KNOWN_KEYS if key in raw}
        return ParsedSource(
            schema=CITY_V1,
            payload=payload,
            mapped_fields=tuple(key for key in KNOWN_KEYS if key in raw),
            unmapped_fields=tuple(sorted(key for key in raw if key not in KNOWN_KEYS)),
        )


def load_json(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceParseError(f"Некорректный JSON: {error}") from error


def _reject_constant(name: str) -> None:
    raise SourceParseError(f"JSON содержит {name}; NaN/Infinity не допускаются")
