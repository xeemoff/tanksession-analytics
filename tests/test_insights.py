# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.presentation import build_snapshot
from tanksession_analytics.goals import evaluate_goals


def row(index, **fields):
    result = dict(arena_id=str(index + 1), account_id='A', vehicle='Tank',
                  timestamp=1700000000 + index * 60, mode='1',
                  outcome='win', damage=1000, xp=500)
    result.update(fields)
    return result


def snapshot(rows, **selection):
    request = dict(protocol=1, request_id='test', vehicle='', window=10)
    request.update(selection)
    return build_snapshot(rows, 'A', request, now=1701000000)


class ExtendedInsightsTests(unittest.TestCase):
    def test_full_pagination_never_drops_or_duplicates_history(self):
        rows = [row(i) for i in range(37)] + [row(40, account_id='B')]
        stamps = []
        for page in range(8):
            result = snapshot(rows, page=page)
            self.assertEqual(result['pagination']['pages'], 8)
            self.assertEqual(result['pagination']['total'], 37)
            stamps.extend(item['timestamp'] for item in result['history'])
        self.assertEqual(stamps, [item['timestamp'] for item in reversed(rows[:-1])])
        self.assertEqual(snapshot(rows, page=999)['pagination']['page'], 7)
        empty = snapshot([], page=10)
        self.assertEqual(empty['pagination'], {'page': 0, 'pages': 1, 'page_size': 5, 'total': 0})
        self.assertEqual(empty['history'], [])

    def test_missing_metrics_do_not_become_zero_and_rates_use_paired_rows(self):
        rows = [row(1, kills=0, survived=False, shots=10, direct_hits=5,
                    penetrations=2, credits_net=-200, credits_gross=0, xp_base=0),
                row(2, kills=2, survived=True, shots=100, direct_hits=None,
                    penetrations=None, credits_net=400), row(3)]
        metrics = snapshot(rows)['metrics']
        self.assertEqual(metrics['fields']['kills'], {'samples': 2, 'average': 1})
        self.assertEqual(metrics['fields']['credits_net'], {'samples': 2, 'average': 100})
        self.assertEqual(metrics['fields']['xp_base'], {'samples': 1, 'average': 0})
        self.assertEqual(metrics['survival'], {'samples': 2, 'survived': 1, 'rate': 50})
        self.assertEqual(metrics['accuracy'], {'samples': 1, 'shots': 10, 'hits': 5, 'rate': 50})
        self.assertEqual(metrics['penetration'], {'samples': 1, 'hits': 5, 'penetrations': 2, 'rate': 40})
        empty = snapshot([row(1)])['metrics']
        self.assertIsNone(empty['fields']['kills']['average'])
        self.assertIsNone(empty['survival']['rate'])
        self.assertIsNone(empty['accuracy']['rate'])

    def test_invalid_rate_pairs_and_zero_shots_never_show_false_precision(self):
        metrics = snapshot([row(1, shots=0, direct_hits=0, penetrations=0),
                            row(2, shots=1, direct_hits=3, penetrations=4)])['metrics']
        self.assertEqual(metrics['accuracy']['samples'], 1)
        self.assertIsNone(metrics['accuracy']['rate'])
        self.assertEqual(metrics['penetration']['samples'], 1)
        self.assertIsNone(metrics['penetration']['rate'])

    def sessions(self):
        return [row(i) for i in range(10)] + [row(i, timestamp=1700010000 + i * 60,
                                                  damage=1200) for i in range(10, 20)]

    def test_session_comparison_requires_real_two_complete_same_vehicle_mode_samples(self):
        rows = self.sessions()
        result = snapshot(rows)['sessions']
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['basis'], 'received_at')
        self.assertEqual(result['comparison']['status'], 'ready')
        self.assertEqual(result['comparison']['delta_average'], 200)
        self.assertEqual(result['comparison']['delta_median'], 200)
        for key, value, expected in (('damage', None, 'incomplete'),
                                     ('mode', 'unknown', 'mode_unknown'),
                                     ('mode', '0', 'mode_unknown'),
                                     ('mode', '7', 'mixed_modes'),
                                     ('vehicle', 'Another', 'choose_vehicle')):
            changed = [dict(item) for item in rows]
            changed[-1][key] = value
            comparison = snapshot(changed)['sessions']['comparison']
            self.assertEqual(comparison['status'], expected)
            self.assertIsNone(comparison['delta_average'])
        self.assertEqual(snapshot(rows[:-1])['sessions']['comparison']['status'], 'insufficient_data')

    def test_session_split_happens_before_vehicle_filter_and_excludes_foreign_account(self):
        rows = [row(0), row(30, vehicle='Another'), row(60, vehicle='Another'), row(90)]
        rows.append(row(200, account_id='B'))
        result = snapshot(rows, vehicle='Tank')['sessions']
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['summary']['battles'], 2)

    def test_unknown_damage_cannot_award_a_goal(self):
        rows = [row(i, damage=3000) for i in range(10)]
        rows[-1]['damage'] = None
        goal = {'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 2500}
        result = evaluate_goals(rows, [goal], account_id='A')[0]
        self.assertEqual(result['known_damage'], 9)
        self.assertEqual(result['status'], 'insufficient_data')

    def test_optional_metrics_are_fill_missing_revisions_with_zero_and_false_preserved(self):
        from tanksession_analytics.storage import BattleStore
        old = row(1, kills=None, survived=None, credits_net=None)
        new = row(1, kills=0, survived=False, credits_net=-100)
        status, merged = BattleStore._merge(old, new)
        self.assertEqual(status, 'updated')
        self.assertEqual(merged['kills'], 0)
        self.assertIs(merged['survived'], False)
        self.assertEqual(merged['credits_net'], -100)
        self.assertEqual(BattleStore._merge(merged, row(1, survived=True))[0], 'conflict')


if __name__ == '__main__':
    unittest.main()
