import unittest
from itertools import permutations

from engine.v1 import Selection, create_official_service
from engine.v1.application.alternatives import portfolio_key, search_alternatives
from tests.v1.test_golden import CONTROL_SELECTIONS


class AlternativesTests(unittest.TestCase):
    def setUp(self):
        self.service = create_official_service()

    def test_complete_neighborhood_and_order_against_independent_enumeration(self):
        baseline = self.service.evaluate(CONTROL_SELECTIONS).score
        expected = {}
        valid = set()
        for position in range(5):
            for measure in self.service.snapshot.measures:
                targets = [None] if measure.scope == "city" else list(self.service.snapshot.district_by_id)
                for district in targets:
                    trial = list(CONTROL_SELECTIONS)
                    trial[position] = Selection(measure.id, district)
                    key = portfolio_key(trial)
                    if key == portfolio_key(CONTROL_SELECTIONS):
                        continue
                    evaluation = self.service.evaluate(trial)
                    if evaluation.valid:
                        valid.add(key)
                        if evaluation.score > baseline:
                            expected[key] = (-evaluation.score, evaluation.cost, 1, key)
        actual = search_alternatives(self.service, CONTROL_SELECTIONS, limit=20)
        self.assertEqual(actual.valid_candidates, len(valid))
        self.assertEqual([portfolio_key(r.selections) for r in actual.results],
                         sorted(expected, key=expected.get)[:20])

    def test_order_is_independent_of_input_permutation(self):
        expected = search_alternatives(self.service, CONTROL_SELECTIONS)
        for selection in list(permutations(CONTROL_SELECTIONS))[:8]:
            actual = search_alternatives(self.service, selection)
            self.assertEqual(actual, expected)

    def test_fixed_selections_are_unchanged(self):
        fixed = CONTROL_SELECTIONS[:3]
        result = search_alternatives(self.service, CONTROL_SELECTIONS, fixed=fixed, limit=20)
        self.assertTrue(all(set(fixed) <= set(alt.selections) for alt in result.results))
        self.assertEqual(search_alternatives(self.service, CONTROL_SELECTIONS,
                                            fixed=CONTROL_SELECTIONS).evaluated, 0)

    def test_bad_constraints_and_invalid_input_rejected(self):
        for kwargs in ({"limit": 0}, {"limit": 21}, {"fixed": [Selection("M99")]},
                       {"fixed": CONTROL_SELECTIONS[:1] * 2}, {"allowed_districts": ["nowhere"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search_alternatives(self.service, CONTROL_SELECTIONS, **kwargs)
        with self.assertRaises(ValueError):
            search_alternatives(self.service, [])

    def test_allowed_districts_constrain_entire_result(self):
        result = search_alternatives(self.service, CONTROL_SELECTIONS, allowed_districts=["nura"])
        self.assertTrue(all(s.district_id in (None, "nura") for r in result.results for s in r.selections))
        self.assertEqual(search_alternatives(self.service, CONTROL_SELECTIONS,
                                            allowed_districts=[]).results, ())
