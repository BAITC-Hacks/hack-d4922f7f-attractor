from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


NumberMap = Mapping[str, float]


def immutable_numbers(values: Mapping[str, float]) -> NumberMap:
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class District:
    id: str
    name: str
    population_share: float
    indicators: NumberMap


@dataclass(frozen=True, slots=True)
class Measure:
    id: str
    direction: str
    scope: str
    cost: float
    lag_quarters: int
    effects: NumberMap


@dataclass(frozen=True, slots=True)
class Synergy:
    measure_ids: frozenset[str]
    target_measure_id: str
    indicator: str
    bonus: float


@dataclass(frozen=True, slots=True)
class DistrictConflict:
    measure_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    id: str
    rules_version: str
    horizon_quarters: int
    budget: float
    required_selection_count: int
    max_measures_per_direction: int
    critical_threshold: float
    critical_penalty: float
    weights: NumberMap
    districts: tuple[District, ...]
    measures: tuple[Measure, ...]
    synergies: tuple[Synergy, ...]
    global_conflicts: tuple[frozenset[str], ...]
    district_conflicts: tuple[DistrictConflict, ...]

    @property
    def district_by_id(self) -> dict[str, District]:
        return {district.id: district for district in self.districts}

    @property
    def measure_by_id(self) -> dict[str, Measure]:
        return {measure.id: measure for measure in self.measures}


@dataclass(frozen=True, slots=True)
class Selection:
    measure_id: str
    district_id: str | None = None


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    field: str
    message: str

    def to_api_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    issues: tuple[Issue, ...]
    cost: float
    remaining_budget: float

    def to_api_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": [issue.to_api_dict() for issue in self.issues],
            "cost": self.cost,
            "remainingBudget": self.remaining_budget,
        }


@dataclass(frozen=True, slots=True)
class ScoreState:
    score: float
    district_scores: Mapping[str, float]
    indicators: Mapping[str, Mapping[str, float]]
    average: float
    minimum: float
    critical_count: int


@dataclass(frozen=True, slots=True)
class ValueChange:
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    def to_api_dict(self) -> dict[str, float]:
        return {"before": self.before, "after": self.after, "delta": self.delta}


@dataclass(frozen=True, slots=True)
class ScoreDecomposition:
    average_contribution: ValueChange
    minimum_contribution: ValueChange
    critical_penalty: ValueChange
    total: ValueChange

    def to_api_dict(self) -> dict[str, object]:
        return {
            "averageContribution": self.average_contribution.to_api_dict(),
            "minimumContribution": self.minimum_contribution.to_api_dict(),
            "criticalPenalty": self.critical_penalty.to_api_dict(),
            "total": self.total.to_api_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    valid: bool
    issues: tuple[Issue, ...]
    cost: float
    remaining_budget: float
    score: float | None
    district_scores: Mapping[str, float]
    district_score_deltas: Mapping[str, float]
    indicators: Mapping[str, Mapping[str, float]]
    indicator_deltas: Mapping[str, Mapping[str, float]]
    average: float | None
    minimum: float | None
    critical_count: int | None
    decomposition: ScoreDecomposition | None

    def to_api_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": [issue.to_api_dict() for issue in self.issues],
            "cost": self.cost,
            "remainingBudget": self.remaining_budget,
            "score": self.score,
            "districtScores": dict(self.district_scores),
            "districtScoreDeltas": dict(self.district_score_deltas),
            "indicators": {
                district_id: dict(values)
                for district_id, values in self.indicators.items()
            },
            "indicatorDeltas": {
                district_id: dict(values)
                for district_id, values in self.indicator_deltas.items()
            },
            "average": self.average,
            "minimum": self.minimum,
            "criticalCount": self.critical_count,
            "decomposition": (
                self.decomposition.to_api_dict() if self.decomposition else None
            ),
        }
