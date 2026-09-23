"""Правила качества (docs/05 §5). Чистые функции: payload → tuple[QualityIssue].

Импорт ничего не «чинит» молча: пропуск не равен нулю, неизвестное поле не влияет
на модель, критическая ошибка блокирует публикацию.
"""

from __future__ import annotations

from math import fsum, isclose, isfinite
from typing import Any, Callable, Iterable, Mapping

from data_gate.domain.model import QualityIssue, Severity

CITY_V1 = "city-v1"
TERRITORY_GEOJSON_V1 = "territory-geojson-v1"

VALID_SCOPES = frozenset({"city", "district"})
VALID_DIRECTIONS = frozenset({"transport", "environment", "social", "safety", "services"})
DECLARED_SCORE_TOLERANCE = 0.006  # источник округляет «Итог D» до сотых

Issues = list[QualityIssue]


def check_payload(
    schema: str, payload: Mapping[str, Any], observations: Mapping[str, Any]
) -> tuple[QualityIssue, ...]:
    checker = _CHECKERS.get(schema)
    if checker is None:
        return (
            QualityIssue("unknown_schema", Severity.CRITICAL, "schema", f"Нет правил качества для схемы {schema}"),
        )
    return tuple(checker(payload, observations))


# --------------------------------------------------------------------------- city-v1


def _check_city_v1(payload: Mapping[str, Any], observations: Mapping[str, Any]) -> Issues:
    issues: Issues = []
    crit = _adder(issues, Severity.CRITICAL)

    required = {
        "id": str, "rulesVersion": str, "horizonQuarters": int, "budget": (int, float),
        "requiredSelectionCount": int, "maxMeasuresPerDirection": int,
        "criticalThreshold": (int, float), "criticalPenalty": (int, float),
        "weights": dict, "districts": list, "measures": list, "synergies": list,
        "globalConflicts": list, "districtConflicts": list,
    }
    for key, kind in required.items():
        if key not in payload or payload[key] is None:
            crit("missing_field", key, f"Обязательное поле {key} отсутствует")
        elif not _is(payload[key], kind):
            crit("invalid_type", key, f"Поле {key} имеет неверный тип")
    if issues:
        return issues  # дальше структура не гарантирована

    horizon = payload["horizonQuarters"]
    for key in ("horizonQuarters", "budget", "requiredSelectionCount", "maxMeasuresPerDirection"):
        if not payload[key] > 0:
            crit("out_of_range", key, f"{key} должен быть положительным")

    weights: Mapping[str, Any] = payload["weights"]
    indicator_codes = set(weights)
    if not all(_number(v) and v >= 0 for v in weights.values()):
        crit("invalid_weight", "weights", "Веса должны быть неотрицательными числами")
    elif not isclose(fsum(weights.values()), 1.0, abs_tol=1e-9):
        crit("weights_sum", "weights", f"Сумма весов {fsum(weights.values())} ≠ 1")

    catalog = payload.get("indicatorCatalog")
    if isinstance(catalog, list):
        codes = [item.get("code") for item in catalog if isinstance(item, dict)]
        if set(codes) != indicator_codes:
            crit("catalog_mismatch", "indicatorCatalog", "Каталог показателей не совпадает с весами")

    # районы
    districts = payload["districts"]
    _unique_ids(districts, "districts", crit)
    shares: list[float] = []
    for index, district in enumerate(districts):
        path = f"districts[{index}]"
        if not isinstance(district, dict):
            crit("invalid_type", path, "Район должен быть объектом")
            continue
        share = district.get("populationShare")
        if share is None:
            crit("missing_value", f"{path}.populationShare", "Доля населения не указана (пропуск ≠ 0)")
        elif not _number(share) or not 0 < share <= 1:
            crit("out_of_range", f"{path}.populationShare", "Доля населения вне (0, 1]")
        else:
            shares.append(share)
        values = district.get("indicators")
        if not isinstance(values, dict):
            crit("missing_field", f"{path}.indicators", "Нет показателей района")
            continue
        missing = indicator_codes - set(values)
        extra = set(values) - indicator_codes
        if missing:
            crit("missing_value", f"{path}.indicators", f"Нет значений: {', '.join(sorted(missing))}")
        if extra:
            crit("unknown_indicator", f"{path}.indicators", f"Неизвестные показатели: {', '.join(sorted(extra))}")
        for code, value in values.items():
            if value is None:
                crit("missing_value", f"{path}.indicators.{code}", "Пропуск не равен нулю")
            elif not _number(value) or not 0 <= value <= 100:
                crit("out_of_range", f"{path}.indicators.{code}", f"{value} вне шкалы 0–100")
    if len(shares) == len(districts) and districts and not isclose(fsum(shares), 1.0, abs_tol=1e-9):
        crit("population_sum", "districts", f"Сумма долей населения {fsum(shares)} ≠ 1")

    # меры
    measures = payload["measures"]
    measure_ids = _unique_ids(measures, "measures", crit)
    for index, measure in enumerate(measures):
        path = f"measures[{index}]"
        if not isinstance(measure, dict):
            crit("invalid_type", path, "Мера должна быть объектом")
            continue
        if measure.get("scope") not in VALID_SCOPES:
            crit("invalid_enum", f"{path}.scope", "scope: city или district")
        if measure.get("direction") not in VALID_DIRECTIONS:
            crit("invalid_enum", f"{path}.direction", f"Неизвестное направление {measure.get('direction')}")
        cost = measure.get("cost")
        if not _number(cost) or cost < 0:
            crit("out_of_range", f"{path}.cost", "Стоимость должна быть неотрицательным числом")
        lag = measure.get("lagQuarters")
        if not isinstance(lag, int) or isinstance(lag, bool) or not 0 <= lag <= horizon:
            crit("out_of_range", f"{path}.lagQuarters", f"Лаг вне [0, {horizon}]")
        effects = measure.get("effects")
        if not isinstance(effects, dict) or not effects:
            crit("missing_field", f"{path}.effects", "Нет эффектов меры")
            continue
        for code, value in effects.items():
            if code not in indicator_codes:
                crit("unknown_indicator", f"{path}.effects.{code}", "Эффект на неизвестный показатель")
            if not _number(value):
                crit("invalid_type", f"{path}.effects.{code}", "Эффект должен быть числом")

    # ссылочная целостность
    for index, synergy in enumerate(payload["synergies"]):
        path = f"synergies[{index}]"
        pair = synergy.get("measureIds", []) if isinstance(synergy, dict) else []
        if not isinstance(pair, list) or len(pair) != 2 or not set(pair) <= measure_ids:
            crit("broken_reference", f"{path}.measureIds", "Синергия ссылается на неизвестные меры")
        elif synergy.get("targetMeasureId") not in pair:
            crit("broken_reference", f"{path}.targetMeasureId", "Цель синергии не входит в пару")
        if isinstance(synergy, dict) and synergy.get("indicator") not in indicator_codes:
            crit("unknown_indicator", f"{path}.indicator", "Синергия на неизвестный показатель")
    for key in ("globalConflicts", "districtConflicts"):
        for index, pair in enumerate(payload[key]):
            if not isinstance(pair, list) or len(pair) != 2 or not set(pair) <= measure_ids:
                crit("broken_reference", f"{key}[{index}]", "Конфликт ссылается на неизвестные меры")

    if any(issue.severity is Severity.CRITICAL for issue in issues):
        return issues

    # сверка с контрольными значениями источника: расхождение — предупреждение, не правка
    declared = observations.get("declaredDistrictScores", {})
    for district in districts:
        expected = declared.get(district["id"])
        if expected is None:
            continue
        actual = fsum(weights[code] * district["indicators"][code] for code in weights)
        if abs(actual - expected) > DECLARED_SCORE_TOLERANCE:
            issues.append(QualityIssue(
                "declared_total_mismatch", Severity.WARNING, f"districts.{district['id']}",
                f"Итог D в источнике {expected}, по весам {actual:.5f}",
            ))
    if declared and not any(i.code == "declared_total_mismatch" for i in issues):
        issues.append(QualityIssue(
            "declared_totals_verified", Severity.INFO, "districts",
            f"Итог D всех {len(declared)} районов совпал с расчётом по весам (±{DECLARED_SCORE_TOLERANCE})",
        ))

    threshold = payload["criticalThreshold"]
    critical_cells = sorted(
        f"{district['id']}.{code}"
        for district in districts
        for code, value in district["indicators"].items()
        if value < threshold
    )
    if critical_cells:
        issues.append(QualityIssue(
            "baseline_critical_values", Severity.INFO, "districts",
            f"Исходно ниже порога {threshold}: {', '.join(critical_cells)}",
        ))
    return issues


# --------------------------------------------------------------- territory-geojson-v1

_GEOMETRY_TYPES = frozenset(
    {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
)
_WGS84_NAMES = frozenset({
    "urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84",
    "EPSG:4326", "urn:ogc:def:crs:EPSG::4326",
})


def _check_territory_geojson(payload: Mapping[str, Any], observations: Mapping[str, Any]) -> Issues:
    issues: Issues = []
    crit = _adder(issues, Severity.CRITICAL)
    warn = _adder(issues, Severity.WARNING)

    if payload.get("type") != "FeatureCollection":
        crit("invalid_type", "type", "Ожидается GeoJSON FeatureCollection")
        return issues
    crs = payload.get("crs")
    if crs is not None:
        name = (crs.get("properties") or {}).get("name") if isinstance(crs, dict) else None
        if name not in _WGS84_NAMES:
            crit("unsupported_crs", "crs", f"CRS {name} не WGS84; перепроецируйте до импорта (RFC 7946)")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        crit("missing_field", "features", "Нет объектов")
        return issues

    seen: set[str] = set()
    known_districts = set(observations.get("knownDistrictIds", ()))
    for index, feature in enumerate(features):
        path = f"features[{index}]"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            crit("invalid_type", path, "Ожидается Feature")
            continue
        feature_id = feature.get("id")
        if feature_id is None:
            crit("missing_value", f"{path}.id", "У объекта нет id — ссылочная целостность невозможна")
        elif str(feature_id) in seen:
            crit("duplicate_id", f"{path}.id", f"Повтор id {feature_id}")
        else:
            seen.add(str(feature_id))
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in _GEOMETRY_TYPES:
            crit("invalid_geometry", f"{path}.geometry", "Неподдерживаемая или пустая геометрия")
            continue
        problem = _geometry_problem(geometry["type"], geometry.get("coordinates"))
        if problem:
            crit("invalid_geometry", f"{path}.geometry", problem)
        properties = feature.get("properties") or {}
        district_id = properties.get("districtId")
        if known_districts and district_id is not None and district_id not in known_districts:
            crit("broken_reference", f"{path}.properties.districtId", f"Неизвестный район {district_id}")
        if not properties.get("layer"):
            warn("missing_layer", f"{path}.properties.layer", "Не указан слой (buildings/roads/…) — объект не попадёт в фильтры")
    return issues


def _geometry_problem(kind: str, coords: Any) -> str | None:
    def position(p: Any) -> bool:
        return (
            isinstance(p, list) and len(p) >= 2 and all(_number(v) for v in p)
            and -180 <= p[0] <= 180 and -90 <= p[1] <= 90
        )

    def ring(r: Any) -> bool:
        return isinstance(r, list) and len(r) >= 4 and all(position(p) for p in r) and r[0] == r[-1]

    def polygon(p: Any) -> bool:
        return isinstance(p, list) and len(p) >= 1 and all(ring(r) for r in p)

    def line(l: Any) -> bool:
        return isinstance(l, list) and len(l) >= 2 and all(position(p) for p in l)

    ok = {
        "Point": lambda c: position(c),
        "MultiPoint": lambda c: isinstance(c, list) and bool(c) and all(position(p) for p in c),
        "LineString": line,
        "MultiLineString": lambda c: isinstance(c, list) and bool(c) and all(line(l) for l in c),
        "Polygon": polygon,
        "MultiPolygon": lambda c: isinstance(c, list) and bool(c) and all(polygon(p) for p in c),
    }[kind](coords)
    return None if ok else f"Некорректные координаты {kind} (WGS84 lon/lat, кольца замкнуты, ≥4 точек)"


# ---------------------------------------------------------------------------- helpers

_CHECKERS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Issues]] = {
    CITY_V1: _check_city_v1,
    TERRITORY_GEOJSON_V1: _check_territory_geojson,
}


def _adder(issues: Issues, severity: Severity) -> Callable[[str, str, str], None]:
    def add(code: str, field: str, message: str) -> None:
        issues.append(QualityIssue(code, severity, field, message))

    return add


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _is(value: Any, kind: Any) -> bool:
    if kind is int or kind == (int, float):
        return _number(value) and (kind != int or isinstance(value, int))
    return isinstance(value, kind)


def _unique_ids(items: Iterable[Any], path: str, crit: Callable[[str, str, str], None]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(items):
        item_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item_id, str) or not item_id:
            crit("missing_value", f"{path}[{index}].id", "Нет id")
        elif item_id in ids:
            crit("duplicate_id", f"{path}[{index}].id", f"Повтор id {item_id}")
        else:
            ids.add(item_id)
    return ids
