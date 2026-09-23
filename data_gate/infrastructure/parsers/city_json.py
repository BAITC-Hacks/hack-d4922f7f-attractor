"""JSON-снимок города (формат engine/v1). Неизвестные ключи остаются в raw и в модель не идут."""

from __future__ import annotations

import json
from math import isfinite
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
        result = json.loads(content.decode("utf-8-sig"), parse_constant=_reject_constant,
                            parse_float=_finite_float, object_pairs_hook=_unique_object)
        pending = [(result, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise SourceParseError("Глубина JSON больше 64")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return result
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceParseError(f"Некорректный JSON: {error}") from error


def _reject_constant(name: str) -> None:
    raise SourceParseError(f"JSON содержит {name}; NaN/Infinity не допускаются")


def _finite_float(value: str) -> float:
    result = float(value)
    if not isfinite(result):
        raise SourceParseError("Число выходит за диапазон конечных float")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceParseError(f"Повторяющийся JSON-ключ: {key}")
        result[key] = value
    return result
