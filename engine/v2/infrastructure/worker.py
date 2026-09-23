"""Separate worker process. Jobs and their recovery state live in the database."""
import logging
import signal
import time

from engine.v2.application.controller import RunController, now
from engine.v2.application.experiments import Experiments
from engine.v2.infrastructure.store import create_store


def main():
    logging.basicConfig(level=logging.INFO)
    store = create_store()
    controller, experiments = RunController(store), Experiments(store)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped:
        started = time.monotonic()
        try:
            for run_id in store.keys("run"):
                if stopped:
                    break
                current = store.read("run", run_id)
                if current["status"] == "running" or current.get("pending"):
                    controller.work_run(run_id)
            for experiment_id in store.keys("experiment"):
                if stopped:
                    break
                current = store.read("experiment", experiment_id)
                if current["status"] in ("queued", "running"):
                    experiments.work(experiment_id)
            with store.transaction("system", "worker") as heartbeat:
                heartbeat.update({"heartbeat": now(), "batchSeconds": time.monotonic() - started})
        except Exception:
            logging.exception("Worker batch failed; committed state is preserved")
        time.sleep(max(0.01, .5 - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
