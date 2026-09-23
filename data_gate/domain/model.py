from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from data_gate.domain.errors import InvalidPassport

DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SCHEMA_VERSION = "1"
TRANSFORM_VERSION = "data-gate/1.1.0"


class Severity(str, Enum):
    """critical блокирует публикацию; warning требует явного допущения; info — справка."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class SourceType(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    SYNTHETIC = "synthetic"


class ImportStatus(str, Enum):
    REJECTED = "rejected"  # есть критические ошибки, публикация невозможна
    READY = "ready"  # проверки пройдены, можно публиковать
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: Severity
    field: str
    message: str

    def to_api_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    id: str
    issues: tuple[QualityIssue, ...]

    @property
    def critical_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is Severity.CRITICAL)

    @property
    def warning_codes(self) -> frozenset[str]:
        return frozenset(
            issue.code for issue in self.issues if issue.severity is Severity.WARNING
        )

    @property
    def blocks_publication(self) -> bool:
        return self.critical_count > 0

    def to_api_dict(self) -> dict[str, Any]:
        counts = {severity.value: 0 for severity in Severity}
        for issue in self.issues:
            counts[issue.severity.value] += 1
        return {
            "id": self.id,
            "counts": counts,
            "blocksPublication": self.blocks_publication,
            "issues": [issue.to_api_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class PassportInput:
    """То, что сообщает о наборе человек или адаптер. Остальное Data Gate вычисляет сам."""

    dataset_id: str
    source_type: SourceType
    source_uri: str
    license_or_permission: str
    retrieved_at: str
    valid_from: str
    valid_to: str | None = None
    geography_version: str = "unspecified"
    units: str = "unspecified"
    currency: str | None = None
    price_base_period: str | None = None
    missingness_policy: str = "explicit-null"
    owner: str = "unspecified"
    usage_restrictions: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not DATASET_ID_PATTERN.fullmatch(self.dataset_id):
            raise InvalidPassport(
                "dataset_id: только a-z, 0-9 и '-', до 64 символов",
                field="datasetId",
            )
        for name in ("source_uri", "license_or_permission", "retrieved_at", "valid_from"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise InvalidPassport(f"{name} обязателен", field=name)
        if not isinstance(self.source_type, SourceType):
            raise InvalidPassport("Некорректный sourceType", field="sourceType")
        dates = {}
        for name in ("retrieved_at", "valid_from", "valid_to"):
            value = getattr(self, name)
            if name == "valid_to" and value is None:
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                dates[name] = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            except (ValueError, TypeError, AttributeError) as error:
                raise InvalidPassport("Нужна дата ISO-8601", field=name) from error
        if self.valid_to is not None and dates["valid_to"] < dates["valid_from"]:
            raise InvalidPassport("validTo раньше validFrom", field="validTo")

    @classmethod
    def from_api_dict(cls, raw: Mapping[str, Any]) -> "PassportInput":
        try:
            return cls(
                dataset_id=raw["datasetId"],
                source_type=SourceType(raw["sourceType"]),
                source_uri=raw["sourceUri"],
                license_or_permission=raw["licenseOrPermission"],
                retrieved_at=raw["retrievedAt"],
                valid_from=raw["validFrom"],
                valid_to=raw.get("validTo"),
                geography_version=raw.get("geographyVersion", "unspecified"),
                units=raw.get("units", "unspecified"),
                currency=raw.get("currency"),
                price_base_period=raw.get("priceBasePeriod"),
                missingness_policy=raw.get("missingnessPolicy", "explicit-null"),
                owner=raw.get("owner", "unspecified"),
                usage_restrictions=raw.get("usageRestrictions", "none"),
            )
        except KeyError as error:
            raise InvalidPassport(f"не хватает поля {error.args[0]}", field=error.args[0]) from error
        except (ValueError, TypeError) as error:
            raise InvalidPassport(str(error), field="sourceType") from error


@dataclass(frozen=True, slots=True)
class Passport:
    """Паспорт набора из docs/05 §3: ввод человека + вычисленные Data Gate поля."""

    input: PassportInput
    schema: str
    schema_version: str
    raw_checksum: str
    payload_checksum: str
    transform_version: str
    source_format: str
    quality_report_id: str

    def to_api_dict(self) -> dict[str, Any]:
        i = self.input
        return {
            "datasetId": i.dataset_id,
            "schema": self.schema,
            "schemaVersion": self.schema_version,
            "sourceType": i.source_type.value,
            "sourceFormat": self.source_format,
            "sourceUri": i.source_uri,
            "licenseOrPermission": i.license_or_permission,
            "retrievedAt": i.retrieved_at,
            "validFrom": i.valid_from,
            "validTo": i.valid_to,
            "geographyVersion": i.geography_version,
            "units": i.units,
            "currency": i.currency,
            "priceBasePeriod": i.price_base_period,
            "rawChecksum": self.raw_checksum,
            "checksum": self.payload_checksum,
            "transformVersion": self.transform_version,
            "missingnessPolicy": i.missingness_policy,
            "qualityReportId": self.quality_report_id,
            "owner": i.owner,
            "usageRestrictions": i.usage_restrictions,
        }


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """Какие поля источника стали входом модели, а какие остались только в raw."""

    mapped: tuple[str, ...]
    unmapped: tuple[str, ...]

    def to_api_dict(self) -> dict[str, list[str]]:
        return {"mapped": list(self.mapped), "unmapped": list(self.unmapped)}


@dataclass(frozen=True, slots=True)
class FieldChange:
    path: str
    before: Any
    after: Any

    def to_api_dict(self) -> dict[str, Any]:
        return {"path": self.path, "before": self.before, "after": self.after}


@dataclass(frozen=True, slots=True)
class ChangePreview:
    """Что изменится относительно текущего опубликованного снимка набора."""

    base_snapshot_id: str | None
    changes: tuple[FieldChange, ...]
    truncated: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "baseSnapshotId": self.base_snapshot_id,
            "changeCount": len(self.changes),
            "truncated": self.truncated,
            "changes": [change.to_api_dict() for change in self.changes],
        }


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: str
    status: ImportStatus
    created_at: str
    passport: Passport
    report: QualityReport
    mapping: FieldMapping
    payload: Mapping[str, Any]
    published_snapshot_id: str | None = None

    def mark_published(self, snapshot_id: str) -> "ImportRecord":
        return replace(self, status=ImportStatus.PUBLISHED, published_snapshot_id=snapshot_id)

    def to_api_dict(self, preview: ChangePreview | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "status": self.status.value,
            "createdAt": self.created_at,
            "passport": self.passport.to_api_dict(),
            "report": self.report.to_api_dict(),
            "mapping": self.mapping.to_api_dict(),
            "publishedSnapshotId": self.published_snapshot_id,
        }
        if preview is not None:
            result["preview"] = preview.to_api_dict()
        return result


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """Опубликованный immutable-снимок. Эксперименты ссылаются на него по id."""

    id: str
    dataset_id: str
    import_id: str
    published_at: str
    passport: Passport
    accepted_warnings: tuple[str, ...]
    payload: Mapping[str, Any] = field(repr=False)

    def manifest_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "datasetId": self.dataset_id,
            "importId": self.import_id,
            "publishedAt": self.published_at,
            "passport": self.passport.to_api_dict(),
            "acceptedWarnings": list(self.accepted_warnings),
        }


@dataclass(frozen=True, slots=True)
class RefEntry:
    """Одна запись журнала указателя: публикация или rollback. Журнал только растёт."""

    snapshot_id: str
    action: str
    at: str

    def to_api_dict(self) -> dict[str, str]:
        return {"snapshotId": self.snapshot_id, "action": self.action, "at": self.at}


@dataclass(frozen=True, slots=True)
class DatasetRef:
    dataset_id: str
    current: str | None
    history: tuple[RefEntry, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "current": self.current,
            "history": [entry.to_api_dict() for entry in self.history],
        }
