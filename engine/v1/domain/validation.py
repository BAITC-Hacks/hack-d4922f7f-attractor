from __future__ import annotations

from collections import Counter
from math import fsum
from typing import Sequence

from engine.v1.domain.model import (
    Issue,
    Measure,
    Selection,
    SimulationSnapshot,
    ValidationResult,
)


def validate_portfolio(
    snapshot: SimulationSnapshot,
    selections: Sequence[Selection],
) -> ValidationResult:
    issues: list[Issue] = []
    measures = snapshot.measure_by_id
    districts = snapshot.district_by_id

    if len(selections) != snapshot.required_selection_count:
        issues.append(
            Issue(
                code="selection_count",
                field="selections",
                message=(
                    f"Expected exactly {snapshot.required_selection_count} selections; "
                    f"received {len(selections)}."
                ),
            )
        )

    counts = Counter(selection.measure_id for selection in selections)
    for measure_id in sorted(
        measure_id for measure_id, count in counts.items() if count > 1
    ):
        issues.append(
            Issue(
                code="duplicate_measure",
                field="selections",
                message=f"Measure {measure_id} may be selected only once.",
            )
        )

    known: list[tuple[int, Selection, Measure]] = []
    for index, selection in enumerate(selections):
        measure = measures.get(selection.measure_id)
        if measure is None:
            issues.append(
                Issue(
                    code="unknown_measure",
                    field=f"selections[{index}].measureId",
                    message=f"Unknown measure ID: {selection.measure_id}.",
                )
            )
            continue
        known.append((index, selection, measure))

        if measure.scope == "district":
            if selection.district_id is None:
                issues.append(
                    Issue(
                        code="district_required",
                        field=f"selections[{index}].districtId",
                        message=f"Measure {measure.id} requires a district.",
                    )
                )
            elif selection.district_id not in districts:
                issues.append(
                    Issue(
                        code="unknown_district",
                        field=f"selections[{index}].districtId",
                        message=f"Unknown district ID: {selection.district_id}.",
                    )
                )
        elif selection.district_id is not None:
            issues.append(
                Issue(
                    code="district_not_allowed",
                    field=f"selections[{index}].districtId",
                    message=f"City-wide measure {measure.id} must not have a district.",
                )
            )

    cost = fsum(measure.cost for _, _, measure in known)
    remaining = snapshot.budget - cost
    if cost > snapshot.budget:
        issues.append(
            Issue(
                code="budget_exceeded",
                field="selections",
                message=f"Portfolio cost {cost:g} exceeds budget {snapshot.budget:g}.",
            )
        )

    directions = Counter(measure.direction for _, _, measure in known)
    for direction in sorted(
        direction
        for direction, count in directions.items()
        if count > snapshot.max_measures_per_direction
    ):
        issues.append(
            Issue(
                code="direction_limit_exceeded",
                field="selections",
                message=(
                    f"Direction {direction} has {directions[direction]} measures; "
                    f"maximum is {snapshot.max_measures_per_direction}."
                ),
            )
        )

    selected_ids = set(counts)
    for conflict in snapshot.global_conflicts:
        if conflict <= selected_ids:
            ids = ", ".join(sorted(conflict))
            issues.append(
                Issue(
                    code="measure_conflict_global",
                    field="selections",
                    message=f"Measures {ids} cannot be combined.",
                )
            )

    selections_by_measure = {
        selection.measure_id: selection for _, selection, _ in known
    }
    for conflict in snapshot.district_conflicts:
        if not conflict.measure_ids <= selected_ids:
            continue
        selected = [
            selections_by_measure[measure_id]
            for measure_id in conflict.measure_ids
        ]
        district_ids = {selection.district_id for selection in selected}
        if len(district_ids) == 1 and None not in district_ids:
            ids = ", ".join(sorted(conflict.measure_ids))
            district_id = next(iter(district_ids))
            issues.append(
                Issue(
                    code="measure_conflict_district",
                    field="selections",
                    message=f"Measures {ids} conflict in district {district_id}.",
                )
            )

    return ValidationResult(
        valid=not issues,
        issues=tuple(issues),
        cost=cost,
        remaining_budget=remaining,
    )
