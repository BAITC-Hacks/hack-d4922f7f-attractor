from __future__ import annotations

import json
from math import isclose
from pathlib import Path

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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SnapshotFormatError(f"Invalid snapshot {path}: {error}") from error

    _validate_snapshot(snapshot)
    return snapshot


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

    for synergy in snapshot.synergies:
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
