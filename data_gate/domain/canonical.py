"""Каноническая сериализация: одинаковые данные → одинаковый checksum на любой машине."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_checksum(payload: Any) -> str:
    return sha256_bytes(canonical_json(payload).encode("utf-8"))
