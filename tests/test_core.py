# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.core import normalize_result, summarize, by_day, by_vehicle


class NormalizeTests(unittest.TestCase):
    def test_normalizes_one_player_without_guessing_metrics(self):
        raw = {'arenaUniqueID': 123, 'common': {'winnerTeam': 1, 'bonusType': 1},
               'personal': {42: {'team': 1, 'damageDealt': 2000, 'xp': 900}}}
        record = normalize_result(raw, {'player_vehicle_id': 42, 'vehicle_name': 'IS-7'}, 1720000000)
        self.assertEqual(record['arena_id'], '123')
        self.assertEqual(record['outcome'], 'win')
        self.assertEqual(record['vehicle'], 'IS-7')
        self.assertEqual(record['damage'], 2000)
        self.assertEqual(record['xp'], 900)
        self.assertIsNone(record['assistance_radio'])

    def test_draw(self):
        raw = {'arenaUniqueID': 124, 'common': {'winnerTeam': 0}, 'personal': {1: {'team': 2}}}
        self.assertEqual(normalize_result(raw)['outcome'], 'draw')

    def test_no_outcome_is_unknown_not_loss(self):
        raw = {'arenaUniqueID': 124, 'personal': {1: {'damageDealt': 0}}}
        self.assertEqual(normalize_result(raw)['outcome'], 'unknown')

    def test_multiplayer_result_not_attributed_to_random_player(self):
        raw = {'arenaUniqueID': 125, 'personal': {1: {'damageDealt': 500}, 2: {'damageDealt': 3000}}}
        self.assertIsNone(normalize_result(raw))
        own = normalize_result(raw, {'player_vehicle_id': 2})
        self.assertEqual(own['damage'], 3000)

    def test_invalid_input_rejected(self):
        self.assertIsNone(normalize_result({'personal': {1: {'damageDealt': 123}}}))
        self.assertIsNone(normalize_result(None))
        self.assertIsNone(normalize_result({'arenaUniqueID': 1, 'personal': {}}))

    def test_bad_damage_does_not_become_zero(self):
        raw = {'arenaUniqueID': 42, 'personal': {1: {'damageDealt': 'not-a-number', 'xp': -2}}}
        record = normalize_result(raw)
        self.assertIsNone(record['damage'])
        self.assertIsNone(record['xp'])


class SummaryTests(unittest.TestCase):
    def test_win_rate_and_known_samples(self):
        rows = [{'outcome': 'win', 'damage': 1000, 'xp': 500},
                {'outcome': 'loss', 'damage': 2000, 'xp': 200},
                {'outcome': 'unknown', 'damage': None, 'xp': None},
                {'outcome': 'draw', 'damage': 3000, 'xp': 900}]
        result = summarize(rows)
        self.assertEqual(result['battles'], 4)
        self.assertEqual(result['known_outcomes'], 3)
        self.assertEqual(result['win_rate'], 33.3)
        self.assertEqual(result['avg_damage'], 2000.0)
        self.assertEqual(result['avg_xp'], 533.3)
        self.assertEqual(result['damage_samples'], 3)

    def test_empty(self):
        result = summarize([])
        self.assertEqual(result['battles'], 0)
        self.assertIsNone(result['win_rate'])
        self.assertIsNone(result['avg_damage'])

    def test_vehicle_and_date_grouping(self):
        rows = [{'timestamp': 1720000000, 'vehicle': 'IS-7', 'outcome': 'win', 'damage': 100},
                {'timestamp': 1720000010, 'vehicle': 'T-34', 'outcome': 'loss', 'damage': 200}]
        self.assertEqual(by_vehicle(rows)['IS-7']['battles'], 1)
        self.assertEqual(sum(bucket['battles'] for bucket in by_day(rows).values()), 2)


if __name__ == '__main__':
    unittest.main()

class RegressionV02Tests(unittest.TestCase):
    def test_damage_string_is_numeric_and_invalid_values_are_ignored(self):
        stats = summarize([
            {'outcome': 'win', 'damage': '1000', 'xp': '200'},
            {'outcome': 'loss', 'damage': 2000, 'xp': 'bad'},
            {'outcome': 'loss', 'damage': 'garbage', 'xp': 0},
            {'outcome': 'draw', 'damage': -1, 'xp': True},
            {'outcome': 'unknown', 'damage': 10.5, 'xp': -9},
        ])
        self.assertEqual(stats['battles'], 5)
        self.assertEqual(stats['avg_damage'], 1500.0)
        self.assertEqual(stats['damage_samples'], 2)
        self.assertEqual(stats['avg_xp'], 100.0)
        self.assertEqual(stats['win_rate'], 25.0)

    def test_invalid_timestamp_and_arena_ids_do_not_crash(self):
        raw = {'arenaUniqueID': 7, 'personal': {12: {'damageDealt': 2}}}
        self.assertIsNone(normalize_result(raw, observed_at='nope'))
        self.assertIsNone(normalize_result(dict(raw, arenaUniqueID='  ')))
        self.assertIsNone(normalize_result(dict(raw, arenaUniqueID='0')))
        self.assertIsNotNone(normalize_result(raw))  # default time.time has fractions

    def test_wrong_player_key_does_not_fall_back_without_confirmation(self):
        raw = {'arenaUniqueID': 7, 'personal': {22: {'damageDealt': 900}}}
        self.assertIsNone(normalize_result(raw, {'player_vehicle_id': 123}))
        own = normalize_result(raw, {'player_vehicle_id': 123,
                                     'confirmed_own_result': True})
        self.assertEqual(own['damage'], 900)

    def test_ambiguous_two_players_always_rejected(self):
        raw = {'arenaUniqueID': 7, 'personal': {1: {'xp': 10}, 2: {'xp': 900}}}
        self.assertIsNone(normalize_result(raw, {'player_vehicle_id': 3,
                                                 'confirmed_own_result': True}))

    def test_grouping_handles_malformed_rows(self):
        rows = [None, {}, {'timestamp': 'NaN', 'vehicle': 'X'},
                {'timestamp': 1720000000, 'vehicle': 'X', 'damage': '200'}]
        self.assertEqual(by_vehicle(rows)['X']['battles'], 2)
        self.assertEqual(sum(x['battles'] for x in by_day(rows).values()), 1)
