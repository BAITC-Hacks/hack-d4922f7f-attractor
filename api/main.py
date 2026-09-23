from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from engine.v1 import Selection, SimulationService, create_official_service
from api.v2 import router as v2_router


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "apps" / "web" / "public" / "mock-api" / "catalog.json"
DISTRICT_ALIASES = {"baykonur": "baikonur"}
DISTRICT_FRONTEND_IDS = {value: key for key, value in DISTRICT_ALIASES.items()}


class SelectionInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    measure_id: str = Field(alias="measureId")
    district_id: str | None = Field(default=None, alias="districtId")


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    selections: list[SelectionInput]
    # The current frontend sends versions. The colleague's selections-only payload
    # remains accepted because the engine has one active official snapshot.
    versions: dict[str, str] | None = None


def _service() -> SimulationService:
    return create_official_service()


def _canonical_district(district_id: str | None) -> str | None:
    return DISTRICT_ALIASES.get(district_id, district_id)


def _frontend_district(district_id: str) -> str:
    return DISTRICT_FRONTEND_IDS.get(district_id, district_id)


def _selections(payload: SelectionRequest) -> tuple[Selection, ...]:
    return tuple(
        Selection(item.measure_id, _canonical_district(item.district_id))
        for item in payload.selections
    )


def _catalog(service: SimulationService) -> dict[str, Any]:
    # The mock catalog is the existing human-readable API fixture; the engine
    # snapshot remains authoritative for all calculation and rule behavior.
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    snapshot = service.snapshot
    catalog["versions"] = {
        "catalogVersion": snapshot.id,
        "dataSnapshotId": catalog["versions"]["dataSnapshotId"],
        "modelVersion": snapshot.id,
        "rulesVersion": snapshot.rules_version,
    }
    catalog["districts"] = [
        {
            "id": _frontend_district(district.id),
            "name": district.name,
            "populationShare": district.population_share,
            "indicators": dict(district.indicators),
        }
        for district in snapshot.districts
    ]
    catalog["measures"] = [
        {
            "id": measure.id,
            "name": next(row["name"] for row in catalog["measures"] if row["id"] == measure.id),
            "direction": "ecology" if measure.direction == "environment" else measure.direction,
            "scope": measure.scope,
            "cost": measure.cost,
            "lagQuarters": measure.lag_quarters,
            "effects": [
                {"indicatorId": indicator_id, "points": points}
                for indicator_id, points in measure.effects.items()
            ],
        }
        for measure in snapshot.measures
    ]
    catalog["rules"] = {
        "budget": snapshot.budget,
        "requiredSelectionCount": snapshot.required_selection_count,
        "maxMeasuresPerDirection": snapshot.max_measures_per_direction,
        "horizonQuarters": snapshot.horizon_quarters,
        "criticalThresholdExclusive": snapshot.critical_threshold,
        "incompatibleMeasurePairs": [
            {"measureIds": sorted(pair), "scope": "global"}
            for pair in snapshot.global_conflicts
        ]
        + [
            {"measureIds": sorted(pair.measure_ids), "scope": "same-district"}
            for pair in snapshot.district_conflicts
        ],
        "synergies": [
            {
                "measureIds": sorted(synergy.measure_ids),
                "districtSourceMeasureId": synergy.target_measure_id,
                "indicatorId": synergy.indicator,
                "points": synergy.bonus,
            }
            for synergy in snapshot.synergies
        ],
    }
    return catalog


def _evaluation(service: SimulationService, selections: tuple[Selection, ...]) -> dict[str, Any]:
    result = service.evaluate(selections)
    output = result.to_api_dict()
    if not result.valid:
        output["districtScores"] = []
        output["indicators"] = []
        return output

    before = service.inspect_baseline()
    threshold = service.snapshot.critical_threshold
    output["districtScores"] = [
        {
            "districtId": _frontend_district(district_id),
            "score": score,
            "beforeScore": before.district_scores[district_id],
            "delta": result.district_score_deltas[district_id],
            "criticalCount": sum(value < threshold for value in result.indicators[district_id].values()),
        }
        for district_id, score in result.district_scores.items()
    ]
    output["indicators"] = [
        {
            "districtId": _frontend_district(district_id),
            "before": dict(before.indicators[district_id]),
            "after": dict(values),
            "delta": dict(result.indicator_deltas[district_id]),
        }
        for district_id, values in result.indicators.items()
    ]
    decomposition = result.decomposition
    assert decomposition is not None
    output["decomposition"] = {
        "before": {
            "average": before.average,
            "minimum": before.minimum,
            "criticalPenalty": -service.snapshot.critical_penalty * before.critical_count,
            "score": before.score,
        },
        "after": {
            "average": result.average,
            "minimum": result.minimum,
            "criticalPenalty": -service.snapshot.critical_penalty * (result.critical_count or 0),
            "score": result.score,
        },
        "delta": {
            "averageContribution": decomposition.average_contribution.delta,
            "minimumContribution": decomposition.minimum_contribution.delta,
            "criticalPenaltyContribution": decomposition.critical_penalty.delta,
            "score": decomposition.total.delta,
        },
    }
    return output


app = FastAPI(title="AKIM V1 Simulation API", version="1.0.0")
app.include_router(v2_router)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"]
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return _catalog(_service())


@app.post("/v1/validate")
def validate(payload: SelectionRequest) -> dict[str, Any]:
    return _service().validate(_selections(payload)).to_api_dict()


@app.post("/v1/evaluate")
def evaluate(payload: SelectionRequest) -> dict[str, Any]:
    service = _service()
    return _evaluation(service, _selections(payload))
