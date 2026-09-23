from copy import deepcopy
import unittest

from engine.v2.domain.fixtures import build_demo_dataset
from engine.v2.domain.simulation import (
    DomainError, MONTH_MINUTES, advance, apply_decision, initial_state, random_value,
)


def city(**parameters):
    return initial_state(build_demo_dataset(), 42, "test-family", parameters)


class DomainTests(unittest.TestCase):
    def test_checkpoint_chunking_and_branch_isolation(self):
        baseline = city()
        advance(baseline, 73)
        checkpoint = deepcopy(baseline)
        advance(baseline, 287)
        branch = deepcopy(checkpoint)
        advance(branch, 100)
        advance(branch, 187)
        self.assertEqual(baseline, branch)
        branch["agents"][0]["memory"].append("only-this-branch")
        self.assertNotEqual(baseline["agents"][0]["memory"], branch["agents"][0]["memory"])

    def test_keyed_rng_not_shifted_by_unrelated_draw(self):
        expected = [random_value(42, "family", "trip", "resident-A", t) for t in range(20)]
        random_value(42, "family", "politics", "unrelated", 10)
        self.assertEqual(expected, [random_value(42, "family", "trip", "resident-A", t) for t in range(20)])
        self.assertNotEqual(expected, [random_value(43, "family", "trip", "resident-A", t) for t in range(20)])

    def test_snow_causal_chain_and_no_teleportation(self):
        state = city()
        advance(state, 180)
        by_id = {event["id"]: event for event in state["events"]}
        appeals = [e for e in state["events"] if e["type"] == "appeal.created" and e["simMinute"] >= 60]
        self.assertTrue(appeals)
        appeal = appeals[0]
        experience = by_id[appeal["payload"]["experienceEventId"]]
        self.assertEqual(experience["type"], "transport.experience")
        capacity = by_id[experience["causedBy"][0]]
        self.assertEqual(capacity["type"], "transport.capacity")
        self.assertTrue(any(by_id[c]["type"] == "weather.start" for c in capacity["causedBy"]))
        for district in state["districts"]:
            self.assertAlmostEqual(district["tripDemand"], district["tripsServed"] + district["unmetTrips"])
            self.assertAlmostEqual(district["serviceBacklog"], district["jobArrivals"] - district["jobsCompleted"])
        source = build_demo_dataset()
        source["districts"][0]["roadCapacity"] = 0
        closed = initial_state(source, 42, "family")
        advance(closed, 15)
        district = next(d for d in closed["districts"] if d["id"] == "almaty")
        self.assertEqual(district["tripsServed"], 0)
        self.assertEqual(district["unmetTrips"], district["tripDemand"])

    def test_weather_ablation_and_reassignment_change_real_backlog(self):
        baseline, intervention, dry = city(), city(), city(snowIntensity=0)
        for state in (baseline, intervention, dry):
            advance(state, 60)
        apply_decision(intervention, {"commandId": "move-crew", "type": "crew.reassign",
                                     "payload": {"crewId": "crew-almaty-1", "districtId": "nura", "durationMinutes": 360}})
        for state in (baseline, intervention, dry):
            advance(state, 300)
        nura_base = next(d for d in baseline["districts"] if d["id"] == "nura")
        nura_changed = next(d for d in intervention["districts"] if d["id"] == "nura")
        self.assertLess(nura_changed["serviceBacklog"], nura_base["serviceBacklog"])
        self.assertEqual(sum(d["serviceBacklog"] for d in dry["districts"]), 0)
        self.assertLess(sum(d["serviceUnavailabilityHours"] for d in dry["districts"]),
                        sum(d["serviceUnavailabilityHours"] for d in baseline["districts"]))

    def test_six_districts_agent_marginals_and_zero_population(self):
        state = city()
        self.assertEqual(len(state["districts"]), 6)
        for district in state["districts"]:
            agents = [a for a in state["agents"] if a["districtId"] == district["id"]]
            self.assertAlmostEqual(sum(a["weight"] for a in agents), district["population"])
            self.assertAlmostEqual(sum(a["weight"] for a in agents if a["ageGroup"] == "children"),
                                   district["population"] * 0.22)
        source = build_demo_dataset()
        for district in source["districts"]:
            district["population"] = 0
        empty = initial_state(source, 0, "empty", {"timeMode": "strategic", "externalInflow": 0})
        advance(empty, MONTH_MINUTES)
        self.assertEqual(sum(d["population"] for d in empty["districts"]), 0)
        self.assertFalse(any(t["kind"] == "income-tax" for t in empty["transfers"]))

    def test_population_and_three_sector_money_conservation(self):
        state = city(timeMode="strategic")
        advance(state, MONTH_MINUTES * 3)
        for row in state["populationHistory"]:
            self.assertAlmostEqual(row["after"], row["before"] + row["births"] - row["deaths"] + row["in"] - row["out"])
        self.assertTrue(all(c["population"] >= 0 for c in state["cohorts"]))
        self.assertAlmostEqual(sum(a["weight"] for a in state["agents"]),
                               sum(d["population"] for d in state["districts"]))
        self.assertAlmostEqual(sum(state["accounts"].values()),
                               state["initialMoney"] + state["externalInflow"] - state["externalOutflow"], places=5)
        self.assertAlmostEqual(state["ledger"]["cash"], state["initialMoney"] + state["ledger"]["revenue"] -
                               state["ledger"]["expenditure"], places=5)
        self.assertEqual(len([e for e in state["events"] if e["type"] == "month.closed"]), 3)

    def test_project_reservation_cash_once_and_delayed_capacity(self):
        state = city(timeMode="strategic")
        district = next(d for d in state["districts"] if d["id"] == "nura")
        original_capacity, cash = district["schoolCapacity"], state["ledger"]["cash"]
        command = {"commandId": "school", "type": "project.start", "payload": {
            "districtId": "nura", "projectType": "school", "parcelId": "parcel-nura-4",
            "capex": 1000000, "opexMonthly": 10000, "capacity": 40, "durationMonths": 1,
        }}
        apply_decision(state, command)
        self.assertEqual(state["ledger"]["cash"], cash - 1000000)
        self.assertEqual(state["ledger"]["reserved"], 0)
        self.assertEqual(next(d for d in state["districts"] if d["id"] == "nura")["schoolCapacity"], original_capacity)
        advance(state, MONTH_MINUTES)
        self.assertEqual(next(d for d in state["districts"] if d["id"] == "nura")["schoolCapacity"], original_capacity + 40)
        self.assertEqual(len([e for e in state["ledger"]["entries"] if e["kind"] == "capex"]), 1)

    def test_rejected_decision_is_atomic(self):
        state = city()
        previous = deepcopy(state)
        with self.assertRaises(DomainError):
            apply_decision(state, {"type": "crew.reassign", "payload": {
                "crewId": "crew-almaty-1", "districtId": "nura", "durationMinutes": -1,
            }})
        self.assertEqual(state, previous)
        with self.assertRaises(DomainError):
            apply_decision(state, {"type": "project.start", "payload": {
                "districtId": "nura", "projectType": "road", "capex": 1000000000,
                "opexMonthly": 1000, "capacity": 100,
            }})
        self.assertEqual(state, previous)

    def test_moratorium_blocks_new_starts_not_existing_projects(self):
        state = city(timeMode="strategic")
        apply_decision(state, {"commandId": "road", "type": "project.start", "payload": {
            "districtId": "nura", "projectType": "road", "capex": 1000,
            "opexMonthly": 100, "capacity": 10, "durationMonths": 1,
        }})
        apply_decision(state, {"commandId": "moratorium", "type": "development.moratorium", "payload": {
            "districtId": "nura", "durationMinutes": MONTH_MINUTES * 12, "reason": "Infrastructure capacity review",
        }})
        advance(state, MONTH_MINUTES)
        self.assertEqual(state["projects"][0]["status"], "operating")
        self.assertFalse(any(p["type"] == "housing" and p["districtId"] == "nura" for p in state["projects"]))

    def test_votes_are_reproducible_and_do_not_modify_physical_scores(self):
        left, right = city(), city()
        decision = {"commandId": "budget", "type": "budget.submit", "payload": {"amount": 1000000, "districtId": "nura"}}
        before = deepcopy(left["districts"])
        apply_decision(left, decision)
        apply_decision(right, decision)
        self.assertEqual(left["politics"], right["politics"])
        self.assertEqual(left["districts"], before)
        self.assertTrue(all(v["deputyId"].startswith("synthetic-") for v in left["politics"]["votes"][0]["votes"]))

    def test_invalid_parameters_unknowns_and_nonfinite_rejected(self):
        for values in ({"tripRate": float("nan")}, {"unregisteredCoefficient": 1}, {"snowIntensity": 2}):
            with self.assertRaises(DomainError):
                city(**values)


if __name__ == "__main__":
    unittest.main()
