"""Bounded paired experiments: same past, weather and keyed random streams."""
from copy import deepcopy

from engine.v2.application.controller import RunError, digest, interval, required, now
from engine.v2.domain.simulation import initial_state, advance, apply_decision


def final_metrics(state):
    """Normalize domain points into a metric-id lookup (projection, never scoring)."""
    result = {}
    for point in state.get("metrics", []):
        name = point.get("metricId", point.get("metric"))
        if name and point.get("districtId") is None:
            result[name] = point
    return result


class Experiments:
    def __init__(self, store):
        self.store = store

    def create(self, request, key):
        scenario = required(self.store.read("scenario", request["scenarioId"]), "scenarioId")
        if len(set(request["seeds"])) != len(request["seeds"]):
            raise RunError("duplicate_seed", "seeds", "Seed должны быть уникальными")
        if request["warmup"] >= request["horizon"]:
            raise RunError("invalid_horizon", "horizon", "Горизонт должен быть больше warmup")
        if scenario["timeMode"] == "operational" and request["horizon"] > 10080:
            raise RunError("compute_budget", "horizon", "Оперативный ансамбль ограничен 7 сутками")
        if request["intervention"]["type"].startswith("clock."):
            raise RunError("invalid_intervention", "intervention.type", "Нужна управленческая команда")
        identity = "experiment-" + digest(key)[:24]
        with self.store.transaction("experiment", identity) as record:
            if record:
                if record["requestHash"] != digest(request):
                    raise RunError("idempotency_conflict", "Idempotency-Key", "Ключ уже использован", 409)
            else:
                record.update({"experimentId": identity, "status": "queued", "requestHash": digest(request),
                               "protocol": deepcopy(request), "createdAt": now(), "pairs": [],
                               "primaryOutcome": "service-unavailability-hours",
                               "question": "Как решение меняет исходы внутри синтетической модели?",
                               "baseline": "no-intervention", "analysis": "paired-difference-with-interval",
                               "stoppingRule": "predefined-seeds-and-horizon", "dataSnapshotId": scenario["dataSnapshotId"],
                               "dataHash": scenario["dataHash"], "parameterHash": digest(scenario["parameters"]),
                               "modelVersion": scenario["modelVersion"], "summary": {},
                               "limitations": ["Seed-интервал отражает случайность, не ошибку данных или модели.",
                                                "Синтетические коэффициенты не калиброваны на реальном городе."]})
        return self.get(identity)

    def get(self, identity):
        return required(self.store.read("experiment", identity), "experimentId")

    def work(self, identity):
        with self.store.transaction("experiment", identity) as experiment:
            if not experiment or experiment["status"] in ("completed", "failed", "cancelled"):
                return False
            protocol = experiment["protocol"]
            scenario = required(self.store.read("scenario", protocol["scenarioId"]), "scenarioId")
            index = len(experiment["pairs"])
            seed = protocol["seeds"][index]
            family = digest([scenario["id"], seed])[:24]
            try:
                baseline = initial_state(deepcopy(scenario["snapshot"]), seed, family,
                                         deepcopy(scenario["parameters"]))
                advance(baseline, protocol["warmup"])
                intervention = deepcopy(baseline)
                decision = {"commandId": f"experiment-{seed}", "issuedBy": "approved-experiment",
                            **protocol["intervention"]}
                # Both endpoints require explicit user command; assistant cannot create jobs.
                apply_decision(intervention, decision)
                advance(baseline, protocol["horizon"] - protocol["warmup"])
                advance(intervention, protocol["horizon"] - protocol["warmup"])
                left, right = final_metrics(baseline), final_metrics(intervention)
                difference = {name: right[name]["value"] - point["value"] for name, point in left.items()
                              if name in right and point.get("value") is not None
                              and right[name].get("value") is not None}
                experiment["pairs"].append({"seed": seed, "baseline": left, "intervention": right,
                    "difference": difference,
                    "budgetViolation": any(s["ledger"]["cash"] < s["ledger"].get("reserved", 0)
                                           + s["ledger"].get("requiredReserve", 0) for s in (baseline, intervention)),
                    "baselineHash": digest(baseline), "interventionHash": digest(intervention)})
                experiment["status"] = "running"
                if len(experiment["pairs"]) == len(protocol["seeds"]):
                    names = set.intersection(*(set(pair["difference"]) for pair in experiment["pairs"]))
                    experiment["summary"] = {name: {**interval([pair["difference"][name]
                                                               for pair in experiment["pairs"]]),
                                                     "unit": left[name]["unit"]} for name in sorted(names)}
                    experiment["budgetViolationRate"] = sum(p["budgetViolation"] for p in experiment["pairs"]) / len(protocol["seeds"])
                    experiment["status"] = "completed"
            except Exception as error:
                experiment["status"] = "failed"
                experiment["error"] = {"code": "experiment_failed", "message": str(error)[:500]}
            return True
