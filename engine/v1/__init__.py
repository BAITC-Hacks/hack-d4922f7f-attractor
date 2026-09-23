"""Public composition helpers for the official V1 simulation."""

from pathlib import Path

from engine.v1.application.service import SimulationService
from engine.v1.domain.model import Selection
from engine.v1.infrastructure.json_snapshot import load_snapshot


def create_official_service(
    snapshot_path: Path | None = None,
) -> SimulationService:
    """Build the V1 service with the repository's official immutable snapshot."""
    path = snapshot_path or (
        Path(__file__).resolve().parents[2]
        / "data"
        / "v1"
        / "official-v1.snapshot.json"
    )
    return SimulationService(load_snapshot(path))


__all__ = ["Selection", "SimulationService", "create_official_service", "load_snapshot"]
