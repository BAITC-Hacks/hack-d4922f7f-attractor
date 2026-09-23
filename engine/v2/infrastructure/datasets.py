"""V2 obtains all city inputs through immutable published Data Gate snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from data_gate.application.service import DataGateService
from data_gate.domain.model import PassportInput, SnapshotRecord, SourceType
from engine.v2.domain.fixtures import build_demo_dataset

DEMO_DATASET_ID = "synthetic-v2-demo"


def load_demo_snapshot(gate: DataGateService, data_path: Path | None = None) -> SnapshotRecord:
    """Idempotently import/publish built-in six-district data; never reuse V1 inputs."""
    payload = build_demo_dataset() if data_path is None else json.loads(Path(data_path).read_text(encoding="utf-8"))
    payload.setdefault("provenance", {
        "sourceType": "synthetic",
        "syntheticBaseTime": "2026-01-01T00:00:00Z",
        "ingestionTimeLocation": "Data Gate import.createdAt; generated inputs are not observations",
        "assumptions": ["All values are synthetic demonstration assumptions, not official Astana statistics"],
        "missingnessPolicy": "reject-required-fields; never replace missing values with zero",
        "coverage": ["population-counts", "aggregate-roads", "school-capacity", "housing-stock", "crews", "weather", "opening-cash"],
        "notCovered": ["observed-calibration", "real-road-geometry", "crosswalk", "all-domain-source-adapters"],
    })
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    passport = PassportInput(
        dataset_id=DEMO_DATASET_ID, source_type=SourceType.SYNTHETIC,
        source_uri="repo:engine/v2/domain/fixtures.py" if data_path is None else "local:v2-demo-city",
        license_or_permission="project-generated-synthetic-demo", retrieved_at="2026-01-01T00:00:00Z",
        valid_from="2026-01-01T00:00:00Z", geography_version="synthetic-six-districts/1.0",
        units="persons; person-trips/15min; minutes; school places; housing units; crews; KZT",
        currency="KZT", price_base_period="2026-01", owner="AKIM demo generator",
        usage_restrictions="Not calibrated; not an official forecast or statistics",
    )
    record = gate.create_import(content, "v2-city-json", passport)
    return gate.publish(record.id)
