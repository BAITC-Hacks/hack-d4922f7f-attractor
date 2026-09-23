from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from data_gate import PassportInput, SourceType, create_memory_gate
from data_gate.infrastructure.clock import FixedClock

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "data" / "source-dataset.ru.txt"


def source_bytes() -> bytes:
    return SOURCE.read_bytes()


def passport(dataset_id: str = "official-v1") -> PassportInput:
    return PassportInput(
        dataset_id=dataset_id,
        source_type=SourceType.SYNTHETIC,
        source_uri="repo:data/source-dataset.ru.txt",
        license_or_permission="hackathon-task-provided",
        retrieved_at="2026-09-23",
        valid_from="2026-09-23",
    )


def memory_gate():
    return create_memory_gate(FixedClock())


def official_payload() -> dict[str, Any]:
    gate = memory_gate()
    return copy.deepcopy(dict(gate.create_import(source_bytes(), "source-text-v1", passport()).payload))


def as_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
