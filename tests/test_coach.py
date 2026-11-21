# -*- coding: utf-8 -*-
import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.coach import build_coach, MAX_JS_INTEGER


def rows(damage, vehicle='IS-7', mode='1'):
    return [dict(vehicle=vehicle, mode=mode, damage=value, timestamp=1700000000 + index,
                 arena_id='arena-%d' % index, account_id='own', xp=500, outcome='win')
            for index, value in enumerate(damage)]


class CoachTests(unittest.TestCase):
    def test_empty_is_an_explicit_data_requirement(self):
        result = build_coach([])
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['remaining_battles'], 20)
        self.assertIsNone(result['comparison'])
        self.assertIsNone(result['records']['best_damage'])
        self.assertFalse(result['records']['new_damage_record'])

    def test_first_battle_is_a_baseline_not_a_new_record(self):
        result = build_coach(rows([700]))
        self.assertEqual(result['status'], 'collecting')
        self.assertEqual(result['vehicle'], 'IS-7')
        self.assertEqual(result['battles'], 1)
        self.assertEqual(result['remaining_battles'], 19)
        self.assertEqual(result['records']['best_damage'], 700)
        self.assertIsNone(result['records']['previous_best_damage'])
        self.assertFalse(result['records']['new_damage_record'])
        self.assertFalse(result['records']['new_window_record'])

    def test_multiple_vehicles_never_make_an_aggregate_comparison(self):
        data = rows([100] * 20, vehicle='A') + rows([10000] * 20, vehicle='B')
        result = build_coach(data)
        self.assertEqual(result['status'], 'choose_vehicle')
        self.assertEqual(result['vehicle'], '')
        self.assertEqual(result['battles'], 0)
        self.assertIsNone(result['comparison'])
        self.assertIsNone(result['records']['best_damage'])
        selected = build_coach(data, vehicle='A')
        self.assertEqual(selected['status'], 'ready')
        self.assertEqual(selected['comparison']['current_avg'], 100)
        self.assertEqual(selected['records']['best_damage'], 100)

    def test_unknown_vehicle_cannot_prove_matching_tank(self):
        for selection in ('', 'unknown'):
            result = build_coach(rows([1000] * 20, vehicle='unknown'), vehicle=selection)
            self.assertEqual(result['status'], 'choose_vehicle')
            self.assertEqual(result['battles'], 0)
            self.assertIsNone(result['comparison'])

    def test_absent_vehicle_does_not_fall_back_to_known_history(self):
        result = build_coach(rows([1000] * 20), vehicle='missing')
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['vehicle'], 'missing')
        self.assertIsNone(result['records']['best_damage'])

    def test_two_full_nonoverlapping_trailing_windows(self):
        data = rows([9000] * 10 + [1000] * 10 + [1500] * 10)
        result = build_coach(data)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['remaining_battles'], 0)
        self.assertEqual(result['comparison'], {
            'current_avg': 1500, 'previous_avg': 1000, 'delta': 500,
            'delta_percent': 50, 'current_median': 1500,
            'previous_median': 1000, 'median_delta': 500})
        self.assertEqual(result['coverage'], {'current_battles': 10, 'current_damage': 10,
                                             'previous_battles': 10, 'previous_damage': 10})

    def test_partial_previous_window_is_explained_but_never_compared(self):
        result = build_coach(rows([1000] * 19))
        self.assertEqual(result['status'], 'collecting')
        self.assertEqual(result['remaining_battles'], 1)
        self.assertEqual(result['coverage']['current_battles'], 10)
        self.assertEqual(result['coverage']['previous_battles'], 9)
        self.assertIsNone(result['comparison'])

    def test_missing_damage_does_not_pull_an_older_battle_into_window(self):
        data = rows([9000] * 10 + [1000] * 10 + [2000] * 9 + [None])
        result = build_coach(data)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['coverage']['current_damage'], 9)
        self.assertEqual(result['coverage']['previous_damage'], 10)
        self.assertIsNone(result['comparison'])
        self.assertIsNone(result['records']['latest_damage'])
        self.assertIsNone(result['records']['current_window_avg'])
        self.assertFalse(result['records']['new_damage_record'])

    def test_previous_missing_damage_also_blocks_comparison(self):
        result = build_coach(rows([None] + [1000] * 19))
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['coverage']['previous_damage'], 9)
        self.assertEqual(result['coverage']['current_damage'], 10)
        self.assertIsNone(result['comparison'])

    def test_unknown_outcome_and_xp_do_not_block_known_damage(self):
        data = rows([1000] * 20)
        for row in data:
            row.update(xp=None, outcome='unknown')
        result = build_coach(data)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['comparison']['delta'], 0)
        self.assertNotIn('xp', json.dumps(result))

    def test_zero_is_known_and_zero_baseline_has_no_percentage(self):
        result = build_coach(rows([0] * 10 + [100] * 10))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['comparison']['previous_avg'], 0)
        self.assertEqual(result['comparison']['delta'], 100)
        self.assertIsNone(result['comparison']['delta_percent'])
        all_zero = build_coach(rows([0] * 20))
        self.assertEqual(all_zero['records']['best_damage'], 0)
        self.assertEqual(all_zero['records']['best_window_avg'], 0)
        self.assertFalse(all_zero['records']['new_damage_record'])
        self.assertFalse(all_zero['records']['new_window_record'])

    def test_mean_and_median_expose_an_outlier_without_causal_claims(self):
        result = build_coach(rows([1000] * 10 + [900] * 9 + [10000]))
        self.assertEqual(result['comparison']['current_avg'], 1810)
        self.assertEqual(result['comparison']['delta'], 810)
        self.assertEqual(result['comparison']['current_median'], 900)
        self.assertEqual(result['comparison']['median_delta'], -100)

    def test_even_median_uses_two_middle_values(self):
        result = build_coach(rows([100] * 10 + list(range(10))))
        self.assertEqual(result['comparison']['current_median'], 4.5)
        self.assertEqual(result['comparison']['median_delta'], -95.5)

    def test_new_damage_record_requires_a_strictly_lower_known_baseline(self):
        fresh = build_coach(rows([1000, None, 1500]))['records']
        self.assertEqual(fresh['previous_best_damage'], 1000)
        self.assertTrue(fresh['new_damage_record'])
        self.assertFalse(build_coach(rows([1500, 1500]))['records']['new_damage_record'])
        self.assertFalse(build_coach(rows([None, 1500]))['records']['new_damage_record'])

    def test_first_complete_window_and_ties_are_not_new_records(self):
        first = build_coach(rows([1000] * 10))['records']
        self.assertEqual(first['best_window_avg'], 1000)
        self.assertEqual(first['current_window_avg'], 1000)
        self.assertIsNone(first['previous_best_window_avg'])
        self.assertFalse(first['new_window_record'])
        tie = build_coach(rows([1000] * 11))['records']
        self.assertEqual(tie['previous_best_window_avg'], 1000)
        self.assertFalse(tie['new_window_record'])

    def test_rolling_record_compares_every_previous_complete_window(self):
        result = build_coach(rows([1000] * 20 + [3500]))['records']
        self.assertEqual(result['current_window_avg'], 1250)
        self.assertEqual(result['previous_best_window_avg'], 1000)
        self.assertEqual(result['best_window_avg'], 1250)
        self.assertTrue(result['new_window_record'])
        old_peak = build_coach(rows([9000] * 10 + [1000] * 20 + [3500]))['records']
        self.assertEqual(old_peak['best_window_avg'], 9000)
        self.assertFalse(old_peak['new_window_record'])

    def test_incomplete_rolling_windows_do_not_count_as_baselines(self):
        result = build_coach(rows([None] + [1000] * 10))['records']
        self.assertEqual(result['current_window_avg'], 1000)
        self.assertIsNone(result['previous_best_window_avg'])
        self.assertFalse(result['new_window_record'])

    def test_known_different_modes_block_progress_but_keep_local_records(self):
        data = rows([1000] * 10, mode='1') + rows([2000] * 10, mode='7')
        result = build_coach(data)
        self.assertEqual(result['status'], 'mixed_modes')
        self.assertEqual(result['remaining_battles'], 0)
        self.assertIsNone(result['comparison'])
        self.assertEqual(result['records']['best_damage'], 2000)
        self.assertEqual(result['coverage']['current_damage'], 10)

    def test_old_modes_outside_two_windows_do_not_block_recent_comparison(self):
        data = rows([9000] * 10, mode='7') + rows([1000] * 20, mode='1')
        self.assertEqual(build_coach(data)['status'], 'ready')

    def test_unknown_mode_does_not_invent_a_mode_conflict(self):
        data = rows([1000] * 10, mode='unknown') + rows([1000] * 10, mode='1')
        self.assertEqual(build_coach(data)['status'], 'ready')

    def test_all_window_sizes_use_full_periods(self):
        for window in (10, 30, 100):
            result = build_coach(rows([100] * window + [200] * window), window=window)
            self.assertEqual(result['required_battles'], 2 * window)
            self.assertEqual(result['coverage']['current_battles'], window)
            self.assertEqual(result['comparison']['delta'], 100)
            self.assertEqual(result['comparison']['delta_percent'], 100)

    def test_large_exact_sums_do_not_overflow_the_frontend_number_range(self):
        result = build_coach(rows([1] * 10 + [MAX_JS_INTEGER] * 10))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['comparison']['current_avg'], MAX_JS_INTEGER)
        self.assertEqual(result['comparison']['delta'], MAX_JS_INTEGER - 1)
        self.assertIsNone(result['comparison']['delta_percent'])
        self.assertEqual(result['records']['best_window_avg'], MAX_JS_INTEGER)
        json.dumps(result, allow_nan=False)

    def test_record_comparisons_use_exact_sums_before_display_rounding(self):
        result = build_coach(rows([MAX_JS_INTEGER - 1] * 100 + [MAX_JS_INTEGER]),
                             window=100)['records']
        self.assertTrue(result['new_window_record'])
        self.assertTrue(result['new_damage_record'])

    def test_input_records_are_not_mutated(self):
        data = rows([None, 0, 1000])
        before = copy.deepcopy(data)
        build_coach(data)
        self.assertEqual(data, before)


if __name__ == '__main__':
    unittest.main()
