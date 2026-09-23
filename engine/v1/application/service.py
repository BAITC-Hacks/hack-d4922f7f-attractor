from __future__ import annotations

from types import MappingProxyType
from typing import Sequence

from engine.v1.domain.model import (
    EvaluationResult,
    ScoreDecomposition,
    ScoreState,
    Selection,
    SimulationSnapshot,
    ValidationResult,
    ValueChange,
)
from engine.v1.domain.scoring import calculate_score
from engine.v1.domain.validation import validate_portfolio


class SimulationService:
    """Application boundary used by the future HTTP API and AI tools."""

    def __init__(self, snapshot: SimulationSnapshot) -> None:
        self._snapshot = snapshot
        self._baseline = calculate_score(snapshot, ())

    @property
    def snapshot(self) -> SimulationSnapshot:
        return self._snapshot

    def validate(self, selections: Sequence[Selection]) -> ValidationResult:
        return validate_portfolio(self._snapshot, selections)

    def evaluate(self, selections: Sequence[Selection]) -> EvaluationResult:
        validation = self.validate(selections)
        if not validation.valid:
            return EvaluationResult(
                valid=False,
                issues=validation.issues,
                cost=validation.cost,
                remaining_budget=validation.remaining_budget,
                score=None,
                district_scores=MappingProxyType({}),
                district_score_deltas=MappingProxyType({}),
                indicators=MappingProxyType({}),
                indicator_deltas=MappingProxyType({}),
                average=None,
                minimum=None,
                critical_count=None,
                decomposition=None,
            )

        state = calculate_score(self._snapshot, selections)
        baseline = self._baseline
        district_score_deltas = MappingProxyType(
            {
                district_id: score - baseline.district_scores[district_id]
                for district_id, score in state.district_scores.items()
            }
        )
        indicator_deltas = MappingProxyType(
            {
                district_id: MappingProxyType(
                    {
                        indicator: value
                        - baseline.indicators[district_id][indicator]
                        for indicator, value in values.items()
                    }
                )
                for district_id, values in state.indicators.items()
            }
        )
        decomposition = ScoreDecomposition(
            average_contribution=ValueChange(
                0.7 * baseline.average, 0.7 * state.average
            ),
            minimum_contribution=ValueChange(
                0.3 * baseline.minimum, 0.3 * state.minimum
            ),
            critical_penalty=ValueChange(
                -self._snapshot.critical_penalty * baseline.critical_count,
                -self._snapshot.critical_penalty * state.critical_count,
            ),
            total=ValueChange(baseline.score, state.score),
        )
        return EvaluationResult(
            valid=True,
            issues=(),
            cost=validation.cost,
            remaining_budget=validation.remaining_budget,
            score=state.score,
            district_scores=state.district_scores,
            district_score_deltas=district_score_deltas,
            indicators=state.indicators,
            indicator_deltas=indicator_deltas,
            average=state.average,
            minimum=state.minimum,
            critical_count=state.critical_count,
            decomposition=decomposition,
        )

    def inspect_baseline(self) -> ScoreState:
        """Return the diagnostic zero-action state; it is not an official portfolio."""
        return self._baseline
