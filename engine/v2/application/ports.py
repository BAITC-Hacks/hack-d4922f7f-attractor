from contextlib import AbstractContextManager
from typing import Protocol


class DocumentStore(Protocol):
    """Atomic document transactions; a committed run includes its queue and event log."""

    def read(self, kind: str, key: str) -> dict | None: ...
    def keys(self, kind: str) -> list[str]: ...
    def transaction(self, kind: str, key: str) -> AbstractContextManager[dict]: ...
