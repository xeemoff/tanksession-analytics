# -*- coding: utf-8 -*-
"""Cross-service regressions for bounded, coverage-aware 2.0 analytics."""
import calendar
import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.presentation import build_snapshot, validate_request
from tanksession_analytics.workspace import DEFAULT_PREFERENCES, Workspace, validate_preferences
from tanksession_analytics.insights import total_metric

NOW = calendar.timegm((2026, 11, 27, 12, 0, 0))
TYPE = 'type:257'


def row(index, **updates):
    value = {'arena_id': 'private-arena-%d' % index, 'account_id': 'private-own',
             'timestamp': NOW - 3600 + index * 60, 'vehicle': u'Т-34', 'vehicle_id': TYPE,
             'vehicle_tier': 5, 'vehicle_class': 'mediumTank', 'vehicle_nation': 'ussr',
             'map': 'arena:65547', 'map_label': u'Карта А', 'mode': '1',
             'outcome': 'win', 'damage': 1000, 'xp': 500, 'xp_bonus': 0,
             'credits_gross': 10000, 'credits_net': -100}
    value.update(updates)
    return value


def request(**updates):
    value = {'protocol': 1, 'request_id': 'v2-test', 'vehicle': '', 'window': 10, 'page': 0}
    value.update(updates)
    return value


def snapshot(rows, now=NOW, **selection):
    return build_snapshot(rows, 'private-own', request(**selection), now=now)


class AnalyticsV2Tests(unittest.TestCase):
    def test_dimensions_keep_unknown_rows_and_exclude_foreign_accounts(self):
        rows = [row(0), row(1, vehicle='Another', vehicle_id='type:513', vehicle_tier=8,
                            vehicle_class='SPG', map='arena:22', map_label=u'Карта Б'),
                row(2, vehicle='Old label', vehicle_id=None, vehicle_tier=None,
                    vehicle_class=None, vehicle_nation=None, map=None, map_label=None,
                    credits_net=None),
                row(3, account_id='private-foreign', vehicle='SECRET FOREIGN', damage=99999)]
        original = copy.deepcopy(rows)
        result = snapshot(rows)
        data = result['analytics']
        self.assertEqual(data['coverage'], {'map_label': 2, 'vehicle_tier': 2,
                                           'vehicle_class': 2, 'vehicle_nation': 2})
        for groups in data['dimensions'].values():
            self.assertEqual(sum(item['summary']['battles'] for item in groups), 3)
            unknown = [item for item in groups if item['key'] == 'unknown']
            self.assertEqual(unknown[0]['summary']['battles'], 1)
        self.assertEqual(data['economy']['credits_net'], {'samples': 2, 'average': -100, 'total': -200})
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        for secret in ('private-own', 'private-foreign', 'private-arena', 'account_id',
                       'arena_id', 'SECRET FOREIGN'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(rows, original)

    def test_high_cardinality_groups_preserve_totals_in_a_bounded_other_bucket(self):
        rows = [row(index, vehicle='Tank %d' % index, vehicle_id=None,
                    map='arena:%d' % index, map_label='Map %d' % index) for index in range(80)]
        result = snapshot(rows, now=NOW + 10000)
        maps = result['analytics']['dimensions']['maps']
        vehicles = result['analytics']['economy']['vehicles']
        report_vehicles = result['reports']['periods'][2]['vehicles']
        self.assertEqual((len(maps), len(vehicles), len(report_vehicles)), (24, 64, 10))
        for groups in (maps, vehicles, report_vehicles):
            self.assertEqual(sum(group['summary']['battles'] for group in groups), 80)
            self.assertEqual(sum(group['credits_net']['total'] for group in groups), -8000)
            self.assertEqual(len(set(group['key'] for group in groups)), len(groups))

    def test_activity_uses_utc_receipt_time_even_when_process_timezone_is_different(self):
        stamp = calendar.timegm((2026, 11, 27, 0, 30, 0))
        previous = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'Etc/GMT+11'
            if hasattr(time, 'tzset'):
                time.tzset()
            data = snapshot([row(0, timestamp=stamp)])['analytics']
        finally:
            if previous is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = previous
            if hasattr(time, 'tzset'):
                time.tzset()
        self.assertEqual((data['basis'], data['timezone']), ('received_at', 'UTC'))
        activity = data['activity']
        self.assertEqual((len(activity['days']), len(activity['weekdays']), len(activity['hours'])), (90, 7, 24))
        self.assertEqual(activity['days'][-1]['key'], '2026-11-27')
        self.assertEqual(activity['days'][-1]['summary']['battles'], 1)
        self.assertEqual(activity['weekdays'][4]['summary']['battles'], 1)
        self.assertEqual(activity['hours'][0]['summary']['battles'], 1)
        self.assertEqual(activity['days'][0]['summary']['battles'], 0)
        self.assertIsNone(activity['days'][0]['credits_net']['total'])

    def test_totals_distinguish_negative_zero_unknown_and_integer_overflow(self):
        self.assertEqual(total_metric([{'credits_net': -300}, {'credits_net': 0},
                                       {'credits_net': None}], 'credits_net'),
                         {'samples': 2, 'average': -150, 'total': -300})
        self.assertEqual(total_metric([{}], 'credits_net'), {'samples': 0, 'average': None, 'total': None})
        maximum = (1 << 53) - 1
        huge = total_metric([{'credits_net': maximum}, {'credits_net': maximum}], 'credits_net')
        self.assertEqual(huge['samples'], 2)
        self.assertIsNone(huge['total'])
        self.assertEqual(huge['average'], maximum)

    def test_unavailable_account_cannot_leak_new_analytics_or_report_counts(self):
        result = build_snapshot([row(0)], None, request(), now=NOW)
        self.assertEqual(result['analytics']['coverage']['vehicle_tier'], 0)
        self.assertEqual(result['analytics']['economy']['vehicles'], [])
        self.assertEqual(result['reports']['excluded_future'], 0)
        self.assertTrue(all(period['summary']['battles'] == 0 for period in result['reports']['periods']))
        self.assertEqual(result['coach']['observations'], [])
        self.assertEqual(result['coach']['goal_suggestions'], [])

    def test_calendar_supported_epoch_and_last_year_are_bounded(self):
        for stamp, expected in ((0, '1970-01-01'), (253402300799, '9999-12-31')):
            result = snapshot([], now=stamp)
            days = result['analytics']['activity']['days']
            self.assertEqual(len(days), 90)
            self.assertEqual(days[-1]['key'], expected)
            self.assertEqual(result['reports']['periods'][0]['end_at'], stamp + 1)
            json.dumps(result, allow_nan=False)


class ReportV2Tests(unittest.TestCase):
    def test_report_boundaries_are_exact_equal_intervals_and_future_is_explicit(self):
        end = NOW + 1
        start = end - 7 * 86400
        rows = [row(0, timestamp=start - 1, damage=500, credits_net=-500),
                row(1, timestamp=start, damage=1000, credits_net=-100),
                row(2, timestamp=end - 1, damage=2000, credits_net=100),
                row(3, timestamp=end, damage=99999, credits_net=99999)]
        reports = snapshot(rows)['reports']
        week, month, entire = reports['periods']
        self.assertEqual(reports['excluded_future'], 1)
        self.assertEqual((week['start_at'], week['end_at']), (start, end))
        self.assertEqual((week['previous']['start_at'], week['previous']['end_at']),
                         (start - 7 * 86400, start))
        self.assertEqual((week['summary']['battles'], week['previous']['summary']['battles']), (2, 1))
        self.assertEqual(week['comparison']['status'], 'ready')
        self.assertEqual(week['comparison']['avg_damage_delta'], 1000)
        self.assertEqual(week['comparison']['credits_net_average_delta'], 500)
        self.assertEqual(month['end_at'] - month['start_at'], 30 * 86400)
        self.assertEqual(entire['summary']['battles'], 3)
        self.assertIsNone(entire['previous'])
        self.assertEqual(entire['comparison']['status'], 'not_applicable')

    def test_report_comparison_checks_each_metrics_coverage_independently(self):
        rows = [row(0, timestamp=NOW - 8 * 86400, outcome='loss', credits_net=-50),
                row(1, damage=None, credits_net=None)]
        comparison = snapshot(rows)['reports']['periods'][0]['comparison']
        self.assertEqual(comparison['status'], 'partial_data')
        self.assertIsNone(comparison['avg_damage_delta'])
        self.assertEqual(comparison['win_rate_delta_pp'], 100)
        self.assertIsNone(comparison['credits_net_average_delta'])
        empty = snapshot([])['reports']['periods']
        self.assertEqual(empty[0]['comparison']['status'], 'insufficient_data')
        self.assertIsNone(empty[2]['start_at'])
        self.assertIsNone(empty[2]['credits_net']['total'])

    def test_signed_credit_delta_cannot_overflow_the_public_number_range(self):
        maximum = (1 << 53) - 1
        rows = [row(0, timestamp=NOW - 8 * 86400, credits_net=-maximum),
                row(1, credits_net=maximum)]
        comparison = snapshot(rows)['reports']['periods'][0]['comparison']
        self.assertEqual(comparison['status'], 'ready')
        self.assertIsNone(comparison['credits_net_average_delta'])


class CoachV2Tests(unittest.TestCase):
    def test_outlier_exposes_mean_and_median_evidence_without_claiming_skill(self):
        rows = [row(index) for index in range(20)]
        rows[-1]['damage'] = 10000
        result = snapshot(rows)['coach']
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['consistency'], {
            'status': 'ready', 'samples': 10, 'required': 10, 'median': 1000,
            'lower_quartile': 1000, 'upper_quartile': 1000, 'interquartile_range': 0,
            'median_absolute_deviation': 0})
        evidence = dict((item['kind'], item) for item in result['observations'])
        self.assertEqual(evidence['damage_average']['delta'], 900)
        self.assertEqual(evidence['damage_median']['delta'], 0)
        self.assertEqual(evidence['net_credits']['current'], -100)
        suggestion = result['goal_suggestions'][0]
        self.assertEqual(suggestion['target_avg_damage'], 2000)
        self.assertEqual(suggestion['baseline_avg_damage'], 1900)
        self.assertEqual(suggestion['vehicle'], TYPE)
        self.assertIs(suggestion['requires_confirmation'], True)
        self.assertEqual((suggestion['adjustment_percent'], suggestion['rounding_step']), (5, 50))

    def test_unknown_or_mixed_modes_and_incomplete_windows_never_suggest_goals(self):
        for field, value in (('mode', 'unknown'), ('mode', '7'), ('damage', None)):
            rows = [row(index) for index in range(20)]
            rows[-1][field] = value
            coach = snapshot(rows)['coach']
            self.assertEqual(coach['observations'], [])
            self.assertEqual(coach['goal_suggestions'], [])
            self.assertNotEqual(coach['consistency']['status'], 'ready')
        rows = [row(index, vehicle='T-34', vehicle_id=None) for index in range(20)]
        rows += [row(21, vehicle='T-34'), row(22, vehicle='T-34', vehicle_id='type:513')]
        coach = snapshot(rows, vehicle='T-34')['coach']
        self.assertEqual(coach['status'], 'identity_ambiguous')
        self.assertEqual(coach['observations'], [])
        self.assertEqual(coach['goal_suggestions'], [])
        self.assertEqual(coach['consistency']['status'], 'not_comparable')

    def test_consistency_can_describe_one_full_window_but_goal_needs_two(self):
        coach = snapshot([row(index, damage=index * 100) for index in range(10)])['coach']
        self.assertEqual(coach['status'], 'collecting')
        self.assertEqual(coach['consistency']['median'], 450)
        self.assertEqual(coach['consistency']['lower_quartile'], 200)
        self.assertEqual(coach['consistency']['upper_quartile'], 700)
        self.assertEqual(coach['consistency']['interquartile_range'], 500)
        self.assertEqual(coach['consistency']['median_absolute_deviation'], 250)
        self.assertEqual(coach['goal_suggestions'], [])
        huge = snapshot([row(index, damage=50000) for index in range(20)])['coach']
        self.assertEqual(huge['goal_suggestions'], [])


class HistoryV2Tests(unittest.TestCase):
    def test_search_spans_every_page_matches_localized_labels_and_never_changes_summary(self):
        rows = [row(index, vehicle='ussr:R04_T-34' if index < 10 else u'Т-34',
                    outcome='loss' if index == 3 else 'win',
                    map_label=u'Особая карта' if index == 2 else u'Обычная карта')
                for index in range(37)]
        by_map = snapshot(rows, history_query=u'особая', page=100)
        self.assertEqual(by_map['summary']['battles'], 37)
        self.assertEqual(by_map['pagination']['total'], 1)
        self.assertEqual(by_map['pagination']['page'], 0)
        self.assertEqual(by_map['history'][0]['timestamp'], rows[2]['timestamp'])
        by_outcome = snapshot(rows, history_query=u'поражение')
        self.assertEqual(by_outcome['pagination']['total'], 1)
        self.assertEqual(by_outcome['history'][0]['timestamp'], rows[3]['timestamp'])
        aliases = snapshot(rows, history_query='ussr:R04')
        self.assertEqual(aliases['pagination']['total'], 10)
        literal = snapshot(rows, history_query='.*')
        self.assertEqual(literal['history'], [])
        self.assertEqual(literal['summary']['battles'], 37)

    def test_numeric_history_sort_keeps_zero_negative_and_unknown_in_order(self):
        values = [None, -100, 0, 500, None, 100]
        rows = [row(index, credits_net=value) for index, value in enumerate(values)]
        first = snapshot(rows, history_sort='credits_desc')
        second = snapshot(rows, history_sort='credits_desc', page=1)
        combined = first['history'] + second['history']
        self.assertEqual([item['credits_net'] for item in combined], [500, 100, 0, -100, None, None])
        chronological = snapshot(rows, history_sort='time_asc')
        self.assertEqual(chronological['history'][0]['timestamp'], rows[0]['timestamp'])
        for patch in ({'history_sort': 'damage;rm'}, {'history_sort': []},
                      {'history_query': 'x' * 65}, {'history_query': 'line\nbreak'}):
            with self.assertRaises(ValueError):
                validate_request(request(**patch))


class DisplayPreferencesV2Tests(unittest.TestCase):
    def test_legacy_profile_gets_defaults_without_writing_and_new_preferences_persist(self):
        folder = tempfile.mkdtemp(prefix='tanksession-v2-preferences-')
        try:
            workspace = Workspace(folder)
            path = workspace._path('private-own')
            os.makedirs(os.path.dirname(path))
            old = {'version': 1, 'preferences': {'vehicle': '', 'window': 10, 'tab': 'progress',
                                                'density': 'normal', 'contrast': 'standard'}, 'goals': []}
            raw = json.dumps(old).encode('utf-8')
            with open(path, 'wb') as stream:
                stream.write(raw)
            loaded = workspace.snapshot([row(0)], 'private-own', request(action='initialize'), now=NOW)
            self.assertEqual(loaded['workspace']['preferences'], DEFAULT_PREFERENCES)
            with open(path, 'rb') as stream:
                self.assertEqual(stream.read(), raw)
            changed = dict(DEFAULT_PREFERENCES, theme='slate', motion='reduced', tab='analytics',
                           modules=['activity', 'economy', 'reports'])
            saved = workspace.snapshot([row(0)], 'private-own', request(action='save_preferences',
                                      preferences=changed), now=NOW)
            self.assertEqual(saved['workspace']['operation']['code'], 'preferences_saved')
            with open(path + '.bak', 'rb') as stream:
                self.assertEqual(stream.read(), raw)
            reopened = Workspace(folder).snapshot([row(0)], 'private-own', request(action='initialize'), now=NOW)
            self.assertEqual(reopened['workspace']['preferences'], changed)
        finally:
            shutil.rmtree(folder)

    def test_invalid_display_preferences_are_rejected_without_mutating_defaults(self):
        original = copy.deepcopy(DEFAULT_PREFERENCES)
        for patch in ({'modules': ['coach', 'coach']}, {'modules': 'coach'},
                      {'modules': ['remote_script']}, {'theme': 'external'}, {'motion': True}):
            with self.assertRaises(ValueError):
                validate_preferences(dict(DEFAULT_PREFERENCES, **patch))
        clean = validate_preferences(dict(DEFAULT_PREFERENCES))
        clean['modules'].append('reports')
        self.assertEqual(DEFAULT_PREFERENCES, original)


if __name__ == '__main__':
    unittest.main()
