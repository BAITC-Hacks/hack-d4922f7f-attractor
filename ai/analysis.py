"""Application policy: approved evidence selection, one repair, deterministic fallback."""
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Protocol

from engine.v1.application.alternatives import portfolio_key, search_alternatives
from engine.v1.application.service import SimulationService
from engine.v1.domain.model import Selection

POLICY_VERSION = "evidence-selection/1.0.0"
LIMITATIONS = [
    "Это расчёт по синтетическому условию, не прогноз реального города.",
    "Поиск проверяет одну замену меры или района, а не глобальный оптимум.",
    "LLM выбирает и упорядочивает готовые факты; свободные числовые утверждения запрещены.",
]
ReadTool = Callable[[], dict[str, Any]]


class Analyst(Protocol):
    def select(self, facts: list[dict], tools: dict[str, ReadTool], repair: bool = False) -> dict: ...


@dataclass(frozen=True)
class Evidence:
    id: str
    metric: str
    value: float
    unit: str
    district_id: str | None
    category: str
    text: str
    portfolio_id: str | None = None

    def to_dict(self, snapshot_id: str, portfolio_id: str) -> dict:
        return {
            "id": self.id, "metric": self.metric, "value": self.value, "unit": self.unit,
            "districtId": self.district_id, "category": self.category, "text": self.text,
            "window": [0, 8], "aggregation": "end-of-horizon",
            "status": "derived", "sourceIds": [snapshot_id], "portfolioId": self.portfolio_id or portfolio_id,
        }


def analyze(service: SimulationService, selections: tuple[Selection, ...], *,
            snapshot_id: str, portfolio_id: str, analyst: Analyst | None = None,
            unavailable_reason: str = "not_configured") -> dict:
    result = service.evaluate(selections)
    if not result.valid:
        return {"mode": "rule-based", "status": "invalid_portfolio", "summary": "",
                "claims": [], "evidenceIds": [], "evidence": [], "proposals": [],
                "limitations": LIMITATIONS, "issues": [i.to_api_dict() for i in result.issues],
                "policyVersion": POLICY_VERSION}
    search = search_alternatives(service, selections)
    facts: list[Evidence] = [
        Evidence("score", "aqolScore", result.score, "score-points", None, "summary",
                 f"Astana Quality of Life Score: {result.score:.5f}."),
        Evidence("delta", "scoreDelta", result.decomposition.total.delta, "score-points", None,
                 "strengths" if result.decomposition.total.delta >= 0 else "risks",
                 f"Изменение относительно исходного города: {result.decomposition.total.delta:+.5f}."),
        Evidence("budget", "remainingBudget", result.remaining_budget, "conditional-budget-units",
                 None, "consequences", f"Остаток бюджета: {result.remaining_budget:g}."),
        Evidence("critical", "criticalCount", result.critical_count, "indicator-cells", None, "risks",
                 f"Показателей ниже критического порога: {result.critical_count}."),
    ]
    for district in service.snapshot.districts:
        delta = result.district_score_deltas[district.id]
        facts.append(Evidence(f"district:{district.id}", "districtScoreDelta", delta,
                              "score-points", district.id,
                              "strengths" if delta > 0 else "consequences",
                              f"{district.name}: изменение районной оценки {delta:+.5f}."))
        for indicator, change in result.indicator_deltas[district.id].items():
            if change < 0:
                facts.append(Evidence(f"negative:{district.id}:{indicator}", f"{indicator}.delta",
                                      change, "index-points", district.id, "risks",
                                      f"{district.name}: показатель {indicator} снижается на {abs(change):g}."))
    proposals = []
    for index, alternative in enumerate(search.results):
        evidence_id = f"alternative:{index}"
        candidate_id = sha256(json.dumps([snapshot_id, portfolio_key(alternative.selections)]).encode()).hexdigest()
        facts.append(Evidence(evidence_id, "alternativeScore", alternative.evaluation.score,
                              "score-points", None, "proposals",
                              f"Проверенная альтернатива: Score {alternative.evaluation.score:.5f}, "
                              f"бюджет {alternative.evaluation.cost:g}.", candidate_id))
        proposals.append({
            "evidenceId": evidence_id,
            "portfolioId": candidate_id,
            "selections": [{"measureId": s.measure_id, "districtId": s.district_id}
                           for s in alternative.selections],
            "evaluation": alternative.evaluation.to_api_dict(),
        })
    evidence = [fact.to_dict(snapshot_id, portfolio_id) for fact in facts]
    by_id = {fact["id"]: fact for fact in evidence}
    default = {section: [f.id for f in facts if f.category == section]
               for section in ("summary", "strengths", "risks", "consequences", "proposals")}
    selection, mode, status = default, "rule-based", unavailable_reason
    if analyst is not None:
        tools = {
            "validate_portfolio": lambda: service.validate(selections).to_api_dict(),
            "evaluate_portfolio": lambda: result.to_api_dict(),
            "search_alternatives": lambda: {"results": proposals, "searchType": "local-one-edit"},
        }
        for attempt in range(2):
            try:
                candidate = analyst.select(evidence, tools, repair=attempt == 1)
                _validate_selection(candidate, by_id, default)
                selection, mode, status = candidate, "llm", "ok"
                break
            except InvalidEvidence:
                status = "invalid_evidence"
            except Exception:
                # Never leak upstream errors containing keys, prompts or provider internals.
                status = "provider_unavailable"
                break
    # The server hydrates claims: all numbers, scope and wording come from the same evidence.
    chosen = [key for section in selection.values() for key in section]
    claims = [{**by_id[key], "evidenceIds": [key], "kind": "calculation"} for key in chosen]
    return {
        "mode": mode, "status": status, "policyVersion": POLICY_VERSION,
        "summary": " ".join(by_id[key]["text"] for key in selection["summary"]),
        "claims": claims, "evidenceIds": chosen, "evidence": evidence,
        "sections": selection, "limitations": LIMITATIONS,
        "proposals": [p for p in proposals if p["evidenceId"] in selection["proposals"]],
        "issues": [],
    }


class InvalidEvidence(ValueError):
    pass


def _validate_selection(selection: Any, facts: dict, required: dict) -> None:
    if not isinstance(selection, dict) or set(selection) != set(required):
        raise InvalidEvidence("Unknown response fields")
    for section, ids in selection.items():
        if not isinstance(ids, list) or not all(isinstance(key, str) for key in ids):
            raise InvalidEvidence("Expected evidence IDs")
        if len(set(ids)) != len(ids) or len(ids) > len(facts):
            raise InvalidEvidence("Duplicate or excessive evidence")
        if any(key not in facts or facts[key]["category"] != section for key in ids):
            raise InvalidEvidence("Unsupported evidence or changed claim meaning")
        # Do not let the model hide risk, cost or score evidence.
        if section in ("summary", "risks", "consequences") and set(ids) != set(required[section]):
            raise InvalidEvidence("Mandatory facts omitted")
        if required[section] and not ids:
            raise InvalidEvidence("Empty section")
