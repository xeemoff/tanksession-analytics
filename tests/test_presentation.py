# -*- coding: utf-8 -*-
import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.presentation import (
    build_snapshot, validate_request, MAX_JS_INTEGER, MAX_TIMESTAMP, MAX_VEHICLES)
from tanksession_analytics.analytics import rolling_damage, window_comparison


def battle(index, account='own', vehicle='IS-7', damage=1200, xp=500, outcome='win'):
    return {'arena_id': 'private-arena-%s' % index, 'account_id': account,
            'timestamp': 1700000000 + index * 1800, 'vehicle': vehicle,
            'outcome': outcome, 'damage': damage, 'xp': xp}


def request(vehicle='', window=10, identifier='request-1'):
    return {'protocol': 1, 'request_id': identifier, 'vehicle': vehicle, 'window': window}


class PresentationTests(unittest.TestCase):
    def test_default_request_and_strict_protocol_boundary(self):
        self.assertEqual(validate_request(None), request(identifier='initial'))
        for value in ([], '', {'protocol': True, 'request_id': 'a'},
                      {'protocol': 2, 'request_id': 'a'}, {'protocol': 1},
                      dict(request(), account_id='someone-else'),
                      dict(request(), window=True), dict(request(), window='10'),
                      dict(request(), window=20), dict(request(), request_id='a\nb'),
                      dict(request(), request_id='a\n'),
                      dict(request(), request_id=''), dict(request(), request_id='a' * 65),
                      dict(request(), vehicle='a' * 129), dict(request(), vehicle=12),
                      dict(request(), vehicle=u'\ud800')):
            with self.assertRaises(ValueError):
                validate_request(value)

    def test_only_current_account_reaches_all_sections(self):
        rows = [battle(i, account='private-owner-account') for i in range(20)]
        rows += [battle(i, account='private-foreign-account', vehicle='Foreign tank',
                        damage=9999) for i in range(30)]
        goals = [{'account_id': 'private-owner-account', 'vehicle': 'IS-7',
                  'window': 10, 'target_avg_damage': 1000},
                 {'account_id': 'private-foreign-account', 'vehicle': 'Foreign tank',
                  'window': 10, 'target_avg_damage': 9999}]
        result = build_snapshot(rows, 'private-owner-account', goals=goals, now=1701000000)
        self.assertEqual(result['summary']['battles'], 20)
        self.assertEqual(result['summary']['avg_damage'], 1200)
        self.assertEqual(result['vehicles'], [{'name': 'IS-7', 'battles': 20}])
        self.assertEqual(len(result['goals']), 1)
        rendered = json.dumps(result, allow_nan=False)
        for secret in ('private-owner-account', 'private-foreign-account',
                       'private-arena', 'Foreign tank', 'account_id', 'arena_id'):
            self.assertNotIn(secret, rendered)

    def test_missing_identity_clears_every_data_section(self):
        for account in (None, False, 0, -1, 'local', 'unknown', '', {}, [], 'a' * 129):
            result = build_snapshot([battle(1)], account,
                                    diagnostics={'invalid': 12, 'conflicts': 8},
                                    goals=[{'vehicle': 'IS-7', 'window': 10,
                                            'target_avg_damage': 1000}], now=1701000000)
            self.assertEqual(result['status'], 'account_unavailable')
            self.assertEqual(result['summary']['battles'], 0)
            for key in ('vehicles', 'goals', 'history', 'series'):
                self.assertEqual(result[key], [])
            self.assertFalse(any(result['quality'].values()))

    def test_numeric_identity_uses_the_same_canonical_record_account(self):
        result = build_snapshot([battle(1, account=123), battle(2, account='123')], 123,
                                now=1701000000)
        self.assertEqual(result['summary']['battles'], 2)

    def test_unknown_and_zero_are_distinct(self):
        rows = [battle(1, damage=None, xp=None, outcome='unknown'),
                battle(2, damage=0, xp=0, outcome='loss')]
        result = build_snapshot(rows, 'own', now=1701000000)
        self.assertEqual(result['summary']['avg_damage'], 0)
        self.assertEqual(result['summary']['damage_samples'], 1)
        self.assertEqual(result['summary']['known_outcomes'], 1)
        self.assertEqual(result['summary']['win_rate'], 0)
        self.assertEqual(result['quality']['incomplete_records'], 1)
        self.assertEqual(result['history'][0]['damage'], 0)
        self.assertIsNone(result['history'][1]['damage'])

    def test_selected_tank_filters_summary_series_history_and_goals(self):
        rows = [battle(i) for i in range(20)] + [battle(30, vehicle='Other', damage=9000)]
        goals = [{'vehicle': 'IS-7', 'window': 10, 'target_avg_damage': 1000},
                 {'vehicle': 'Other', 'window': 10, 'target_avg_damage': 1000}]
        result = build_snapshot(rows, 'own', request('IS-7'), goals=goals, now=1701000000)
        self.assertEqual(result['summary']['battles'], 20)
        self.assertEqual(result['quality']['total_records'], 20)
        self.assertEqual(result['comparison']['current']['avg_damage'], 1200)
        self.assertEqual(len(result['vehicles']), 2)
        self.assertEqual(len(result['goals']), 1)
        self.assertTrue(all(row['vehicle'] == 'IS-7' for row in result['history']))
        self.assertTrue(all(row['avg_damage'] == 1200 for row in result['series']))

    def test_comparison_requires_two_full_windows(self):
        rows = [battle(i, damage=1000, outcome='loss') for i in range(10)]
        rows += [battle(i, damage=2000, outcome='win') for i in range(10, 20)]
        result = build_snapshot(rows, 'own', now=1701000000)
        self.assertEqual(result['comparison']['damage_delta'], 1000)
        self.assertEqual(result['comparison']['win_rate_delta_pp'], 100)
        partial = build_snapshot(rows[:19], 'own', now=1701000000)
        self.assertIsNone(partial['comparison']['previous'])
        self.assertFalse(partial['comparison']['enough_previous'])
        self.assertIsNone(partial['comparison']['damage_delta'])

    def test_invalid_records_and_journal_diagnostics_remain_visible(self):
        rows = [battle(1), dict(battle(2), outcome=[]),
                dict(battle(3), timestamp=None), dict(battle(4), vehicle='x' * 129),
                dict(battle(5), damage=MAX_JS_INTEGER + 1),
                dict(battle(6, account='foreign'), outcome=[])]
        result = build_snapshot(rows, 'own', diagnostics={'malformed': 2, 'invalid': 3,
                                'conflicts': 1}, now=1701000000)
        self.assertEqual(result['summary']['battles'], 1)
        self.assertEqual(result['quality']['invalid_records'], 9)
        self.assertEqual(result['quality']['conflicts'], 1)

    def test_non_object_records_do_not_break_reading(self):
        result = build_snapshot([None, [], 'broken', battle(1)], 'own', now=1701000000)
        self.assertEqual(result['quality']['invalid_records'], 3)
        self.assertEqual(result['summary']['battles'], 1)

    def test_snapshot_is_bounded_and_newest_history_first(self):
        rows = [battle(i) for i in range(300)]
        result = build_snapshot(rows, 'own', now=1701000000)
        self.assertEqual(len(result['history']), 12)
        self.assertEqual(len(result['series']), 60)
        self.assertEqual(result['history'][0]['timestamp'], rows[-1]['timestamp'])
        self.assertEqual(result['series'][-1]['battle'], 300)

    def test_excessive_dropdown_is_rejected_without_silent_truncation(self):
        rows = [battle(i, vehicle='Tank %d' % i) for i in range(MAX_VEHICLES + 1)]
        with self.assertRaises(ValueError):
            build_snapshot(rows, 'own', now=1701000000)

    def test_trailing_calculations_match_full_history_with_unknown_values(self):
        for length in (205, 1000):
            rows = [battle(index,
                           damage=None if index % 23 < 9 else (index % 37) * 111,
                           xp=None if index % 11 == 0 else 500,
                           outcome='unknown' if index % 17 == 0 else 'win')
                    for index in range(length)]
            for window in (10, 30, 100):
                result = build_snapshot(rows, 'own', request(window=window), now=1701000000)
                self.assertEqual(result['comparison'], window_comparison(rows, window))
                expected = [{'battle': number, 'avg_damage': average, 'known_damage': known}
                            for number, average, known in rolling_damage(rows, window, max_points=60)]
                self.assertEqual(result['series'], expected)
                self.assertEqual(result['series'][-1]['battle'], length)

    def test_empty_filter_does_not_fall_back_to_all_records(self):
        result = build_snapshot([battle(1)], 'own', request('not-owned'), now=1701000000)
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['summary']['battles'], 0)
        self.assertEqual(result['history'], [])

    def test_goals_keep_account_isolation_and_no_account_identifier(self):
        rows = [battle(i, account='own') for i in range(5)]
        rows += [battle(i + 10, account='foreign') for i in range(5)]
        result = build_snapshot(rows, 'own', goals=[{'vehicle': 'IS-7', 'window': 10,
                                 'target_avg_damage': 1000}], now=1701000000)
        self.assertEqual(result['goals'][0]['status'], 'in_progress')
        self.assertEqual(result['goals'][0]['battles'], 5)
        self.assertNotIn('account_id', result['goals'][0])

    def test_invalid_configuration_is_not_disguised_as_empty_data(self):
        for kwargs in ({'goals': {}}, {'goals': [{'vehicle': 'IS-7'}]},
                       {'source': 'remote'}, {'diagnostics': []},
                       {'diagnostics': {'invalid': -1}},
                       {'diagnostics': {'invalid': True}},
                       {'now': float('nan')}, {'now': MAX_JS_INTEGER + 1},
                       {'now': MAX_TIMESTAMP + 1}, {'now': -1}, {'now': 1.5}):
            args = {'now': 1701000000}
            args.update(kwargs)
            with self.assertRaises(ValueError):
                build_snapshot([battle(1)], 'own', **args)

    def test_observed_time_calendar_boundaries_are_supported(self):
        for timestamp in (0, MAX_TIMESTAMP):
            result = build_snapshot([battle(1)], 'own', now=timestamp)
            self.assertEqual(result['updated_at'], timestamp)

    def test_input_is_not_mutated_and_snapshot_is_json_serializable(self):
        rows = [battle(1, vehicle=u'ИС-7'), battle(2, damage=None)]
        before = copy.deepcopy(rows)
        result = build_snapshot(rows, 'own', request(u'ИС-7'), now=1701000000)
        self.assertEqual(rows, before)
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=True, allow_nan=False)), result)

    def test_output_order_is_deterministic(self):
        rows = [battle(i, vehicle='A' if i % 2 else 'B') for i in range(50)]
        self.assertEqual(build_snapshot(rows, 'own', now=1701000000),
                         build_snapshot(reversed(rows), 'own', now=1701000000))


if __name__ == '__main__':
    unittest.main()
