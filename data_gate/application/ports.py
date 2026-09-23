"""Порты прикладного слоя. Инфраструктура реализует их, домен о них не знает."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from data_gate.domain.model import DatasetRef, ImportRecord, SnapshotRecord


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """Результат адаптера: нормализованный payload + то, что в модель не пошло."""

    schema: str
    payload: Mapping[str, Any]
    mapped_fields: tuple[str, ...]
    unmapped_fields: tuple[str, ...] = ()
    # Контрольные значения источника для сверки (например «Итог D»), в payload не входят.
    observations: Mapping[str, Any] = field(default_factory=dict)


class SourceParser(Protocol):
    format_id: str

    def parse(self, content: bytes) -> ParsedSource: ...


class RawStore(Protocol):
    """Сырой слой: байты источника как есть, адресуются checksum."""

    def put(self, checksum: str, content: bytes) -> None: ...

    def get(self, checksum: str) -> bytes: ...


class ImportRepository(Protocol):
    def get(self, import_id: str) -> ImportRecord | None: ...

    def save(self, record: ImportRecord) -> None: ...

    def list(self) -> list[ImportRecord]: ...


class SnapshotRepository(Protocol):
    """Снимки неизменяемы: повторная запись того же id с другим содержимым — ошибка."""

    def get(self, snapshot_id: str) -> SnapshotRecord | None: ...

    def add(self, record: SnapshotRecord) -> None: ...

    def list(self, dataset_id: str | None = None) -> list[SnapshotRecord]: ...


class RefRepository(Protocol):
    """Указатель «текущий снимок набора» + журнал его изменений."""

    def get(self, dataset_id: str) -> DatasetRef: ...

    def save(self, ref: DatasetRef) -> None: ...

    def list(self) -> list[DatasetRef]: ...


class Clock(Protocol):
    def now_iso(self) -> str: ...
