"""Composition root: Data Gate publication -> pinned immutable engine snapshot."""
from hashlib import sha256
import json
import os
from threading import BoundedSemaphore, Lock, RLock

from ai.analysis import analyze
from data_gate.__main__ import OFFICIAL_PASSPORT, OFFICIAL_SOURCE
from data_gate.composition import create_file_gate
from engine.v1.application.alternatives import portfolio_key
from engine.v1.application.service import SimulationService
from engine.v1.infrastructure.json_snapshot import snapshot_from_payload


class Runtime:
    def __init__(self, gate=None, analyst_factory=None):
        self.gate = gate if gate is not None else create_file_gate()
        self.gate_lock = RLock()
        record = self.gate.create_import(OFFICIAL_SOURCE.read_bytes(), "source-text-v1", OFFICIAL_PASSPORT)
        self.published = self.gate.publish(record.id)
        self.service = SimulationService(snapshot_from_payload(self.published.payload))
        self.versions = {
            "catalogVersion": self.published.passport.payload_checksum,
            "dataSnapshotId": self.published.id,
            "modelVersion": "v1/1.0.0", "rulesVersion": self.service.snapshot.rules_version,
        }
        self.analyst_factory = analyst_factory
        self._analysis_slots = BoundedSemaphore(1)
        self._budget_lock = Lock()
        self._used_analyses = 0

    def analysis(self, selections):
        identity = json.dumps([self.versions, portfolio_key(selections)], sort_keys=True)
        kwargs = {"snapshot_id": self.published.id,
                  "portfolio_id": sha256(identity.encode()).hexdigest()}
        if not self.service.validate(selections).valid:
            return analyze(self.service, selections, **kwargs)
        if not self._analysis_slots.acquire(blocking=False):
            return analyze(self.service, selections, unavailable_reason="llm_busy", **kwargs)
        client = None
        try:
            analyst = None
            reason = "not_configured"
            if self.analyst_factory:
                analyst = self.analyst_factory()
            elif os.getenv("AKIM_LLM_ENABLED") == "1" and os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"):
                with self._budget_lock:
                    try:
                        limit = max(0, min(100, int(os.getenv("AKIM_LLM_MAX_ANALYSES", "10"))))
                    except ValueError:
                        limit = 0  # Invalid budget configuration fails closed.
                    allowed = self._used_analyses < limit
                    if allowed:
                        self._used_analyses += 1
                if allowed:
                    from openai import OpenAI
                    from ai.openai_adapter import OpenAIAnalyst
                    client = OpenAI(max_retries=0, timeout=20)
                    analyst = OpenAIAnalyst(client, os.environ["OPENAI_MODEL"])
                else:
                    reason = "llm_budget_exhausted"
            return analyze(self.service, selections, analyst=analyst, unavailable_reason=reason, **kwargs)
        finally:
            if client is not None:
                client.close()
            self._analysis_slots.release()
