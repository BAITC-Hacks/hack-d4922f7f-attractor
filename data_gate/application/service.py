"""DataGateService — единственная точка входа для API, CLI и AI-tools.

Методы соответствуют эндпоинтам docs/02 §5:
    POST /datasets/imports                   → create_import
    GET  /datasets/imports/{id}/report       → get_report
    POST /datasets/imports/{id}/publish      → publish
плюс чтение снимков для движков и rollback из docs/05 §8.
"""

from __future__ import annotations

from dataclasses import asdict

from typing import Any, Iterable

from data_gate.application.ports import (
    Clock,
    ImportRepository,
    RawStore,
    RefRepository,
    SnapshotRepository,
    SourceParser,
)
from data_gate.domain.canonical import payload_checksum, sha256_bytes
from data_gate.domain.errors import (
    ImportNotFound,
    NothingToRollback,
    PublishBlocked,
    SnapshotNotFound,
    UnsupportedFormat,
)
from data_gate.domain.model import (
    SCHEMA_VERSION,
    TRANSFORM_VERSION,
    ChangePreview,
    DatasetRef,
    FieldMapping,
    ImportRecord,
    ImportStatus,
    Passport,
    PassportInput,
    QualityReport,
    RefEntry,
    SnapshotRecord,
)
from data_gate.domain.preview import build_preview
from data_gate.domain.quality import check_payload


class DataGateService:
    def __init__(
        self,
        *,
        parsers: Iterable[SourceParser],
        raw: RawStore,
        imports: ImportRepository,
        snapshots: SnapshotRepository,
        refs: RefRepository,
        clock: Clock,
    ) -> None:
        self._parsers = {parser.format_id: parser for parser in parsers}
        self._raw = raw
        self._imports = imports
        self._snapshots = snapshots
        self._refs = refs
        self._clock = clock

    @property
    def formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))

    # ------------------------------------------------------------------ импорт

    def create_import(
        self, content: bytes, source_format: str, passport: PassportInput
    ) -> ImportRecord:
        """raw → проверка → staging → нормализация → quality report.

        Идемпотентно: те же байты, формат, паспорт и версия преобразования дают тот же import id.
        """
        parser = self._parsers.get(source_format)
        if parser is None:
            raise UnsupportedFormat(
                f"Формат {source_format} не поддержан; доступны: {', '.join(self.formats)}",
                field="format",
            )
        raw_checksum = sha256_bytes(content)
        identity = payload_checksum({
            "raw": raw_checksum, "format": source_format,
            "passport": asdict(passport), "transform": TRANSFORM_VERSION,
        })
        import_id = f"imp-{passport.dataset_id}-{source_format}-{identity[:16]}"
        existing = self._imports.get(import_id)
        if existing is not None:
            return existing

        self._raw.put(raw_checksum, content)  # сырой слой хранится до любой проверки
        parsed = parser.parse(content)
        issues = check_payload(parsed.schema, parsed.payload, parsed.observations)
        report = QualityReport(id=f"qr-{identity[:16]}-{source_format}", issues=issues)
        record = ImportRecord(
            id=import_id,
            status=ImportStatus.REJECTED if report.blocks_publication else ImportStatus.READY,
            created_at=self._clock.now_iso(),
            passport=Passport(
                input=passport,
                schema=parsed.schema,
                schema_version=SCHEMA_VERSION,
                raw_checksum=raw_checksum,
                payload_checksum=payload_checksum(parsed.payload),
                transform_version=TRANSFORM_VERSION,
                source_format=source_format,
                quality_report_id=report.id,
            ),
            report=report,
            mapping=FieldMapping(parsed.mapped_fields, parsed.unmapped_fields),
            payload=parsed.payload,
        )
        self._imports.save(record)
        return record

    def get_import(self, import_id: str) -> ImportRecord:
        record = self._imports.get(import_id)
        if record is None:
            raise ImportNotFound(f"Импорт {import_id} не найден", field="importId")
        return record

    def get_report(self, import_id: str) -> dict[str, Any]:
        """Отчёт для GET /datasets/imports/{id}/report: ошибки, mapping, preview."""
        record = self.get_import(import_id)
        return record.to_api_dict(preview=self.preview(import_id))

    def preview(self, import_id: str) -> ChangePreview:
        record = self.get_import(import_id)
        current = self._current_snapshot(record.passport.input.dataset_id)
        return build_preview(
            current.id if current else None,
            current.payload if current else None,
            record.payload,
        )

    def list_imports(self) -> list[ImportRecord]:
        return self._imports.list()

    # -------------------------------------------------------------- публикация

    def publish(
        self, import_id: str, accepted_warnings: Iterable[str] = ()
    ) -> SnapshotRecord:
        """Публикует immutable-снимок и переводит на него указатель набора.

        Критические ошибки блокируют публикацию. Предупреждения требуют явного
        допущения (docs/05 §5): их коды перечисляются в accepted_warnings и
        попадают в manifest снимка.
        """
        record = self.get_import(import_id)
        if record.report.blocks_publication:
            raise PublishBlocked(
                f"Импорт {import_id}: {record.report.critical_count} критических ошибок",
                field="report",
            )
        accepted = tuple(sorted(set(accepted_warnings)))
        missing = record.report.warning_codes - set(accepted)
        if missing:
            raise PublishBlocked(
                "Нужна явная политика допущения для предупреждений: " + ", ".join(sorted(missing)),
                field="acceptedWarnings",
            )

        dataset_id = record.passport.input.dataset_id
        identity = payload_checksum({
            "payload": record.passport.payload_checksum,
            "passport": record.passport.to_api_dict(), "acceptedWarnings": accepted,
        })
        snapshot_id = f"{dataset_id}--{identity[:16]}"
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            snapshot = SnapshotRecord(
                id=snapshot_id,
                dataset_id=dataset_id,
                import_id=record.id,
                published_at=self._clock.now_iso(),
                passport=record.passport,
                accepted_warnings=accepted,
                payload=record.payload,
            )
            self._snapshots.add(snapshot)

        ref = self._refs.get(dataset_id)
        if ref.current != snapshot.id:
            self._refs.save(DatasetRef(
                dataset_id,
                snapshot.id,
                ref.history + (RefEntry(snapshot.id, "publish", self._clock.now_iso()),),
            ))
        if record.status is not ImportStatus.PUBLISHED:
            self._imports.save(record.mark_published(snapshot.id))
        return snapshot

    def rollback(self, dataset_id: str) -> DatasetRef:
        """Возвращает указатель на предыдущий опубликованный снимок. Lineage не удаляется."""
        ref = self._refs.get(dataset_id)
        if ref.current is None:
            raise NothingToRollback(f"У набора {dataset_id} нет опубликованных снимков", field="datasetId")
        previous = _previous_snapshot(ref)
        if previous is None:
            raise NothingToRollback(f"У набора {dataset_id} нет предыдущего снимка", field="datasetId")
        updated = DatasetRef(
            dataset_id, previous, ref.history + (RefEntry(previous, "rollback", self._clock.now_iso()),)
        )
        self._refs.save(updated)
        return updated

    # ----------------------------------------------------------------- чтение

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise SnapshotNotFound(f"Снимок {snapshot_id} не найден", field="snapshotId")
        return snapshot

    def current_snapshot(self, dataset_id: str) -> SnapshotRecord:
        snapshot = self._current_snapshot(dataset_id)
        if snapshot is None:
            raise SnapshotNotFound(f"У набора {dataset_id} нет опубликованного снимка", field="datasetId")
        return snapshot

    def list_snapshots(self, dataset_id: str | None = None) -> list[SnapshotRecord]:
        return self._snapshots.list(dataset_id)

    def dataset_ref(self, dataset_id: str) -> DatasetRef:
        return self._refs.get(dataset_id)

    def list_datasets(self) -> list[DatasetRef]:
        return self._refs.list()

    def _current_snapshot(self, dataset_id: str) -> SnapshotRecord | None:
        current = self._refs.get(dataset_id).current
        return self._snapshots.get(current) if current else None


def _previous_snapshot(ref: DatasetRef) -> str | None:
    """Предыдущий — последний снимок в журнале до текущего, отличный от него.

    Цепочка rollback'ов идёт назад по истории публикаций, а не мечется между двумя.
    """
    published = [entry.snapshot_id for entry in ref.history if entry.action == "publish"]
    distinct: list[str] = []
    for snapshot_id in published:
        if snapshot_id in distinct:
            distinct.remove(snapshot_id)
        distinct.append(snapshot_id)
    if ref.current not in distinct:
        return None
    index = distinct.index(ref.current)
    return distinct[index - 1] if index > 0 else None
