"""Data Gate: единый путь от источника к проверенному immutable-снимку (docs/05-data-gate.md).

Слои:
    domain/          чистые сущности и правила качества, без I/O
    application/     сценарии импорта, preview, публикации и rollback; порты
    infrastructure/  адаптеры форматов и хранилища
"""

from data_gate.application.service import DataGateService
from data_gate.composition import create_file_gate, create_memory_gate
from data_gate.domain.errors import DataGateError, ImportNotFound, PublishBlocked, SnapshotNotFound
from data_gate.domain.model import (
    ImportRecord,
    ImportStatus,
    PassportInput,
    QualityIssue,
    QualityReport,
    Severity,
    SnapshotRecord,
    SourceType,
)

__all__ = [
    "DataGateError",
    "DataGateService",
    "ImportNotFound",
    "ImportRecord",
    "ImportStatus",
    "PassportInput",
    "PublishBlocked",
    "QualityIssue",
    "QualityReport",
    "Severity",
    "SnapshotNotFound",
    "SnapshotRecord",
    "SourceType",
    "create_file_gate",
    "create_memory_gate",
]
