"""In-memory хранилища: тесты и demo-профиль без диска."""

from __future__ import annotations

from copy import deepcopy

from data_gate.domain.canonical import canonical_json
from data_gate.domain.errors import ImmutabilityViolation
from data_gate.domain.model import DatasetRef, ImportRecord, SnapshotRecord
from data_gate.infrastructure.serialization import snapshot_to_doc


class MemoryRawStore:
    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def put(self, checksum: str, content: bytes) -> None:
        self._items.setdefault(checksum, content)

    def get(self, checksum: str) -> bytes:
        return self._items[checksum]


class MemoryImportRepository:
    def __init__(self) -> None:
        self._items: dict[str, ImportRecord] = {}

    def get(self, import_id: str) -> ImportRecord | None:
        return deepcopy(self._items.get(import_id))

    def save(self, record: ImportRecord) -> None:
        self._items[record.id] = deepcopy(record)

    def list(self) -> list[ImportRecord]:
        return deepcopy(sorted(self._items.values(), key=lambda r: (r.created_at, r.id)))


class MemorySnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[str, SnapshotRecord] = {}

    def get(self, snapshot_id: str) -> SnapshotRecord | None:
        return deepcopy(self._items.get(snapshot_id))

    def add(self, record: SnapshotRecord) -> None:
        existing = self._items.get(record.id)
        if existing is not None:
            if canonical_json(snapshot_to_doc(existing)) != canonical_json(snapshot_to_doc(record)):
                raise ImmutabilityViolation(f"Снимок {record.id} уже опубликован с другим содержимым")
            return
        self._items[record.id] = deepcopy(record)

    def list(self, dataset_id: str | None = None) -> list[SnapshotRecord]:
        return deepcopy(sorted(
            (r for r in self._items.values() if dataset_id in (None, r.dataset_id)),
            key=lambda r: (r.published_at, r.id),
        ))


class MemoryRefRepository:
    def __init__(self) -> None:
        self._items: dict[str, DatasetRef] = {}

    def get(self, dataset_id: str) -> DatasetRef:
        return self._items.get(dataset_id, DatasetRef(dataset_id, None, ()))

    def save(self, ref: DatasetRef) -> None:
        self._items[ref.dataset_id] = ref

    def list(self) -> list[DatasetRef]:
        return [self._items[k] for k in sorted(self._items)]
