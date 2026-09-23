"""Public composition helpers for the official V1 simulation."""

from pathlib import Path
from importlib.resources import files
import json

from engine.v1.application.service import SimulationService
from engine.v1.domain.model import Selection
from engine.v1.infrastructure.json_snapshot import load_snapshot, snapshot_from_payload


def create_official_service(
    snapshot_path: Path | None = None,
) -> SimulationService:
    """Convenience/reference fixture; the HTTP composition uses published Data Gate data."""
    snapshot = (
        load_snapshot(snapshot_path) if snapshot_path else snapshot_from_payload(
            json.loads(files("data").joinpath("v1/official-v1.snapshot.json").read_text(encoding="utf-8"))
        )
    )
    return SimulationService(snapshot)


__all__ = ["Selection", "SimulationService", "create_official_service", "load_snapshot"]
