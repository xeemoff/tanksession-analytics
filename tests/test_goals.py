import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.goals import evaluate_goals, validate_goals


def rows(account, count, damage=2500):
    return [{'arena_id': '%s-%d' % (account, i), 'account_id': account,
             'timestamp': 1700000000 + i, 'vehicle': 'IS-7', 'damage': damage}
            for i in range(count)]


GOAL = {'vehicle': 'IS-7', 'window': 10, 'target_avg_damage': 2000}


class AccountGoalTests(unittest.TestCase):
    def test_two_incomplete_accounts_cannot_complete_each_others_goal(self):
        results = evaluate_goals(rows('A', 5) + rows('B', 5), [GOAL])
        self.assertEqual([(r['account_id'], r['battles'], r['status']) for r in results],
                         [('A', 5, 'in_progress'), ('B', 5, 'in_progress')])

    def test_bound_goal_ignores_other_account(self):
        goal = dict(GOAL, account_id='A')
        result = evaluate_goals(rows('A', 10, 1000) + rows('B', 10, 5000), [goal])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['avg_damage'], 1000)
        self.assertEqual(result[0]['status'], 'not_achieved')
        self.assertEqual(evaluate_goals(rows('B', 10), [goal], account_id='B'), [])

    def test_selected_account_with_empty_history_is_still_identified(self):
        result = evaluate_goals([], [GOAL], account_id='A')[0]
        self.assertEqual((result['account_id'], result['battles']), ('A', 0))
        self.assertEqual(result['status'], 'in_progress')

    def test_missing_account_is_its_own_legacy_bucket(self):
        legacy = rows('A', 5)
        for row in legacy:
            row.pop('account_id')
        result = evaluate_goals(legacy + rows('B', 5), [GOAL])
        self.assertEqual({r['account_id']: r['battles'] for r in result}, {'local': 5, 'B': 5})

    def test_rounding_cannot_award_an_unmet_target(self):
        sample = rows('A', 25, 2000)
        sample[0]['damage'] = 1999
        result = evaluate_goals(sample, [dict(GOAL, window=25)])[0]
        self.assertEqual(result['avg_damage'], 2000.0)
        self.assertEqual(result['status'], 'not_achieved')

    def test_demo_goals_match_real_demo_vehicle_labels(self):
        sample = [json.loads(line) for line in
                  (ROOT / 'sample_data/battles.jsonl').read_text(encoding='utf-8').splitlines()]
        goals = json.loads((ROOT / 'sample_data/goals.json').read_text(encoding='utf-8'))
        results = evaluate_goals(sample, goals)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r['account_id'] == 'demo' and r['battles'] == 10 for r in results))

    def test_bad_account_binding_is_rejected(self):
        for account in (' ', [], True, None, 'A' * 129):
            with self.assertRaises(ValueError):
                validate_goals([dict(GOAL, account_id=account)])


if __name__ == '__main__':
    unittest.main()
