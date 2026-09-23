"""Generate the versioned HTTP contract, or check it without changing files."""
import argparse
import json
import sys
from pathlib import Path

from services.api.app import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "packages/contracts/openapi.json"
    expected = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            print("OpenAPI contract is stale; run python -m scripts.export_openapi")
            return 1
        print("OpenAPI contract is current")
    else:
        target.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
