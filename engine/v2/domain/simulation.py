"""Deterministic synthetic city transitions, with no I/O or V1 dependencies.

Operational resolution is 15 model minutes. Strategic resolution samples physical
service demand once per day and runs stocks/flows once per 30-day model month.
Neither resolution is calibrated to a real city. State consists only of JSON values.
"""

from copy import deepcopy
from hashlib import sha256
import json
import math


MODEL_VERSION = "v2-demo/1.0"
RNG_VERSION = "sha256-keyed/1.0"
MONTH_MINUTES = 30 * 24 * 60


class DomainError(ValueError):
    def __init__(self, code: str, field: str, message: str):
        self.code, self.field, self.message = code, field, message
        super().__init__(message)


# Configurable coefficients are explicit assumptions; ranges support bounded sensitivity.
PARAMETERS = {
    "snowIntensity": (0.8, "fraction", 0, 1),
    "snowCapacityLoss": (0.6, "fraction/intensity", 0, 0.95),
    "crewSnowLoss": (0.35, "fraction/intensity", 0, 0.95),
    "crewProductivity": (3.5, "job/15min/crew", 0, 100),
    "snowJobRate": (0.30, "job/100-person/15min/intensity", 0, 5),
    "backlogCapacityLoss": (0.015, "fraction/job", 0, 0.1),
    "tripRate": (0.10, "trip/person/15min", 0, 1),
    "congestionAlpha": (0.15, "dimensionless", 0, 2),
    "congestionPower": (4.0, "dimensionless", 1, 8),
    "appealPropensity": (0.7, "probability", 0, 1),
    "crewCost": (1200.0, "KZT/crew/15min", 0, 100000),
    "reassignmentCost": (5000.0, "KZT/crew", 0, 1000000),
    "monthlyBirthRate": (0.0012, "birth/person/month", 0, 0.01),
    "monthlyDeathRate": (0.0005, "death/person/month", 0, 0.01),
    "monthlyOutRate": (0.0007, "fraction/month", 0, 0.05),
    "externalInflow": (70.0, "person/month/city", 0, 100000),
    "internalMoveRate": (0.001, "fraction/month", 0, 0.05),
    "householdSize": (3.0, "person/household", 1, 8),
    "priceElasticity": (0.04, "fraction/month", 0, 0.5),
    "monthlyWage": (250000.0, "KZT/person/month", 0, 10000000),
    "employmentRate": (0.65, "fraction/adult", 0, 1),
    "incomeTaxRate": (0.10, "fraction/income", 0, 0.5),
    "propertyTaxRate": (0.00002, "fraction/value/month", 0, 0.01),
    "serviceCostPerPerson": (1000.0, "KZT/person/month", 0, 1000000),
    "monthlyTransfer": (1000000.0, "KZT/month/city", 0, 1000000000),
    "monthlyInflation": (0.003, "fraction/month", -0.02, 0.1),
    "constructionCost": (20000000.0, "KZT/dwelling", 1, 1000000000),
    "constructionMonths": (6.0, "month", 1, 120),
    "supportInertia": (0.15, "fraction/month", 0, 1),
    "voteSupportWeight": (2.0, "dimensionless", 0, 10),
}


def _number(value, field: str, minimum: float = 0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DomainError("invalid_value", field, "Expected a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise DomainError("out_of_range", field, f"Value must be between {minimum} and {maximum}")
    return float(value)


def random_value(seed: int, family_id: str, module: str, entity: str, minute: int) -> float:
    """A stateless stream: unrelated events never consume another entity's draw."""
    key = json.dumps([seed, family_id, module, entity, minute], separators=(",", ":"))
    return int.from_bytes(sha256(key.encode()).digest()[:8], "big") / 2**64


def _random(state: dict, module: str, entity: str, minute: int | None = None) -> float:
    return random_value(state["seed"], state["familyId"], module, entity,
                        state["simMinute"] if minute is None else minute)


def _event(state: dict, kind: str, payload: dict, *, district: str | None = None,
           actor: str | None = None, causes: list[str] | None = None) -> str:
    seq = len(state["events"]) + 1
    event_id = f"event-{seq:09d}"
    state["events"].append({
        "id": event_id, "seq": seq, "simMinute": state["simMinute"], "type": kind,
        "actorId": actor, "districtId": district, "causedBy": list(causes or []),
        "payloadSchemaVersion": "1.0", "payload": payload,
    })
    return event_id


def _metric(state: dict, metric_id: str, value: float, unit: str,
            district: str | None = None, sources: list[str] | None = None) -> None:
    state["metrics"].append({
        "id": f"evidence-{len(state['metrics']) + 1:09d}", "metricId": metric_id,
        "metric": metric_id, "districtId": district, "value": value, "unit": unit,
        "simMinute": state["simMinute"], "status": "simulated", "sourceIds": list(sources or []),
        "aggregation": ("corridor-delay-proxy" if district else "worst-district-corridor-delay-proxy")
        if metric_id == "travel-time-p90" else "state-value",
    })


def _schedule(state: dict, minute: int, priority: int, kind: str, payload: dict | None = None) -> None:
    state["pendingEvents"].append({"simMinute": minute, "priority": priority, "type": kind,
                                   "id": f"{kind}:{minute}:{len(state['pendingEvents'])}",
                                   "payload": payload or {}})


def initial_state(snapshot: dict, seed: int, family_id: str, parameters: dict | None = None) -> dict:
    """Validate a published city payload and create an independent JSON state."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise DomainError("invalid_seed", "seed", "Seed must be an integer")
    if snapshot.get("mode") != "dynamic-v2" or snapshot.get("status") != "synthetic":
        raise DomainError("invalid_snapshot", "snapshot", "This demo accepts synthetic dynamic-v2 snapshots")
    overrides = {**snapshot.get("parameters", {}), **(parameters or {})}
    unknown = set(overrides) - set(PARAMETERS) - {"timeMode", "representativesPerGroup"}
    if unknown:
        raise DomainError("unknown_parameter", "parameters", f"Unknown parameters: {sorted(unknown)}")
    coefficients = {key: _number(overrides.get(key, value), f"parameters.{key}", low, high)
                    for key, (value, _unit, low, high) in PARAMETERS.items()}
    time_mode = overrides.get("timeMode", "operational")
    if time_mode not in ("operational", "strategic"):
        raise DomainError("invalid_time_mode", "parameters.timeMode", "Use operational or strategic")
    representatives = overrides.get("representativesPerGroup", 10)
    if isinstance(representatives, bool) or not isinstance(representatives, int) or not 1 <= representatives <= 100:
        raise DomainError("invalid_value", "representativesPerGroup", "Expected an integer from 1 to 100")
    rows = snapshot.get("districts")
    if not isinstance(rows, list) or not rows:
        raise DomainError("invalid_snapshot", "districts", "At least one district is required")
    district_ids = [row.get("id") for row in rows]
    if any(not isinstance(value, str) or not value for value in district_ids) or len(set(district_ids)) != len(rows):
        raise DomainError("invalid_snapshot", "districts.id", "District IDs must be nonempty and unique")
    finance = snapshot.get("finance", {})
    cash = _number(finance.get("cash"), "finance.cash")
    reserve = _number(finance.get("requiredReserve", 0), "finance.requiredReserve", maximum=cash)
    weather = deepcopy(snapshot.get("weather", {}))
    for key in ("snowStartMinute", "snowEndMinute"):
        minute = _number(weather.get(key), f"weather.{key}")
        if int(minute) != minute:
            raise DomainError("invalid_value", f"weather.{key}", "Weather times use whole model minutes")
    if weather["snowEndMinute"] <= weather["snowStartMinute"]:
        raise DomainError("invalid_window", "weather", "Snow must end after it starts")
    _number(weather.get("intensity"), "weather.intensity", maximum=1)
    if "snowIntensity" in overrides:
        weather["intensity"] = coefficients["snowIntensity"]
    else:
        coefficients["snowIntensity"] = float(weather["intensity"])
    state = {
        "mode": "dynamic-v2", "dataStatus": "synthetic", "modelVersion": MODEL_VERSION,
        "rngVersion": RNG_VERSION, "seed": seed, "familyId": family_id, "simMinute": 0,
        "stateVersion": 0, "timeMode": time_mode, "parameters": coefficients,
        "units": {
            "simMinute": "minute", "stateVersion": "version-counter", "month": "30-day-model-month",
            "population": "person", "agent.weight": "person", "agent.income": "KZT/month",
            "agent.satisfaction": "index-0-100", "roadCapacity": "person-trip/15min",
            "travelTimeP90": "minute-corridor-proxy", "serviceBacklog": "job",
            "serviceUnavailabilityHours": "service-hour", "schoolCapacity": "place",
            "schoolQueue": "person", "housingStock.units": "dwelling", "housingStock.price": "KZT/dwelling",
            "parcel.maxUnits": "dwelling-or-place-by-zone", "ledger": snapshot.get("currency", "KZT"),
            "politics.support": "fraction", "politics.politicalCapital": "fraction", "priceIndex": "ratio-to-base-period",
        },
        "startSimTime": snapshot.get("startSimTime", "2026-01-01T00:00:00Z"),
        "basePeriod": snapshot.get("basePeriod", "2026-01"), "month": 0, "priceIndex": 1.0,
        "districts": [], "agents": [], "crews": [], "cohorts": [], "migrationFlows": [],
        "events": [], "metrics": [], "observations": [], "pendingEvents": [],
        "projects": [], "parcels": [], "housingStock": [], "populationHistory": [],
        "transfers": [], "weather": {**weather, "activeIntensity": 0, "eventId": None},
        "ledger": {"cash": cash, "reserved": 0.0, "requiredReserve": reserve,
                   "currency": snapshot.get("currency", "KZT"), "entries": [],
                   "revenue": 0.0, "expenditure": 0.0, "debt": 0.0, "arrears": 0.0},
        "accounts": {"city": cash, "households": 0.0, "business": 0.0},
        "initialMoney": cash, "externalInflow": 0.0, "externalOutflow": 0.0,
        "politics": {"synthetic": True, "status": "hypothesis", "politicalCapital": 0.5,
                     "groups": [], "votes": [], "hearings": [], "promises": [],
                     "salience": {"transport": 0.0, "schools": 0.0, "housing": 0.0},
                     "temporaryFunding": False},
        "parameterRegistry": [
            {"id": key, "value": coefficients[key], "unit": unit, "range": [low, high],
             "source": "assumption", "status": "assumed", "version": MODEL_VERSION}
            for key, (_default, unit, low, high) in PARAMETERS.items()
        ],
        "moduleStatuses": [
            {"id": "weather", "status": "implemented", "limitations": ["Synthetic one-window snow scenario"]},
            {"id": "population", "status": "implemented", "limitations": ["Weighted representatives; cohort means"]},
            {"id": "transport", "status": "partial", "limitations": [
                "Aggregate district corridor; no multimodal route graph",
                "travel-time-p90 is explicitly a corridor-delay proxy, not a sampled trip percentile",
            ]},
            {"id": "services", "status": "partial", "limitations": ["Snow crews and physical backlog; no waste routing or utility network"]},
            {"id": "appeals", "status": "implemented", "limitations": ["Synthetic experience-backed observations, not public opinion"]},
            {"id": "schools", "status": "partial", "limitations": ["Capacity and staffing; clinics not implemented"]},
            {"id": "demography", "status": "partial", "limitations": ["Three age cohorts; assumed rates, no calibration"]},
            {"id": "development", "status": "partial", "limitations": ["Synthetic parcel units; no cadastral geometry or demolition"]},
            {"id": "finances", "status": "partial", "limitations": ["Three-sector conserved flows; no borrowing or real municipal tax rules"]},
            {"id": "politics", "status": "partial", "limitations": [
                "Synthetic votes and zoning hearings; no real actors or election forecasts",
                "Budget votes record approval/temporary-funding status; annual appropriation enforcement and project hearing gates are not implemented",
            ]},
            {"id": "greenery", "status": "not-implemented", "limitations": []},
            {"id": "safety", "status": "not-implemented", "limitations": []},
            {"id": "calibration", "status": "not-implemented", "limitations": []},
            {"id": "parameter-registry", "status": "partial", "limitations": [
                "Configurable coefficients have units/ranges; fixed cohort shares and remaining constants are versioned model assumptions, not calibrated estimates",
            ]},
        ],
    }
    for row in sorted(rows, key=lambda item: item["id"]):
        district = deepcopy(row)
        for field in ("population", "roadCapacity", "travelMinutes", "schoolCapacity", "housingUnits", "housingPrice"):
            district[field] = _number(row.get(field), f"districts.{row['id']}.{field}")
        crew_count = row.get("crews", 0)
        if isinstance(crew_count, bool) or not isinstance(crew_count, int) or not 0 <= crew_count <= 1000:
            raise DomainError("invalid_value", "districts.crews", "Crew count must be an integer from 0 to 1000")
        district.update({"serviceBacklog": 0.0, "serviceUnavailabilityHours": 0.0,
                         "travelTimeP90": district["travelMinutes"], "tripDemand": 0.0,
                         "tripsServed": 0.0, "unmetTrips": 0.0, "jobArrivals": 0.0,
                         "jobsCompleted": 0.0, "schoolQueue": 0.0, "schoolStaffCapacity": district["schoolCapacity"],
                         "schoolFundedCapacity": district["schoolCapacity"], "moratoriumUntil": 0,
                         "developerSchoolRequirement": 0.0, "populationInitial": district["population"]})
        state["districts"].append(district)
        for age, fraction, income in (("children", 0.22, 0), ("adults", 0.63, 250000), ("seniors", 0.15, 120000)):
            for sex in ("female", "male"):
                state["cohorts"].append({"districtId": row["id"], "ageGroup": age, "sex": sex,
                                         "population": district["population"] * fraction / 2, "unit": "person"})
            for index in range(representatives):
                state["agents"].append({"id": f"resident-{row['id']}-{age}-{index:03d}",
                                        "districtId": row["id"], "ageGroup": age,
                                        "weight": district["population"] * fraction / representatives,
                                        "income": income, "incomeUnit": "KZT/month", "satisfaction": 70.0,
                                        "memory": [], "lastExperienceEventId": None})
        for index in range(crew_count):
            state["crews"].append({"id": f"crew-{row['id']}-{index + 1}", "districtId": row["id"],
                                   "skills": ["snow", "repair"], "available": True, "assignmentUntil": None})
        state["housingStock"].append({"districtId": row["id"], "units": district["housingUnits"],
                                      "vacant": max(0, district["housingUnits"] - district["population"] / coefficients["householdSize"]),
                                      "price": district["housingPrice"], "unit": "dwelling", "priceUnit": "KZT/dwelling"})
        for index in range(4):
            state["parcels"].append({"id": f"parcel-{row['id']}-{index + 1}", "districtId": row["id"],
                                     "zone": "residential" if index < 3 else "social", "maxUnits": 50.0,
                                     "status": "available", "builtUnits": 0.0})
        state["politics"]["groups"].append({"id": f"families-{row['id']}", "districtId": row["id"],
                                            "name": "Синтетические семьи", "support": 0.6})
    _schedule(state, int(weather["snowStartMinute"]), 0, "weather.start")
    _schedule(state, int(weather["snowEndMinute"]), 0, "weather.end")
    _schedule(state, 15 if time_mode == "operational" else 1440, 10, "operational.tick")
    _schedule(state, MONTH_MINUTES, 20, "strategic.tick")
    created = _event(state, "city.initialized", {"population": sum(d["population"] for d in state["districts"]),
                                                 "dataStatus": "synthetic", "timeMode": time_mode})
    _record_metrics(state, [created])
    return state


def _district(state: dict, district_id: str) -> dict:
    for district in state["districts"]:
        if district["id"] == district_id:
            return district
    raise DomainError("unknown_district", "payload.districtId", "Unknown district")


def _available(state: dict) -> float:
    ledger = state["ledger"]
    return max(0, ledger["cash"] - ledger["reserved"] - ledger["requiredReserve"])


def _transfer(state: dict, source: str, target: str, amount: float, kind: str,
              reference: str | None = None, spend_reserved: bool = False) -> float:
    """Cash transfers conserve the three internal sector accounts exactly."""
    amount = max(0.0, float(amount))
    if source == "city" and not spend_reserved:
        amount = min(amount, _available(state))
    elif source != "external":
        amount = min(amount, state["accounts"][source])
    if amount <= 0:
        return 0.0
    if source == "external":
        state["externalInflow"] += amount
    else:
        state["accounts"][source] -= amount
    if target == "external":
        state["externalOutflow"] += amount
    else:
        state["accounts"][target] += amount
    ledger = state["ledger"]
    ledger["cash"] = state["accounts"]["city"]
    if source == "city":
        ledger["expenditure"] += amount
    if target == "city":
        ledger["revenue"] += amount
    entry = {"id": f"transfer-{len(state['transfers']) + 1:09d}", "simMinute": state["simMinute"],
             "from": source, "to": target, "amount": amount, "currency": ledger["currency"],
             "kind": kind, "referenceId": reference}
    state["transfers"].append(entry)
    if source == "city" or target == "city":
        ledger["entries"].append(deepcopy(entry))
    return amount


def _reserve(state: dict, amount: float, reference: str) -> None:
    if amount > _available(state) + 1e-7:
        raise DomainError("budget_insufficient", "payload.capex", "Insufficient uncommitted cash after required reserve")
    state["ledger"]["reserved"] += amount
    state["ledger"]["entries"].append({"kind": "reserve", "amount": amount,
                                        "simMinute": state["simMinute"], "referenceId": reference,
                                        "currency": state["ledger"]["currency"]})


def _record_metrics(state: dict, causes: list[str]) -> None:
    for district in state["districts"]:
        for metric_id, key, unit in (
            ("travel-time-p90", "travelTimeP90", "minute"), ("backlog", "serviceBacklog", "job"),
            ("service-unavailability-hours", "serviceUnavailabilityHours", "service-hour"),
            ("population", "population", "person"), ("school-queue", "schoolQueue", "person"),
            ("unmet-trips", "unmetTrips", "person-trip"),
        ):
            _metric(state, metric_id, district[key], unit, district["id"], causes)
    _metric(state, "service-unavailability-hours", sum(d["serviceUnavailabilityHours"] for d in state["districts"]),
            "service-hour", sources=causes)
    _metric(state, "backlog", sum(d["serviceBacklog"] for d in state["districts"]), "job", sources=causes)
    _metric(state, "travel-time-p90", max(d["travelTimeP90"] for d in state["districts"]),
            "minute", sources=causes)
    _metric(state, "population", sum(d["population"] for d in state["districts"]), "person", sources=causes)
    _metric(state, "expenditure", state["ledger"]["expenditure"], state["ledger"]["currency"], sources=causes)
    _metric(state, "cash", state["ledger"]["cash"], state["ledger"]["currency"], sources=causes)
    _metric(state, "available-to-commit", _available(state), state["ledger"]["currency"], sources=causes)


def _operational(state: dict) -> None:
    params, weather = state["parameters"], state["weather"]
    intensity = weather["activeIntensity"]
    period = 15 if state["timeMode"] == "operational" else 1440
    scale = period / 15
    causes = [weather["eventId"]] if weather["eventId"] else []
    total_cost = sum(crew["available"] for crew in state["crews"]) * params["crewCost"] * scale
    paid = _transfer(state, "city", "households", total_cost, "crew-opex")
    funding_fraction = paid / total_cost if total_cost else 1.0
    state["ledger"]["arrears"] += total_cost - paid
    all_causes = []
    for district in state["districts"]:
        district_id = district["id"]
        capacity = district["roadCapacity"] * (1 - params["snowCapacityLoss"] * intensity)
        capacity /= 1 + params["backlogCapacityLoss"] * district["serviceBacklog"]
        # Trips are divisible representative flows, not a weight-100 person in a seat.
        demand = district["population"] * params["tripRate"] * scale
        served = min(demand, capacity * scale)
        district.update({"tripDemand": demand, "tripsServed": served, "unmetTrips": demand - served})
        ratio = demand / (capacity * scale) if capacity > 0 else 0
        travel = district["travelMinutes"] * (1 + params["congestionAlpha"] * min(ratio, 10) ** params["congestionPower"])
        # A closed corridor never completes trips; finite delay is an observation window, not teleportation.
        district["travelTimeP90"] = travel if served > 0 else float(period)
        capacity_event = _event(state, "transport.capacity", {"capacity": capacity, "unit": "person-trip/15min",
                                                               "snowIntensity": intensity}, district=district_id, causes=causes)
        experience = _event(state, "transport.experience", {
            "demand": demand, "served": served, "unmet": demand - served, "tripUnit": "person-trip",
            "travelTimeP90": district["travelTimeP90"], "unit": "minute", "routeAvailable": capacity > 0,
        }, district=district_id, causes=[capacity_event])
        crew_count = sum(c["districtId"] == district_id and c["available"] for c in state["crews"])
        arrivals = (district["population"] / 100 * params["snowJobRate"] * intensity *
                    (1 + (190 - min(190, district["roadCapacity"])) / 80) *
                    (0.8 + 0.4 * _random(state, "snow-jobs", district_id)) * scale)
        before = district["serviceBacklog"]
        completed = min(before + arrivals, crew_count * params["crewProductivity"] *
                        (1 - params["crewSnowLoss"] * intensity) * scale * funding_fraction)
        district["serviceBacklog"] = max(0.0, before + arrivals - completed)
        district["jobArrivals"] += arrivals
        district["jobsCompleted"] += completed
        district["serviceUnavailabilityHours"] += min(district["population"] / 100,
                                                       district["serviceBacklog"]) * period / 60
        queue_event = _event(state, "service.queue", {"before": before, "arrivals": arrivals,
                                                       "completed": completed, "after": district["serviceBacklog"],
                                                       "unit": "job", "fundingFraction": funding_fraction},
                             district=district_id, causes=[experience, *causes])
        all_causes.append(queue_event)
        severity = min(1.0, max(0.0, (district["travelTimeP90"] - district["travelMinutes"]) / 60)
                       + (district["unmetTrips"] / demand if demand else 0))
        for agent in (a for a in state["agents"] if a["districtId"] == district_id):
            agent["lastExperienceEventId"] = experience
            agent["memory"] = (agent["memory"] + [experience])[-24:]
            agent["satisfaction"] = max(0.0, min(100.0, 0.95 * agent["satisfaction"] + 0.05 * (100 - 80 * severity)))
            previous = next((appeal for appeal in reversed(state["observations"])
                             if appeal["actorId"] == agent["id"] and appeal["status"] == "assigned"), None)
            if previous is not None:
                if district["serviceBacklog"] <= 1e-8 and severity < 0.1:
                    previous["status"] = "resolved"
                    previous["resolvedMinute"] = state["simMinute"]
                    _event(state, "appeal.resolved", {"appealId": previous["id"], "physicalBacklog": 0},
                           district=district_id, actor=agent["id"], causes=[queue_event, previous["eventId"]])
                continue
            if severity > 0.05 and _random(state, "appeal", agent["id"]) < params["appealPropensity"] * severity:
                appeal_id = f"synthetic-appeal-{len(state['observations']) + 1}"
                event_id = _event(state, "appeal.created", {"appealId": appeal_id, "topic": "transport-delay",
                                                            "experienceEventId": experience, "severity": severity},
                                  district=district_id, actor=agent["id"], causes=[experience, queue_event])
                state["observations"].append({"id": appeal_id, "type": "appeal", "namespace": "synthetic",
                                               "simMinute": state["simMinute"], "districtId": district_id,
                                               "actorId": agent["id"], "experienceEventId": experience,
                                               "eventId": event_id, "status": "assigned", "topic": "transport-delay",
                                               "confidence": 1.0, "source": "simulated-experience"})
    _record_metrics(state, all_causes)


def advance(state: dict, minutes: int) -> None:
    """Advance exactly `minutes`; fixed scheduler boundaries make chunking invariant."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise DomainError("invalid_step", "minutes", "Step must be a nonnegative whole number of minutes")
    target = state["simMinute"] + minutes
    while state["pendingEvents"]:
        scheduled = min(state["pendingEvents"], key=lambda item: (item["simMinute"], item["priority"], item["id"]))
        if scheduled["simMinute"] > target:
            break
        state["pendingEvents"].remove(scheduled)
        state["simMinute"] = scheduled["simMinute"]
        kind = scheduled["type"]
        if kind in ("weather.start", "weather.end"):
            state["weather"]["activeIntensity"] = state["weather"]["intensity"] if kind.endswith("start") else 0
            state["weather"]["eventId"] = _event(state, kind, {"intensity": state["weather"]["activeIntensity"],
                                                                "unit": "fraction"})
        elif kind == "operational.tick":
            _operational(state)
            _schedule(state, state["simMinute"] + (15 if state["timeMode"] == "operational" else 1440), 10, kind)
        elif kind == "strategic.tick":
            _strategic(state)
            _schedule(state, state["simMinute"] + MONTH_MINUTES, 20, kind)
        elif kind == "crew.restore":
            crew = next(c for c in state["crews"] if c["id"] == scheduled["payload"]["crewId"])
            # A subsequent explicit reassignment supersedes a prior return order.
            if crew.get("assignmentId") == scheduled["payload"]["assignmentId"]:
                crew["districtId"] = scheduled["payload"]["districtId"]
                crew["assignmentUntil"] = None
                _event(state, "crew.returned", scheduled["payload"], actor=crew["id"])
        elif kind == "decision.apply":
            _execute_decision(state, scheduled["payload"], scheduled=True)
        state["stateVersion"] += 1
    state["simMinute"] = target


def _strategic(state: dict) -> None:
    """Monthly stock/flow model; every balance has an explicit accounting identity."""
    state["month"] += 1
    params = state["parameters"]
    state["priceIndex"] *= 1 + params["monthlyInflation"]
    _complete_projects(state)
    _demography(state)
    _development(state)
    _monthly_finance(state)
    _politics(state)
    for district in state["districts"]:
        children = sum(c["population"] for c in state["cohorts"]
                       if c["districtId"] == district["id"] and c["ageGroup"] == "children")
        capacity = min(district["schoolCapacity"], district["schoolStaffCapacity"], district["schoolFundedCapacity"])
        district["schoolQueue"] = max(0.0, children - capacity)
    event_id = _event(state, "month.closed", {"month": state["month"], "cash": state["ledger"]["cash"],
                                               "priceIndex": state["priceIndex"], "currency": state["ledger"]["currency"]})
    _record_metrics(state, [event_id])


def _demography(state: dict) -> None:
    params = state["parameters"]
    # Attraction reflects real modeled service outcomes and affordability; no manual policy penalty.
    attractiveness = {}
    for district in state["districts"]:
        stock = next(h for h in state["housingStock"] if h["districtId"] == district["id"])
        price_income = stock["price"] / max(1, params["monthlyWage"] * 12)
        school_coverage = max(0.0, 1 - district["schoolQueue"] / max(1, district["population"] * 0.22))
        attractiveness[district["id"]] = school_coverage - price_income / 20 - district["travelTimeP90"] / 120
    exp_weights = {key: math.exp(max(-20, min(20, value))) for key, value in attractiveness.items()}
    denominator = sum(exp_weights.values())
    histories = {}
    for district in state["districts"]:
        district_id = district["id"]
        cohorts = [c for c in state["cohorts"] if c["districtId"] == district_id]
        before = sum(c["population"] for c in cohorts)
        births = before * params["monthlyBirthRate"]
        deaths = before * params["monthlyDeathRate"]
        # Cohort mortality is bounded; births/deaths use rates per month (not per tick).
        for cohort in cohorts:
            cohort["population"] *= 1 - params["monthlyDeathRate"]
            if cohort["ageGroup"] == "children":
                cohort["population"] += births / 2
        for sex in ("female", "male"):
            by_age = {c["ageGroup"]: c for c in cohorts if c["sex"] == sex}
            to_adult = by_age["children"]["population"] / (18 * 12)
            to_senior = by_age["adults"]["population"] / (47 * 12)
            by_age["children"]["population"] -= to_adult
            by_age["adults"]["population"] += to_adult - to_senior
            by_age["seniors"]["population"] += to_senior
        outgoing = (before + births - deaths) * params["monthlyOutRate"] / (1 + math.exp(attractiveness[district_id]))
        stock = next(h for h in state["housingStock"] if h["districtId"] == district_id)
        room = max(0.0, stock["units"] * params["householdSize"] - (before + births - deaths - outgoing))
        incoming = min(room, params["externalInflow"] * exp_weights[district_id] / denominator *
                       (0.85 + 0.30 * _random(state, "migration", district_id)))
        self_total = sum(c["population"] for c in cohorts)
        for cohort in cohorts:
            cohort["population"] *= (self_total - outgoing) / self_total if self_total else 0
            fraction = {"children": 0.30, "adults": 0.65, "seniors": 0.05}[cohort["ageGroup"]]
            cohort["population"] += incoming * fraction / 2
        for source, target, amount in (("outside-city", district_id, incoming), (district_id, "outside-city", outgoing)):
            if amount:
                state["migrationFlows"].append({"simMinute": state["simMinute"], "from": source, "to": target,
                                                "population": amount, "unit": "person", "group": "mixed-cohort",
                                                "factors": {"attractiveness": attractiveness[district_id],
                                                            "housingCapacity": room}})
        histories[district_id] = {"simMinute": state["simMinute"], "districtId": district_id,
                                  "before": before, "births": births, "deaths": deaths,
                                  "in": incoming, "out": outgoing, "unit": "person"}
    # Internal relocation is a conserved transfer and requires vacant housing at destination.
    ranked = sorted(state["districts"], key=lambda d: (attractiveness[d["id"]], d["id"]))
    if len(ranked) > 1:
        source, target = ranked[0]["id"], ranked[-1]["id"]
        source_cohorts = [c for c in state["cohorts"] if c["districtId"] == source]
        target_cohorts = [c for c in state["cohorts"] if c["districtId"] == target]
        target_stock = next(h for h in state["housingStock"] if h["districtId"] == target)
        room = max(0.0, target_stock["units"] * params["householdSize"] - sum(c["population"] for c in target_cohorts))
        source_total = sum(c["population"] for c in source_cohorts)
        moving = min(room, source_total * params["internalMoveRate"] * max(0, attractiveness[target] - attractiveness[source]))
        for cohort in source_cohorts:
            amount = moving * cohort["population"] / source_total if source_total else 0
            cohort["population"] -= amount
            next(c for c in target_cohorts if c["ageGroup"] == cohort["ageGroup"] and c["sex"] == cohort["sex"])["population"] += amount
        histories[source]["out"] += moving
        histories[target]["in"] += moving
        if moving:
            state["migrationFlows"].append({"simMinute": state["simMinute"], "from": source, "to": target,
                                            "population": moving, "unit": "person", "group": "mixed-cohort",
                                            "factors": {"attractivenessDifference": attractiveness[target] - attractiveness[source]}})
    for district in state["districts"]:
        district["population"] = sum(c["population"] for c in state["cohorts"] if c["districtId"] == district["id"])
        history = histories[district["id"]]
        history["after"] = district["population"]
        state["populationHistory"].append(history)
        for age in ("children", "adults", "seniors"):
            representatives = [a for a in state["agents"] if a["districtId"] == district["id"] and a["ageGroup"] == age]
            total = sum(c["population"] for c in state["cohorts"] if c["districtId"] == district["id"] and c["ageGroup"] == age)
            for agent in representatives:
                agent["weight"] = total / len(representatives)
        _event(state, "population.changed", history, district=district["id"])


def _development(state: dict) -> None:
    params = state["parameters"]
    for district in state["districts"]:
        stock = next(h for h in state["housingStock"] if h["districtId"] == district["id"])
        households = district["population"] / params["householdSize"]
        stock["vacant"] = max(0.0, stock["units"] - households)
        last_history = next(h for h in reversed(state["populationHistory"]) if h["districtId"] == district["id"])
        demand = max(0, (last_history["in"] - last_history["out"] + last_history["births"] - last_history["deaths"]) /
                     params["householdSize"] + households * 0.005)
        # Scarcity changes price; a moratorium acts only by preventing new starts.
        pressure = (demand - stock["vacant"]) / max(1.0, stock["vacant"])
        stock["price"] *= max(0.5, 1 + params["priceElasticity"] * max(-1, min(5, pressure)))
        _metric(state, "housing-price", stock["price"], "KZT/dwelling", district["id"])
        if demand <= 0 or district["moratoriumUntil"] > state["simMinute"]:
            continue
        parcel = next((p for p in state["parcels"] if p["districtId"] == district["id"]
                       and p["zone"] == "residential" and p["status"] == "available"), None)
        if parcel is None or stock["vacant"] > max(20, demand * 6):
            continue
        unit_cost = params["constructionCost"] * state["priceIndex"]
        margin = (stock["price"] - unit_cost) / unit_cost
        probability = 1 / (1 + math.exp(-max(-20, min(20, 5 * margin))))
        if _random(state, "development", parcel["id"]) >= probability:
            continue
        units = min(parcel["maxUnits"], max(1.0, demand * 3))
        project_id = f"development-{parcel['id']}-{state['month']}"
        # Outside investment is explicit, not free construction or a city-budget deduction.
        cost = units * unit_cost
        _transfer(state, "external", "business", cost, "private-investment", project_id)
        _transfer(state, "business", "external", cost, "construction-inputs", project_id)
        project = {"id": project_id, "districtId": district["id"], "parcelId": parcel["id"], "type": "housing",
                   "status": "construction", "startMinute": state["simMinute"],
                   "completeMinute": state["simMinute"] + int(params["constructionMonths"] * MONTH_MINUTES),
                   "capex": cost, "opexMonthly": units * 1000, "capacity": units, "funding": "private",
                   "schoolRequirement": district["developerSchoolRequirement"] * units, "staff": True}
        state["projects"].append(project)
        parcel["status"] = "construction"
        _event(state, "development.started", deepcopy(project), district=district["id"])


def _complete_projects(state: dict) -> None:
    for project in state["projects"]:
        if project["status"] != "construction" or project["completeMinute"] > state["simMinute"]:
            continue
        if not project.get("staff", True) and project["type"] == "school":
            project["status"] = "awaiting-staff"
            _event(state, "project.delayed", {"projectId": project["id"], "reason": "staff_unavailable"},
                   district=project["districtId"])
            continue
        project["status"] = "operating"
        district = _district(state, project["districtId"])
        if project["type"] == "housing":
            stock = next(h for h in state["housingStock"] if h["districtId"] == project["districtId"])
            stock["units"] += project["capacity"]
            district["schoolCapacity"] += project.get("schoolRequirement", 0)
            district["schoolStaffCapacity"] += project.get("schoolRequirement", 0)
            district["schoolFundedCapacity"] += project.get("schoolRequirement", 0)
        elif project["type"] == "school":
            for key in ("schoolCapacity", "schoolStaffCapacity", "schoolFundedCapacity"):
                district[key] += project["capacity"]
        elif project["type"] == "road":
            district["roadCapacity"] += project["capacity"]
        if project.get("parcelId"):
            parcel = next(p for p in state["parcels"] if p["id"] == project["parcelId"])
            parcel["status"] = "built"
            parcel["builtUnits"] += project["capacity"]
        _event(state, "project.commissioned", {"projectId": project["id"], "capacity": project["capacity"],
                                               "type": project["type"]}, district=project["districtId"])


def _monthly_finance(state: dict) -> None:
    params = state["parameters"]
    population = sum(d["population"] for d in state["districts"])
    adults = sum(c["population"] for c in state["cohorts"] if c["ageGroup"] == "adults")
    wages = adults * params["employmentRate"] * params["monthlyWage"] * state["priceIndex"]
    # An exogenous export/investment flow finances business payroll; every boundary is recorded.
    _transfer(state, "external", "business", wages, "export-revenue")
    _transfer(state, "business", "households", wages, "wages")
    _transfer(state, "households", "city", wages * params["incomeTaxRate"], "income-tax")
    housing_value = sum(h["units"] * h["price"] for h in state["housingStock"])
    _transfer(state, "households", "city", housing_value * params["propertyTaxRate"], "property-tax")
    _transfer(state, "households", "business", wages * 0.6, "consumption")
    _transfer(state, "business", "external", wages * 0.3, "imports")
    _transfer(state, "external", "city", params["monthlyTransfer"], "intergovernmental-transfer")
    project_opex = sum(p["opexMonthly"] for p in state["projects"] if p["status"] == "operating")
    required_opex = (population * params["serviceCostPerPerson"] + project_opex) * state["priceIndex"]
    paid = _transfer(state, "city", "business", required_opex, "service-opex")
    state["ledger"]["arrears"] += required_opex - paid
    coverage = paid / required_opex if required_opex else 1
    for district in state["districts"]:
        district["schoolFundedCapacity"] = district["schoolCapacity"] * coverage
    _metric(state, "real-opex", paid / state["priceIndex"], f"{state['ledger']['currency']}/{state['basePeriod']}")
    _metric(state, "nominal-opex", paid, state["ledger"]["currency"])
    _metric(state, "money-balance-error", sum(state["accounts"].values()) - state["initialMoney"] -
            state["externalInflow"] + state["externalOutflow"], state["ledger"]["currency"])


def _politics(state: dict) -> None:
    politics, params = state["politics"], state["parameters"]
    for group in politics["groups"]:
        district = _district(state, group["districtId"])
        experience = sum(a["satisfaction"] * a["weight"] for a in state["agents"] if a["districtId"] == district["id"])
        utility = experience / max(1, district["population"]) / 100
        utility *= max(0, 1 - district["schoolQueue"] / max(1, district["population"] * 0.22))
        inertia = params["supportInertia"]
        group["support"] = min(1, max(0, (1 - inertia) * group["support"] + inertia * utility))
    politics["salience"]["schools"] = sum(d["schoolQueue"] for d in state["districts"])
    politics["salience"]["transport"] = sum(a["status"] == "assigned" for a in state["observations"])
    for promise in politics["promises"]:
        if promise["status"] != "pending" or promise["deadlineMinute"] > state["simMinute"]:
            continue
        value = next((m["value"] for m in reversed(state["metrics"])
                      if m["metricId"] == promise["metricId"] and m["districtId"] == promise.get("districtId")), None)
        if value is None:
            promise["status"] = "unverifiable"
        else:
            fulfilled = value <= promise["target"] if promise["direction"] == "at-most" else value >= promise["target"]
            promise["status"] = "fulfilled" if fulfilled else "broken"
            promise["actualValue"] = value
            politics["politicalCapital"] = max(0, min(1, politics["politicalCapital"] + (0.05 if fulfilled else -0.1)))
        _event(state, "promise.reviewed", deepcopy(promise))


def apply_decision(state: dict, command: dict) -> dict:
    """Validate a management command before mutation; application owns idempotency."""
    # Transactional copy keeps rejected decisions from leaving partial reserves or events.
    candidate = deepcopy(state)
    result = _execute_decision(candidate, command)
    candidate["stateVersion"] += 1
    state.clear()
    state.update(candidate)
    return result


def _execute_decision(state: dict, command: dict, scheduled: bool = False) -> dict:
    kind, payload = command.get("type"), command.get("payload", {})
    if not isinstance(payload, dict):
        raise DomainError("invalid_payload", "payload", "Expected an object")
    command_id = command.get("commandId", f"decision-{len(state['events']) + 1}")
    start = payload.get("startMinute", state["simMinute"])
    if isinstance(start, bool) or not isinstance(start, int) or start < state["simMinute"]:
        raise DomainError("invalid_start_time", "payload.startMinute", "Start must not precede current model time")
    if start > state["simMinute"] and not scheduled:
        # Scheduling resource commitments requires immediate validation/reservation. The first
        # slice accepts dated crew assignments only; capital projects start after approval.
        if kind != "crew.reassign":
            raise DomainError("unsupported_schedule", "payload.startMinute", "Only crew assignments accept future starts")
        _validate_crew(state, payload)
        cost = state["parameters"]["reassignmentCost"]
        _reserve(state, cost, command_id)
        saved = deepcopy(command)
        saved["payload"]["reservedCost"] = cost
        _schedule(state, start, 5, "decision.apply", saved)
        event_id = _event(state, "decision.scheduled", {"commandId": command_id, "type": kind, "startMinute": start})
        return {"accepted": True, "eventId": event_id, "scheduledMinute": start}
    if kind == "crew.reassign":
        crew, district = _validate_crew(state, payload)
        cost = state["parameters"]["reassignmentCost"]
        reserved = payload.get("reservedCost", 0) if scheduled else 0
        if reserved:
            state["ledger"]["reserved"] -= reserved
            state["ledger"]["entries"].append({"kind": "release", "amount": reserved,
                                                "simMinute": state["simMinute"], "referenceId": command_id})
        if cost > _available(state):
            raise DomainError("budget_insufficient", "payload.crewId", "Reassignment cost exceeds available funds")
        origin = crew["districtId"]
        _transfer(state, "city", "business", cost, "crew-reassignment", command_id)
        crew["districtId"] = district["id"]
        crew["assignmentId"] = command_id
        duration = payload.get("durationMinutes", 360)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise DomainError("invalid_duration", "payload.durationMinutes", "Expected positive whole minutes")
        crew["assignmentUntil"] = state["simMinute"] + duration
        _schedule(state, crew["assignmentUntil"], 5, "crew.restore",
                  {"crewId": crew["id"], "districtId": origin, "assignmentId": command_id})
        details = {"crewId": crew["id"], "fromDistrictId": origin, "districtId": district["id"],
                   "untilMinute": crew["assignmentUntil"], "cost": cost}
    elif kind == "project.start":
        details = _start_project(state, payload, command_id)
    elif kind == "development.moratorium":
        district = _district(state, payload.get("districtId"))
        duration = int(_number(payload.get("durationMinutes", MONTH_MINUTES * 12), "payload.durationMinutes", 1))
        if not payload.get("reason"):
            raise DomainError("missing_reason", "payload.reason", "A moratorium requires a public reason")
        district["moratoriumUntil"] = state["simMinute"] + duration
        details = {"districtId": district["id"], "untilMinute": district["moratoriumUntil"], "reason": payload["reason"]}
    elif kind == "developer.requirement":
        district = _district(state, payload.get("districtId"))
        value = _number(payload.get("schoolPlacesPerUnit"), "payload.schoolPlacesPerUnit", maximum=3)
        district["developerSchoolRequirement"] = value
        details = {"districtId": district["id"], "schoolPlacesPerUnit": value, "appliesTo": "new-starts"}
    elif kind in ("budget.submit", "budget.amend", "zoning.change"):
        details = _vote(state, payload, kind, command_id)
    elif kind == "land.allocate":
        parcel = next((p for p in state["parcels"] if p["id"] == payload.get("parcelId")), None)
        if parcel is None or parcel["status"] != "available":
            raise DomainError("resource_unavailable", "payload.parcelId", "Parcel is unavailable")
        use = payload.get("use")
        if use not in ("school", "housing") or (use == "housing" and parcel["zone"] != "residential"):
            raise DomainError("invalid_zoning", "payload.use", "Requested use is incompatible with zoning")
        parcel["allocatedUse"] = use
        details = deepcopy(parcel)
    elif kind == "hearing.schedule":
        target = payload.get("subjectId") or payload.get("parcelId")
        if not isinstance(target, str) or not target:
            raise DomainError("invalid_subject", "payload.subjectId", "Hearing must reference a subject")
        hearing = {"id": f"hearing-{len(state['politics']['hearings']) + 1}", "subjectId": target,
                   "scheduledMinute": state["simMinute"] + int(_number(payload.get("delayMinutes", 1440), "payload.delayMinutes", 1)),
                   "status": "scheduled", "synthetic": True}
        state["politics"]["hearings"].append(hearing)
        details = hearing
    elif kind == "promise.announce":
        metric_id = payload.get("metricId")
        if metric_id not in {m["metricId"] for m in state["metrics"]}:
            raise DomainError("unknown_metric", "payload.metricId", "Promise metric must already exist")
        deadline = int(_number(payload.get("deadlineMinute"), "payload.deadlineMinute", state["simMinute"] + 1))
        direction = payload.get("direction", "at-most")
        if direction not in ("at-most", "at-least"):
            raise DomainError("invalid_direction", "payload.direction", "Use at-most or at-least")
        promise = {"id": f"promise-{len(state['politics']['promises']) + 1}", "metricId": metric_id,
                   "target": _number(payload.get("target"), "payload.target"), "deadlineMinute": deadline,
                   "direction": direction, "districtId": payload.get("districtId"), "status": "pending"}
        state["politics"]["promises"].append(promise)
        details = promise
    else:
        raise DomainError("unsupported_command", "type", f"Command {kind!r} is not implemented in this demo")
    event_id = _event(state, "decision.applied", {"commandId": command_id, "type": kind, **details},
                      district=payload.get("districtId"))
    return {"accepted": True, "eventId": event_id, "result": details}


def _validate_crew(state: dict, payload: dict) -> tuple[dict, dict]:
    crew = next((c for c in state["crews"] if c["id"] == payload.get("crewId")), None)
    if crew is None or not crew["available"] or "snow" not in crew["skills"]:
        raise DomainError("resource_unavailable", "payload.crewId", "An available snow-qualified crew is required")
    if crew.get("assignmentUntil") is not None and crew["assignmentUntil"] > state["simMinute"]:
        raise DomainError("resource_unavailable", "payload.crewId", "Crew is already committed until its return time")
    if any(e["type"] == "decision.apply" and e["payload"].get("payload", {}).get("crewId") == crew["id"]
           for e in state["pendingEvents"]):
        raise DomainError("resource_unavailable", "payload.crewId", "Crew already has a future commitment")
    duration = payload.get("durationMinutes", 360)
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise DomainError("invalid_duration", "payload.durationMinutes", "Expected positive whole minutes")
    district = _district(state, payload.get("districtId"))
    if district["id"] == crew["districtId"]:
        raise DomainError("invalid_assignment", "payload.districtId", "Crew is already assigned to this district")
    return crew, district


def _start_project(state: dict, payload: dict, command_id: str) -> dict:
    district = _district(state, payload.get("districtId"))
    kind = payload.get("projectType", payload.get("type", "school"))
    if kind not in ("school", "road"):
        raise DomainError("unsupported_project", "payload.projectType", "Public demo projects: school or road")
    if not isinstance(payload.get("staff", True), bool):
        raise DomainError("invalid_value", "payload.staff", "Staff availability must be a boolean")
    capex = _number(payload.get("capex"), "payload.capex", 1)
    opex = _number(payload.get("opexMonthly"), "payload.opexMonthly", 1)
    capacity = _number(payload.get("capacity"), "payload.capacity", 1)
    duration = int(_number(payload.get("durationMonths", 6), "payload.durationMonths", 1, 120))
    parcel = None
    if kind == "school":
        parcel = next((p for p in state["parcels"] if p["id"] == payload.get("parcelId") and
                       p["districtId"] == district["id"] and p["zone"] == "social" and p["status"] == "available"), None)
        if parcel is None:
            raise DomainError("resource_unavailable", "payload.parcelId", "School requires an available social parcel")
        if capacity > parcel["maxUnits"]:
            raise DomainError("zoning_limit", "payload.capacity", "Capacity exceeds parcel zoning limit")
    project_id = str(payload.get("projectId") or f"project-{command_id}")
    if any(p["id"] == project_id for p in state["projects"]):
        raise DomainError("duplicate_project", "payload.projectId", "Project already exists")
    _reserve(state, capex, project_id)
    # Reserve -> release -> payment are separate ledger operations; cash changes once.
    state["ledger"]["reserved"] -= capex
    state["ledger"]["entries"].append({"kind": "release", "amount": capex,
                                        "simMinute": state["simMinute"], "referenceId": project_id})
    paid = _transfer(state, "city", "business", capex, "capex", project_id)
    project = {"id": project_id, "districtId": district["id"], "type": kind, "status": "construction",
               "startMinute": state["simMinute"], "completeMinute": state["simMinute"] + duration * MONTH_MINUTES,
               "capex": paid, "opexMonthly": opex, "capacity": capacity, "funding": "city",
               "staff": payload.get("staff", True), "parcelId": parcel["id"] if parcel else None}
    state["projects"].append(project)
    if parcel:
        parcel["status"] = "construction"
    return deepcopy(project)


def _vote(state: dict, payload: dict, kind: str, command_id: str) -> dict:
    parcel = None
    if kind == "zoning.change":
        parcel = next((p for p in state["parcels"] if p["id"] == payload.get("parcelId")), None)
        if parcel is None or parcel["status"] != "available":
            raise DomainError("resource_unavailable", "payload.parcelId", "Only available parcels may be rezoned")
        zone = payload.get("zone")
        if zone not in ("residential", "social", "protected"):
            raise DomainError("invalid_zoning", "payload.zone", "Unknown zoning class")
        max_units = _number(payload.get("maxUnits", parcel["maxUnits"]), "payload.maxUnits", maximum=10000)
        hearing = next((h for h in state["politics"]["hearings"] if h["subjectId"] == parcel["id"]
                        and h["scheduledMinute"] <= state["simMinute"]), None)
        if hearing is None:
            raise DomainError("hearing_required", "payload.parcelId", "Completed public hearing is required before zoning vote")
        hearing["status"] = "completed"
    else:
        proposed = _number(payload.get("amount"), "payload.amount")
        if proposed > _available(state):
            raise DomainError("budget_insufficient", "payload.amount", "Borrowing is disabled; proposed allocation exceeds available cash")
    votes = []
    for group in state["politics"]["groups"]:
        benefit = float(group["districtId"] == payload.get("districtId"))
        logit = -1.5 + benefit + state["parameters"]["voteSupportWeight"] * group["support"] + state["politics"]["politicalCapital"]
        probability = 1 / (1 + math.exp(-logit))
        yes = _random(state, "vote", f"{command_id}:{group['districtId']}") < probability
        votes.append({"deputyId": f"synthetic-deputy-{group['districtId']}", "districtId": group["districtId"],
                      "yes": yes, "probability": probability, "factors": {"benefit": benefit, "support": group["support"]}})
    accepted = sum(vote["yes"] for vote in votes) > len(votes) / 2
    result = {"id": f"vote-{len(state['politics']['votes']) + 1}", "subject": kind,
              "commandId": command_id, "simMinute": state["simMinute"], "passed": accepted,
              "votes": votes, "synthetic": True, "status": "model-hypothesis"}
    state["politics"]["votes"].append(result)
    if kind == "zoning.change" and accepted:
        parcel.update({"zone": zone, "maxUnits": max_units})
    elif kind in ("budget.submit", "budget.amend"):
        state["politics"]["temporaryFunding"] = not accepted
        if accepted:
            state["politics"]["approvedBudget"] = proposed
    _event(state, "vote.passed" if accepted else "vote.failed", deepcopy(result))
    return result
