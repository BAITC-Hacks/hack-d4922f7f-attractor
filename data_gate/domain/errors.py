from __future__ import annotations


class DataGateError(Exception):
    """Базовая ошибка Data Gate. Поле `code` стабильно и уходит в API как есть."""

    code = "data_gate_error"

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def to_api_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


class SourceParseError(DataGateError):
    code = "source_parse_error"


class UnsupportedFormat(DataGateError):
    code = "unsupported_format"


class InvalidPassport(DataGateError):
    code = "invalid_passport"


class ImportNotFound(DataGateError):
    code = "import_not_found"


class SnapshotNotFound(DataGateError):
    code = "snapshot_not_found"


class PublishBlocked(DataGateError):
    code = "publish_blocked"


class ImmutabilityViolation(DataGateError):
    code = "immutability_violation"


class NothingToRollback(DataGateError):
    code = "nothing_to_rollback"
