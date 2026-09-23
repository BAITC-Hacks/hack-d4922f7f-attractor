"""Bounded, deterministic one-edit search; no HTTP, LLM or persistence dependencies."""
from dataclasses import dataclass
from typing import Sequence

from engine.v1.application.service import SimulationService
from engine.v1.domain.model import EvaluationResult, Selection


def portfolio_key(selections: Sequence[Selection]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((s.measure_id, s.district_id or "") for s in selections))


@dataclass(frozen=True)
class Alternative:
    selections: tuple[Selection, ...]
    evaluation: EvaluationResult
    replacements: int


@dataclass(frozen=True)
class SearchResult:
    results: tuple[Alternative, ...]
    evaluated: int
    valid_candidates: int


def search_alternatives(
    service: SimulationService, selections: Sequence[Selection], *,
    fixed: Sequence[Selection] = (), allowed_districts: Sequence[str] | None = None,
    limit: int = 3,
) -> SearchResult:
    """Enumerate the complete one-replacement/relocation neighborhood, better results only."""
    if not 1 <= limit <= 20:
        raise ValueError("resultLimit must be between 1 and 20")
    baseline = service.evaluate(selections)
    if not baseline.valid:
        raise ValueError("A valid portfolio is required for alternatives")
    selected = set(selections)
    if len(set(fixed)) != len(fixed) or not set(fixed) <= selected:
        raise ValueError("fixedSelections must be a unique subset of selections")
    districts = set(service.snapshot.district_by_id) if allowed_districts is None else set(allowed_districts)
    if not districts <= set(service.snapshot.district_by_id):
        raise ValueError("Unknown allowed district")
    candidates = [
        Selection(m.id, district)
        for m in service.snapshot.measures
        for district in (sorted(districts) if m.scope == "district" else [None])
    ]
    seen = {portfolio_key(selections)}
    results = []
    evaluated = valid_candidates = 0
    for index, old in enumerate(selections):
        if old in fixed:
            continue
        for replacement in candidates:
            if any(s.district_id is not None and s.district_id not in districts
                   for i, s in enumerate(selections) if i != index):
                continue
            candidate = tuple(selections[:index]) + (replacement,) + tuple(selections[index + 1:])
            key = portfolio_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            evaluated += 1
            result = service.evaluate(candidate)
            if not result.valid:
                continue
            valid_candidates += 1
            if result.score > baseline.score:
                canonical = tuple(Selection(m, d or None) for m, d in key)
                results.append(Alternative(canonical, result, 1))
    results.sort(key=lambda r: (-r.evaluation.score, r.evaluation.cost, r.replacements,
                                portfolio_key(r.selections)))
    return SearchResult(tuple(results[:limit]), evaluated, valid_candidates)
