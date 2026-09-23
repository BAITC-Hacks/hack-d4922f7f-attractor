"""Public composition helpers for the official V1 simulation."""

from pathlib import Path
from importlib.resources import as_file, files

from engine.v1.application.service import SimulationService
from engine.v1.domain.model import Selection
from engine.v1.infrastructure.json_snapshot import load_snapshot


def create_official_service(
    snapshot_path: Path | None = None,
) -> SimulationService:
    """Convenience/reference fixture; the HTTP composition uses published Data Gate data."""
    if snapshot_path is not None:
        return SimulationService(load_snapshot(snapshot_path))
    resource = files("data").joinpath("v1", "official-v1.snapshot.json")
    with as_file(resource) as path:
        return SimulationService(load_snapshot(path))


__all__ = ["Selection", "SimulationService", "create_official_service", "load_snapshot"]
