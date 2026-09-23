"""Install the built wheel into a fresh directory, verify modules/assets outside checkout."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

CHECK = """
import importlib, pathlib, sys
installed = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed))
for name in ('engine', 'data_gate', 'data', 'services', 'ai'):
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(installed), name
from engine.v1 import create_official_service
assert abs(create_official_service().inspect_baseline().score - 52.55768) < 1e-8
from data_gate.__main__ import main
assert main(['--store', 'gate', 'bootstrap']) == 0
assert pathlib.Path('gate/exports/official-v1.snapshot.json').is_file()
from fastapi.testclient import TestClient
from services.api.app import create_app
with TestClient(create_app()) as client:
    assert client.get('/catalog').status_code == 200
    assert len(client.get('/catalog').json()['measures']) == 14
    assert client.post('/v1/evaluate', json={'selections': []}).json()['score'] is None
print('WHEEL_SMOKE_OK')
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="akim-wheel-") as directory:
        root = Path(directory)
        installed = root / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed),
                        str(wheel)], check=True, cwd=root)
        subprocess.run([sys.executable, "-I", "-c", CHECK, str(installed)], check=True, cwd=root)


if __name__ == "__main__":
    main()
