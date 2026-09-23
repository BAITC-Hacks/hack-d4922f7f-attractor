"""Preview изменений (docs/05 §1): построчный diff нового payload против опубликованного."""

from __future__ import annotations

from typing import Any, Mapping

from data_gate.domain.model import ChangePreview, FieldChange

MAX_CHANGES = 500
_ID_KEYS = ("id", "code")


def build_preview(
    base_snapshot_id: str | None, before: Mapping[str, Any] | None, after: Mapping[str, Any]
) -> ChangePreview:
    changes: list[FieldChange] = []
    _diff("", before if before is not None else {}, after, changes)
    truncated = len(changes) > MAX_CHANGES
    return ChangePreview(base_snapshot_id, tuple(changes[:MAX_CHANGES]), truncated)


def _diff(path: str, before: Any, after: Any, out: list[FieldChange]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            child = f"{path}.{key}" if path else str(key)
            if key not in before:
                out.append(FieldChange(child, None, after[key]))
            elif key not in after:
                out.append(FieldChange(child, before[key], None))
            else:
                _diff(child, before[key], after[key], out)
        return
    if isinstance(before, list) and isinstance(after, list):
        key = _list_key(before) or _list_key(after)
        if key and _list_key(before) == _list_key(after) or (key and not before):
            _diff(path, {item[key]: item for item in before}, {item[key]: item for item in after}, out)
            return
    if before != after:
        out.append(FieldChange(path, before, after))


def _list_key(items: list[Any]) -> str | None:
    """Списки объектов с id сравниваются по id, а не по позиции."""
    if not items or not all(isinstance(item, dict) for item in items):
        return None
    for key in _ID_KEYS:
        values = [item.get(key) for item in items]
        if all(isinstance(v, str) for v in values) and len(set(values)) == len(values):
            return key
    return None
