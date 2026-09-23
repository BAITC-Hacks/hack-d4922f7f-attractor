from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class FixedClock:
    """Детерминированные часы для тестов и воспроизводимых прогонов."""

    def __init__(self, start: str = "2026-09-23T00:00:00") -> None:
        self._base = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        self._tick = 0

    def now_iso(self) -> str:
        from datetime import timedelta

        self._tick += 1
        return (self._base + timedelta(seconds=self._tick)).isoformat()
