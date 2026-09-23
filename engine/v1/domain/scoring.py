from __future__ import annotations

from math import fsum
from types import MappingProxyType
from typing import Sequence

from engine.v1.domain.model import ScoreState, Selection, SimulationSnapshot


def calculate_score(
    snapshot: SimulationSnapshot,
    selections: Sequence[Selection],
) -> ScoreState:
    """Calculate any subset without official portfolio validation.

    The application layer validates official evaluations. Keeping this pure calculator
    independent permits baseline diagnostics and future exact marginal/Shapley analysis.
    """
    measures = snapshot.measure_by_id
    selected = {selection.measure_id: selection for selection in selections}
    effects: dict[str, dict[str, list[float]]] = {
        district.id: {indicator: [] for indicator in snapshot.weights}
        for district in snapshot.districts
    }

    for selection in selections:
        measure = measures[selection.measure_id]
        factor = (
            snapshot.horizon_quarters - measure.lag_quarters
        ) / snapshot.horizon_quarters
        target_ids = (
            tuple(effects)
            if measure.scope == "city"
            else (selection.district_id,)
        )
        for district_id in target_ids:
            if district_id is None:
                raise ValueError(f"Measure {measure.id} requires a district")
            for indicator, effect in measure.effects.items():
                effects[district_id][indicator].append(effect * factor)

    for synergy in snapshot.synergies:
        if not synergy.measure_ids <= selected.keys():
            continue
        target = selected[synergy.target_measure_id]
        target_measure = measures[synergy.target_measure_id]
        target_ids = (
            tuple(effects)
            if target_measure.scope == "city"
            else (target.district_id,)
        )
        for district_id in target_ids:
            if district_id is None:
                raise ValueError(
                    f"Synergy target {synergy.target_measure_id} requires a district"
                )
            effects[district_id][synergy.indicator].append(synergy.bonus)

    indicators: dict[str, MappingProxyType[str, float]] = {}
    district_scores: dict[str, float] = {}
    critical_count = 0
    for district in snapshot.districts:
        values: dict[str, float] = {}
        for indicator in snapshot.weights:
            value = district.indicators[indicator] + fsum(
                effects[district.id][indicator]
            )
            value = min(100.0, max(0.0, value))
            values[indicator] = value
            if value < snapshot.critical_threshold:
                critical_count += 1
        indicators[district.id] = MappingProxyType(values)
        district_scores[district.id] = fsum(
            snapshot.weights[indicator] * values[indicator]
            for indicator in snapshot.weights
        )

    average = fsum(
        district.population_share * district_scores[district.id]
        for district in snapshot.districts
    )
    minimum = min(district_scores.values())
    score = (
        0.7 * average
        + 0.3 * minimum
        - snapshot.critical_penalty * critical_count
    )
    return ScoreState(
        score=score,
        district_scores=MappingProxyType(district_scores),
        indicators=MappingProxyType(indicators),
        average=average,
        minimum=minimum,
        critical_count=critical_count,
    )
