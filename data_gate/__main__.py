"""CLI Data Gate. Все команды печатают JSON — тот же, что отдаст HTTP API.

    python -m data_gate bootstrap                  исходник ТЗ → проверка → публикация → экспорт
    python -m data_gate import FILE --format F --dataset ID [паспорт]
    python -m data_gate report IMPORT_ID
    python -m data_gate publish IMPORT_ID [--accept-warning CODE ...]
    python -m data_gate rollback DATASET
    python -m data_gate list
    python -m data_gate export DATASET [--snapshot ID] --out PATH

Хранилище: var/data-gate/ или каталог из переменной AKIM_DATA_GATE_DIR.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

from data_gate.application.service import DataGateService
from data_gate.composition import create_file_gate, default_store_dir
from data_gate.domain.errors import DataGateError
from data_gate.domain.model import PassportInput, SourceType

OFFICIAL_PASSPORT = PassportInput(
    dataset_id="official-v1",
    source_type=SourceType.SYNTHETIC,
    source_uri="repo:data/source-dataset.ru.txt",
    license_or_permission="hackathon-task-provided",
    retrieved_at="2026-09-23",
    valid_from="2026-09-23",
    geography_version="synthetic-districts-v1",
    units="index-0-100; budget-conditional-units; quarters",
    owner="HackAlem AI, трек 12 «Аким на 5 часов»",
    usage_restrictions="только задача хакатона",
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    gate = create_file_gate(Path(args.store) if args.store else None)
    try:
        result = args.handler(gate, args)
    except DataGateError as error:
        _print({"error": error.to_api_dict()})
        return 2
    _print(result)
    return 0


def _bootstrap(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source) if args.source else files("data").joinpath("source-dataset.ru.txt")
    record = gate.create_import(source.read_bytes(), "source-text-v1", OFFICIAL_PASSPORT)
    snapshot = gate.publish(record.id)
    store = Path(args.store) if args.store else default_store_dir()
    out = Path(args.out) if args.out else store / "exports" / "official-v1.snapshot.json"
    _write_payload(out, snapshot.payload)
    return {
        "importId": record.id,
        "status": gate.get_import(record.id).status.value,
        "report": record.report.to_api_dict(),
        "snapshot": snapshot.manifest_api_dict(),
        "exportedTo": str(out),
    }


def _import(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    passport = PassportInput(
        dataset_id=args.dataset,
        source_type=SourceType(args.source_type),
        source_uri=args.source_uri or f"file:{Path(args.file).name}",
        license_or_permission=args.license,
        retrieved_at=args.retrieved_at,
        valid_from=args.valid_from or args.retrieved_at,
        geography_version=args.geography_version,
        units=args.units,
    )
    record = gate.create_import(Path(args.file).read_bytes(), args.format, passport)
    return gate.get_report(record.id)


def _report(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    return gate.get_report(args.import_id)


def _publish(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    return gate.publish(args.import_id, args.accept_warning).manifest_api_dict()


def _rollback(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    return gate.rollback(args.dataset).to_api_dict()


def _list(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "formats": list(gate.formats),
        "datasets": [ref.to_api_dict() for ref in gate.list_datasets()],
        "snapshots": [s.manifest_api_dict() for s in gate.list_snapshots()],
        "imports": [
            {"id": r.id, "status": r.status.value, "datasetId": r.passport.input.dataset_id}
            for r in gate.list_imports()
        ],
    }


def _export(gate: DataGateService, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = gate.get_snapshot(args.snapshot) if args.snapshot else gate.current_snapshot(args.dataset)
    _write_payload(Path(args.out), snapshot.payload)
    return {"snapshotId": snapshot.id, "exportedTo": args.out}


def _write_payload(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print(value: Any) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m data_gate", description="Data Gate: импорт и снимки данных AKIM")
    root.add_argument("--store", help="каталог хранилища (по умолчанию var/data-gate)")
    sub = root.add_subparsers(required=True, metavar="command")

    p = sub.add_parser("bootstrap", help="исходник ТЗ → официальный снимок official-v1")
    p.add_argument("--source", help="исходный файл (по умолчанию встроенный датасет)")
    p.add_argument("--out", help="куда экспортировать payload для движка")
    p.set_defaults(handler=_bootstrap)

    p = sub.add_parser("import", help="создать импорт и получить отчёт качества")
    p.add_argument("file")
    p.add_argument("--format", required=True, choices=("source-text-v1", "city-json-v1", "geojson-v1"))
    p.add_argument("--dataset", required=True)
    p.add_argument("--source-type", default="synthetic", choices=[t.value for t in SourceType])
    p.add_argument("--source-uri")
    p.add_argument("--license", default="project-synthetic")
    p.add_argument("--retrieved-at", default="2026-09-23")
    p.add_argument("--valid-from")
    p.add_argument("--geography-version", default="synthetic-districts-v1")
    p.add_argument("--units", default="unspecified")
    p.set_defaults(handler=_import)

    p = sub.add_parser("report", help="отчёт импорта: ошибки, mapping, preview")
    p.add_argument("import_id")
    p.set_defaults(handler=_report)

    p = sub.add_parser("publish", help="опубликовать immutable-снимок")
    p.add_argument("import_id")
    p.add_argument("--accept-warning", action="append", default=[], metavar="CODE")
    p.set_defaults(handler=_publish)

    p = sub.add_parser("rollback", help="вернуть предыдущий снимок набора")
    p.add_argument("dataset")
    p.set_defaults(handler=_rollback)

    p = sub.add_parser("list", help="наборы, снимки и импорты")
    p.set_defaults(handler=_list)

    p = sub.add_parser("export", help="выгрузить payload снимка в JSON для движка")
    p.add_argument("dataset")
    p.add_argument("--snapshot")
    p.add_argument("--out", required=True)
    p.set_defaults(handler=_export)
    return root


if __name__ == "__main__":
    raise SystemExit(main())
