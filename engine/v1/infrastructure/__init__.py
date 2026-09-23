"""Adapters that provide V1 domain inputs."""

from engine.v1.infrastructure.json_snapshot import SnapshotFormatError, load_snapshot

__all__ = ["SnapshotFormatError", "load_snapshot"]
