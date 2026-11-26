import copy
import os
import sys
import unittest
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.analytics import (
    select_records, vehicle_table, window_comparison, rolling_damage, safe_window,
    valid_date, sort_records)


def battle(i, vehicle='IS-7', account='user1', damage=1000, outcome='win'):
    return dict(arena_id=str(i), timestamp=1700000000+i*3600,
                account_id=account, vehicle=vehicle, damage=damage,
                outcome=outcome, xp=500)


class AnalyticsTests(unittest.TestCase):
    def test_date_validation(self):
        self.assertEqual(valid_date('2026-02-28'), '2026-02-28')
        for bad in ('2026-02-30', '2026-2-03', '2026-13-01', '26-11-17', '<script>'):
            self.assertEqual(valid_date(bad), '')

    def test_window_whitelist(self):
        self.assertEqual(safe_window('30'), 30)
        self.assertEqual(safe_window('1000'), 10)
        self.assertEqual(safe_window(None), 10)

    def test_filter_account_and_vehicle(self):
        items = [battle(1), battle(2, account='user2'), battle(3, vehicle='Leopard 1')]
        self.assertEqual([r['arena_id'] for r in select_records(items, account='user1', vehicle='IS-7')], ['1'])
        self.assertEqual(len(select_records(items, account='unknown')), 0)

    def test_date_range_inclusive(self):
        items = [battle(1), battle(30)]
        date = datetime.fromtimestamp(items[0]['timestamp']).strftime('%Y-%m-%d')
        found = select_records(items, from_day=date, to_day=date)
        self.assertEqual([r['arena_id'] for r in found], ['1'])

    def test_bad_timestamps_excluded(self):
        items = [battle(2), dict(battle(1), timestamp='bad'), battle(3)]
        self.assertEqual([r['arena_id'] for r in sort_records(items)], ['2', '3'])

    def test_vehicle_sorting_is_stable(self):
        rows = [battle(1, 'B'), battle(2, 'A'), battle(3, 'B')]
        self.assertEqual([row[0] for row in vehicle_table(rows)], ['B', 'A'])

    def test_vehicle_selector_unifies_exact_account_aliases_without_mutating_labels(self):
        rows = [dict(battle(1, 'Old label'), vehicle_id='type:257'),
                battle(2, 'Old label'), dict(battle(3, 'New label'), vehicle_id='type:257'),
                battle(4, 'Old label', account='other')]
        original = copy.deepcopy(rows)
        for selected in ('Old label', 'New label', 'type:257'):
            result = select_records(rows, vehicle=selected, account='user1')
            self.assertEqual([row['arena_id'] for row in result], ['1', '2', '3'])
            self.assertEqual([row['vehicle'] for row in result], ['Old label', 'Old label', 'New label'])
            self.assertTrue(all(row['vehicle_id'] == 'type:257' for row in result))
        self.assertEqual(rows, original)

    def test_legacy_filter_resolves_per_account_and_does_not_link_other_accounts(self):
        rows = [dict(battle(1, 'Shared', account='A'), vehicle_id='type:257'),
                battle(2, 'Shared', account='A'),
                dict(battle(3, 'Shared', account='B'), vehicle_id='type:513'),
                battle(4, 'Shared', account='B'), battle(5, 'Shared', account='C')]
        selected = select_records(rows, vehicle='Shared')
        self.assertEqual([row['vehicle_id'] for row in selected],
                         ['type:257', 'type:257', 'type:513', 'type:513', None])
        self.assertEqual([row['arena_id'] for row in select_records(rows, vehicle='type:257')], ['1', '2'])
        ranked = dict(vehicle_table(rows))
        self.assertEqual({key: value['battles'] for key, value in ranked.items()},
                         {'type:257': 2, 'type:513': 2, 'Shared': 1})

    def test_same_explicit_type_can_group_accounts_without_importing_their_aliases(self):
        rows = [dict(battle(1, 'Alpha', account='A'), vehicle_id='type:257'),
                battle(2, 'Alpha', account='A'),
                dict(battle(3, 'Beta', account='B'), vehicle_id='type:257'),
                battle(4, 'Beta', account='B'), battle(5, 'Alpha', account='C')]
        ranked = dict(vehicle_table(rows))
        self.assertEqual(ranked['type:257']['battles'], 4)
        self.assertEqual(ranked['Alpha']['battles'], 1)
        self.assertEqual(len(select_records(rows, vehicle='type:257', account='C')), 0)

    def test_unowned_legacy_rows_remain_readable_without_identity_inference(self):
        name = 'ussr:R04_T-34'
        rows = [dict(battle(1, name, account='A'), vehicle_id='type:257'),
                battle(2, name, account='local'), battle(3, name, account='unknown'),
                battle(4, name, account=None), battle(5, name, account='B')]
        selected = select_records(rows)
        self.assertEqual([row.get('vehicle_id') for row in selected],
                         ['type:257', None, None, None, 'name:' + name])
        self.assertEqual([row['arena_id'] for row in select_records(rows, vehicle=name, account='local')], ['2', '4'])
        self.assertEqual([row['arena_id'] for row in select_records(rows, vehicle='name:' + name)], ['1', '5'])
        self.assertEqual(dict(vehicle_table(rows))[name]['battles'], 3)

    def test_reserved_legacy_label_does_not_impersonate_a_numeric_selector(self):
        rows = [battle(1, 'type:257'), dict(battle(2, 'Typed'), vehicle_id='type:257')]
        selected = select_records(rows, vehicle='type:257', account='user1')
        self.assertEqual([row['arena_id'] for row in selected], ['2'])
        keys = [name for name, _ in vehicle_table(rows)]
        legacy = next(key for key in keys if key.startswith('legacy:'))
        self.assertEqual([row['arena_id'] for row in select_records(rows, vehicle=legacy)], ['1'])

    def test_two_full_windows_and_deltas(self):
        items = [battle(i, damage=1000, outcome='loss') for i in range(10)] + [
            battle(i, damage=2000, outcome='win') for i in range(10, 20)]
        res = window_comparison(items, 10)
        self.assertTrue(res['enough_previous'])
        self.assertEqual(res['damage_delta'], 1000.0)
        self.assertEqual(res['win_rate_delta_pp'], 100.0)

    def test_incomplete_window_no_misleading_comparison(self):
        res = window_comparison([battle(i) for i in range(12)], 10)
        self.assertTrue(res['enough_current'])
        self.assertFalse(res['enough_previous'])
        self.assertIsNone(res['damage_delta'])

    def test_rolling_samples_and_sparse_data(self):
        items = [battle(i, damage=None if i < 4 else 1200) for i in range(15)]
        points = rolling_damage(items, 10)
        self.assertEqual(points[0][0], 10)
        self.assertIsNone(points[0][1])  # only 6/10 known
        self.assertEqual(points[-1][1], 1200.0)

    def test_unknown_damage_not_zero(self):
        items = [battle(i, damage=None) for i in range(20)]
        res = window_comparison(items, 10)
        self.assertIsNone(res['damage_delta'])
        self.assertIsNone(res['current']['avg_damage'])


if __name__ == '__main__':
    unittest.main()
