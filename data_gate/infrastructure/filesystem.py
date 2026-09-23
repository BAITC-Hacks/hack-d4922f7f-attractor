"""Файловое хранилище Data Gate (локальный профиль из docs/02 §2).

    <root>/raw/<sha256>                 сырые байты источника
    <root>/imports/<import_id>.json     импорт: паспорт, отчёт, mapping, staging payload
    <root>/snapshots/<snapshot_id>.json опубликованный снимок: manifest + payload
    <root>/refs/<dataset_id>.json       указатель current + журнал publish/rollback

Запись атомарная (tmp + os.replace). Снимки не перезаписываются.
Каталог сам кладёт в себя .gitignore: рантайм-состояние не попадает в git.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, TypeVar

from data_gate.domain.canonical import canonical_json
from data_gate.domain.errors import DataGateError, ImmutabilityViolation
from data_gate.domain.model import DatasetRef, ImportRecord, SnapshotRecord
from data_gate.infrastructure.serialization import (
    import_from_doc,
    import_to_doc,
    ref_from_doc,
    ref_to_doc,
    snapshot_from_doc,
    snapshot_to_doc,
)

T = TypeVar("T")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        for sub in ("raw", "imports", "snapshots", "refs"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        ignore = root / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

    def path(self, kind: str, name: str, suffix: str = ".json") -> Path:
        if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
            raise DataGateError(f"Недопустимое имя объекта хранилища: {name!r}")
        return self.root / kind / f"{name}{suffix}"

    def write_bytes(self, path: Path, data: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
            tmp = Path(file.name)
            file.write(data)
        try:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def write_json(self, path: Path, doc: Any) -> None:
        text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.write_bytes(path, text.encode("utf-8"))

    def read_json(self, path: Path, build: Callable[[Any], T]) -> T | None:
        if not path.exists():
            return None
        return build(json.loads(path.read_text(encoding="utf-8")))

    def read_all(self, kind: str, build: Callable[[Any], T]) -> list[T]:
        return [
            build(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted((self.root / kind).glob("*.json"))
        ]


class FileRawStore:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def put(self, checksum: str, content: bytes) -> None:
        path = self._store.path("raw", checksum, "")
        if not path.exists():
            self._store.write_bytes(path, content)

    def get(self, checksum: str) -> bytes:
        return self._store.path("raw", checksum, "").read_bytes()


class FileImportRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def get(self, import_id: str) -> ImportRecord | None:
        return self._store.read_json(self._store.path("imports", import_id), import_from_doc)

    def save(self, record: ImportRecord) -> None:
        self._store.write_json(self._store.path("imports", record.id), import_to_doc(record))

    def list(self) -> list[ImportRecord]:
        return sorted(self._store.read_all("imports", import_from_doc), key=lambda r: (r.created_at, r.id))


class FileSnapshotRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def get(self, snapshot_id: str) -> SnapshotRecord | None:
        return self._store.read_json(self._store.path("snapshots", snapshot_id), snapshot_from_doc)

    def add(self, record: SnapshotRecord) -> None:
        path = self._store.path("snapshots", record.id)
        doc = snapshot_to_doc(record)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if canonical_json(existing) != canonical_json(doc):
                raise ImmutabilityViolation(f"Снимок {record.id} уже опубликован с другим содержимым")
            return
        self._store.write_json(path, doc)

    def list(self, dataset_id: str | None = None) -> list[SnapshotRecord]:
        return sorted(
            (r for r in self._store.read_all("snapshots", snapshot_from_doc) if dataset_id in (None, r.dataset_id)),
            key=lambda r: (r.published_at, r.id),
        )


class FileRefRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def get(self, dataset_id: str) -> DatasetRef:
        ref = self._store.read_json(self._store.path("refs", dataset_id), ref_from_doc)
        return ref or DatasetRef(dataset_id, None, ())

    def save(self, ref: DatasetRef) -> None:
        self._store.write_json(self._store.path("refs", ref.dataset_id), ref_to_doc(ref))

    def list(self) -> list[DatasetRef]:
        return self._store.read_all("refs", ref_from_doc)
