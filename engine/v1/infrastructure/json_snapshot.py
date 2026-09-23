from __future__ import annotations

import json
from math import isclose, isfinite
from pathlib import Path
from typing import Any, Mapping

from engine.v1.domain.model import (
    District,
    DistrictConflict,
    Measure,
    SimulationSnapshot,
    Synergy,
    immutable_numbers,
)


class SnapshotFormatError(ValueError):
    pass


def load_snapshot(path: Path) -> SimulationSnapshot:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise SnapshotFormatError(f"Invalid snapshot {path}: {error}") from error
    return snapshot_from_payload(raw)


def snapshot_from_payload(raw: Mapping[str, Any]) -> SimulationSnapshot:
    """Boundary adapter shared by file loading and published Data Gate snapshots."""
    try:
        _validate_input(raw)
        snapshot = SimulationSnapshot(
            id=raw["id"],
            rules_version=raw["rulesVersion"],
            horizon_quarters=int(raw["horizonQuarters"]),
            budget=float(raw["budget"]),
            required_selection_count=int(raw["requiredSelectionCount"]),
            max_measures_per_direction=int(raw["maxMeasuresPerDirection"]),
            critical_threshold=float(raw["criticalThreshold"]),
            critical_penalty=float(raw["criticalPenalty"]),
            weights=immutable_numbers(raw["weights"]),
            districts=tuple(
                District(
                    id=item["id"],
                    name=item["name"],
                    population_share=float(item["populationShare"]),
                    indicators=immutable_numbers(item["indicators"]),
                )
                for item in raw["districts"]
            ),
            measures=tuple(
                Measure(
                    id=item["id"],
                    direction=item["direction"],
                    scope=item["scope"],
                    cost=float(item["cost"]),
                    lag_quarters=int(item["lagQuarters"]),
                    effects=immutable_numbers(item["effects"]),
                )
                for item in raw["measures"]
            ),
            synergies=tuple(
                Synergy(
                    measure_ids=frozenset(item["measureIds"]),
                    target_measure_id=item["targetMeasureId"],
                    indicator=item["indicator"],
                    bonus=float(item["bonus"]),
                )
                for item in raw["synergies"]
            ),
            global_conflicts=tuple(
                frozenset(measure_ids) for measure_ids in raw["globalConflicts"]
            ),
            district_conflicts=tuple(
                DistrictConflict(frozenset(measure_ids))
                for measure_ids in raw["districtConflicts"]
            ),
        )
        _validate_snapshot(snapshot)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        raise SnapshotFormatError(f"Invalid snapshot: {error}") from error

    return snapshot


def _validate_input(raw: Mapping[str, Any]) -> None:
    def number(value: Any) -> None:
        if type(value) not in (int, float) or not isfinite(value):
            raise SnapshotFormatError("Expected a finite number (not bool or string)")

    for key in ("horizonQuarters", "requiredSelectionCount", "maxMeasuresPerDirection"):
        if type(raw[key]) is not int or raw[key] <= 0:
            raise SnapshotFormatError(f"{key} must be a positive integer")
    for key in ("budget", "criticalThreshold", "criticalPenalty"):
        number(raw[key])
    if raw["budget"] <= 0 or raw["criticalPenalty"] < 0 or not 0 <= raw["criticalThreshold"] <= 100:
        raise SnapshotFormatError("Invalid budget, threshold or penalty")
    for key in ("id", "rulesVersion"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise SnapshotFormatError(f"{key} must be a nonempty string")
    if not raw["weights"] or not raw["districts"] or not raw["measures"]:
        raise SnapshotFormatError("Empty snapshot collections")
    for code, value in raw["weights"].items():
        if not isinstance(code, str) or not code:
            raise SnapshotFormatError("Invalid indicator ID")
        number(value)
        if value < 0:
            raise SnapshotFormatError("Negative weight")
    for collection in ("districts", "measures"):
        for item in raw[collection]:
            if not isinstance(item["id"], str) or not item["id"]:
                raise SnapshotFormatError("Invalid entity ID")
            values = item["indicators"] if collection == "districts" else item["effects"]
            for value in values.values():
                number(value)
            if collection == "districts":
                number(item["populationShare"])
                if not 0 < item["populationShare"] <= 1:
                    raise SnapshotFormatError("Invalid population share")
            else:
                number(item["cost"])
                if type(item["lagQuarters"]) is not int:
                    raise SnapshotFormatError("Lag must be integer")
                if item["direction"] not in ("transport", "environment", "social", "safety", "services"):
                    raise SnapshotFormatError("Unknown direction")
    for item in raw["synergies"]:
        number(item["bonus"])
    pairs = [item["measureIds"] for item in raw["synergies"]]
    pairs += list(raw["globalConflicts"]) + list(raw["districtConflicts"])
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(x, str) for x in pair):
            raise SnapshotFormatError("Expected a pair of measure IDs")
        if pair[0] == pair[1]:
            raise SnapshotFormatError("Repeated ID in measure pair")


def _validate_snapshot(snapshot: SimulationSnapshot) -> None:
    if snapshot.horizon_quarters <= 0:
        raise SnapshotFormatError("horizonQuarters must be positive")
    if not isclose(sum(snapshot.weights.values()), 1.0, abs_tol=1e-12):
        raise SnapshotFormatError("indicator weights must sum to 1")
    if not isclose(
        sum(district.population_share for district in snapshot.districts),
        1.0,
        abs_tol=1e-12,
    ):
        raise SnapshotFormatError("district population shares must sum to 1")

    district_ids = [district.id for district in snapshot.districts]
    measure_ids = [measure.id for measure in snapshot.measures]
    if len(district_ids) != len(set(district_ids)):
        raise SnapshotFormatError("district IDs must be unique")
    if len(measure_ids) != len(set(measure_ids)):
        raise SnapshotFormatError("measure IDs must be unique")

    indicators = set(snapshot.weights)
    for district in snapshot.districts:
        if set(district.indicators) != indicators:
            raise SnapshotFormatError(
                f"district {district.id} must define exactly the weighted indicators"
            )
        if any(value < 0 or value > 100 for value in district.indicators.values()):
            raise SnapshotFormatError(
                f"district {district.id} indicator must be between 0 and 100"
            )

    known_measures = set(measure_ids)
    for measure in snapshot.measures:
        if measure.scope not in {"city", "district"}:
            raise SnapshotFormatError(f"measure {measure.id} has invalid scope")
        if measure.cost < 0:
            raise SnapshotFormatError(f"measure {measure.id} has negative cost")
        if not 0 <= measure.lag_quarters <= snapshot.horizon_quarters:
            raise SnapshotFormatError(f"measure {measure.id} has invalid lag")
        if not set(measure.effects) <= indicators:
            raise SnapshotFormatError(f"measure {measure.id} has unknown indicator")

    synergy_keys = set()
    for synergy in snapshot.synergies:
        key = (synergy.measure_ids, synergy.target_measure_id, synergy.indicator)
        if key in synergy_keys:
            raise SnapshotFormatError("Duplicate synergy")
        synergy_keys.add(key)
        if not synergy.measure_ids <= known_measures:
            raise SnapshotFormatError("synergy references unknown measure")
        if synergy.target_measure_id not in synergy.measure_ids:
            raise SnapshotFormatError("synergy target must belong to its measure pair")
        if synergy.indicator not in indicators:
            raise SnapshotFormatError("synergy references unknown indicator")
    for conflict in snapshot.global_conflicts:
        if not conflict <= known_measures:
            raise SnapshotFormatError("global conflict references unknown measure")
    for conflict in snapshot.district_conflicts:
        if not conflict.measure_ids <= known_measures:
            raise SnapshotFormatError("district conflict references unknown measure")
