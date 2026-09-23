"""Сборка зависимостей. Единственное место, где домен встречается с инфраструктурой."""

from __future__ import annotations

import os
from pathlib import Path

from data_gate.application.ports import Clock
from data_gate.application.service import DataGateService
from data_gate.infrastructure.clock import SystemClock
from data_gate.infrastructure.filesystem import (
    FileImportRepository,
    FileRawStore,
    FileRefRepository,
    FileSnapshotRepository,
    FileStore,
)
from data_gate.infrastructure.memory import (
    MemoryImportRepository,
    MemoryRawStore,
    MemoryRefRepository,
    MemorySnapshotRepository,
)
from data_gate.infrastructure.parsers import ALL_PARSERS

STORE_ENV = "AKIM_DATA_GATE_DIR"


def default_store_dir() -> Path:
    return Path(os.environ.get(STORE_ENV) or Path.cwd() / "var" / "data-gate")


def create_file_gate(root: Path | None = None, clock: Clock | None = None) -> DataGateService:
    store = FileStore(root or default_store_dir())
    return DataGateService(
        parsers=ALL_PARSERS,
        raw=FileRawStore(store),
        imports=FileImportRepository(store),
        snapshots=FileSnapshotRepository(store),
        refs=FileRefRepository(store),
        clock=clock or SystemClock(),
    )


def create_memory_gate(clock: Clock | None = None) -> DataGateService:
    return DataGateService(
        parsers=ALL_PARSERS,
        raw=MemoryRawStore(),
        imports=MemoryImportRepository(),
        snapshots=MemorySnapshotRepository(),
        refs=MemoryRefRepository(),
        clock=clock or SystemClock(),
    )
