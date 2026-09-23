"""Quality gates for the synthetic composite city and time-series observations.

These schemas deliberately do not claim support for every future V2 source domain.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from data_gate.domain.model import QualityIssue, Severity

V2_CITY = "v2-city-v1"
OBSERVATIONS = "observations-v1"


def _number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    except OverflowError:
        return False


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def check_v2_city(payload: Mapping[str, Any], observations: Mapping[str, Any]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    def reject(code: str, path: str, message: str) -> None:
        issues.append(QualityIssue(code, Severity.CRITICAL, path, message))

    for key, expected in (("schemaVersion", "v2-city/1.0"), ("mode", "dynamic-v2"),
                          ("status", "synthetic"), ("currency", "KZT")):
        if payload.get(key) != expected:
            reject("invalid_value", key, f"Demo schema requires {key}={expected}")
    if not _time(payload.get("startSimTime")):
        reject("invalid_time", "startSimTime", "Expected ISO-8601 timestamp with timezone")
    if not isinstance(payload.get("basePeriod"), str) or not payload["basePeriod"].strip():
        reject("missing_value", "basePeriod", "Price base period is required")
    districts = payload.get("districts")
    if not isinstance(districts, list) or not 1 <= len(districts) <= 100:
        reject("invalid_districts", "districts", "Expected 1–100 districts, without a V1 district whitelist")
        districts = []
    seen: set[str] = set()
    for index, district in enumerate(districts):
        path = f"districts[{index}]"
        if not isinstance(district, dict):
            reject("invalid_type", path, "District must be an object")
            continue
        district_id = district.get("id")
        if not isinstance(district_id, str) or not district_id.strip() or district_id in seen:
            reject("invalid_id", f"{path}.id", "District IDs must be nonempty and unique")
        else:
            seen.add(district_id)
        if not isinstance(district.get("name"), str) or not district["name"].strip():
            reject("missing_value", f"{path}.name", "District name is required")
        for key in ("population", "roadCapacity", "schoolCapacity", "housingUnits", "housingPrice", "crews"):
            value = district.get(key)
            if not _number(value) or value < 0:
                reject("out_of_range", f"{path}.{key}", "Expected finite nonnegative number; missing is not zero")
            elif key in {"population", "schoolCapacity", "housingUnits", "crews"} and value != int(value):
                reject("invalid_type", f"{path}.{key}", "Expected integer count")
        if not _number(district.get("travelMinutes")) or district["travelMinutes"] <= 0:
            reject("out_of_range", f"{path}.travelMinutes", "Travel duration must be positive")
    for section, keys in (("finance", ("cash", "requiredReserve")),
                          ("weather", ("snowStartMinute", "snowEndMinute", "intensity"))):
        values = payload.get(section)
        if not isinstance(values, dict):
            reject("missing_field", section, "Required object is missing")
            continue
        for key in keys:
            if not _number(values.get(key)) or values[key] < 0:
                reject("out_of_range", f"{section}.{key}", "Expected finite nonnegative number")
        if all(_number(values.get(key)) for key in keys):
            if section == "weather" and (values["snowEndMinute"] < values["snowStartMinute"]
                                         or values["intensity"] > 1):
                reject("invalid_weather", section, "Snow interval must be ordered; intensity belongs to [0,1]")
            if section == "finance" and values["requiredReserve"] > values["cash"]:
                reject("invalid_reserve", section, "Required reserve exceeds opening cash")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict) or any(not _number(value) for value in parameters.values()):
        reject("invalid_parameters", "parameters", "Parameters must be finite numeric overrides")
    return issues


def check_observations(payload: Mapping[str, Any], observations: Mapping[str, Any]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return [QualityIssue("missing_field", Severity.CRITICAL, "records", "Expected nonempty records")]
    ids: set[str] = set()
    for index, record in enumerate(records):
        path = f"records[{index}]"

        def reject(code: str, field: str, message: str) -> None:
            issues.append(QualityIssue(code, Severity.CRITICAL, f"{path}.{field}", message))

        if not isinstance(record, dict):
            reject("invalid_type", "", "Record must be an object")
            continue
        for key in ("id", "districtId", "metric", "unit"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                reject("missing_value", key, "Required nonempty string")
        record_id = record.get("id")
        if isinstance(record_id, str):
            if record_id in ids:
                reject("duplicate_id", "id", "Duplicate observation ID")
            ids.add(record_id)
        for key, options in (("measureKind", {"stock", "flow", "rate"}),
                             ("statistic", {"total", "mean", "median", "p90", "proportion"}),
                             ("sourceType", {"observed", "estimated", "synthetic"})):
            if not isinstance(record.get(key), str) or record[key] not in options:
                reject("invalid_semantics", key, f"Expected one of {sorted(options)}")
        if record.get("value") is not None and not _number(record["value"]):
            reject("invalid_value", "value", "Value must be finite number or explicit null")
        if "value" not in record:
            reject("missing_field", "value", "Missing values must be explicit null")
        times = {key: _time(record.get(key)) for key in ("eventTime", "observedAt", "ingestedAt")}
        for key, value in times.items():
            if value is None:
                reject("invalid_time", key, "Expected ISO-8601 timestamp with timezone")
        if all(times.values()) and times["ingestedAt"] < times["observedAt"]:
            reject("invalid_time_order", "ingestedAt", "Ingestion cannot precede observation")
        if record.get("measureKind") == "flow":
            period_start, period_end = _time(record.get("periodStart")), _time(record.get("periodEnd"))
            if not period_start or not period_end or period_end <= period_start:
                reject("missing_flow_period", "periodStart", "Flows require an explicit positive period")
        if record.get("sourceType") == "estimated":
            imputation = record.get("imputation")
            if (not isinstance(imputation, dict) or imputation.get("field") != "value"
                    or not isinstance(imputation.get("method"), str) or not imputation["method"]
                    or not isinstance(imputation.get("parameters"), dict)):
                reject("missing_imputation", "imputation", "Estimated value requires field, method and parameters")
    return issues


def observations_available_at(payload: Mapping[str, Any], cutoff: str) -> list[dict[str, Any]]:
    """Point-in-time query: late observations cannot leak into earlier experiments."""
    at = _time(cutoff)
    if at is None:
        raise ValueError("cutoff must be an ISO timestamp with timezone")
    return [dict(row) for row in payload.get("records", [])
            if _time(row.get("observedAt")) is not None and _time(row.get("ingestedAt")) is not None
            and _time(row["observedAt"]) <= at and _time(row["ingestedAt"]) <= at]
