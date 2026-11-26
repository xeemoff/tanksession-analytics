# -*- coding: utf-8 -*-
"""Additive measurements must preserve unknowns and legacy journal records."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))

from tanksession_analytics.core import MAX_RECORD_INTEGER, normalize_result, validate_record


class OptionalMetricTests(unittest.TestCase):
    def normalize(self, values=None, common=None):
        personal = {'damageDealt': 83, 'xp': 924, 'team': 1}
        personal.update(values or {})
        common_values = {'winnerTeam': 1}
        common_values.update(common or {})
        return normalize_result({'arenaUniqueID': 1234,
                                 'common': common_values,
                                 'personal': {42: personal}},
                                context={'account_id': '88', 'player_vehicle_id': 42},
                                observed_at=1700000000)

    def test_legacy_records_keep_original_primary_statistics(self):
        record = validate_record({'arena_id': '1', 'account_id': '88',
                                  'damage': 83, 'xp': 924, 'outcome': 'win'})
        self.assertEqual(record['damage'], 83)
        self.assertEqual(record['xp'], 924)
        self.assertEqual(record['data_status'], 'complete')
        for field in ('map', 'kills', 'shots', 'direct_hits', 'penetrations',
                      'xp_base', 'xp_bonus', 'credits_gross', 'credits_net', 'survived'):
            self.assertIsNone(record[field], field)

    def test_explicit_reference_fields_are_normalized(self):
        record = self.normalize({'kills': 2, 'shots': 7, 'directHits': 5,
                                 'piercings': 3, 'deathReason': -1,
                                 'credits': 12345, 'originalXP': 615,
                                 'achievementXP': 0}, {'arenaTypeID': 11})
        self.assertEqual(record['map'], 'arena:11')
        self.assertEqual(record['kills'], 2)
        self.assertEqual(record['shots'], 7)
        self.assertEqual(record['direct_hits'], 5)
        self.assertEqual(record['penetrations'], 3)
        self.assertTrue(record['survived'])
        self.assertEqual(record['xp_base'], 615)
        self.assertEqual(record['xp_bonus'], 309)
        self.assertEqual(record['xp'], 924)
        self.assertEqual(record['credits_gross'], 12345)
        self.assertIsNone(record['credits_net'])

    def test_death_reason_distinguishes_zero_from_missing(self):
        self.assertFalse(self.normalize({'deathReason': 0})['survived'])
        self.assertFalse(self.normalize({'deathReason': 8})['survived'])
        for value in (None, -2, True, False, 'invalid', 0.5,
                      MAX_RECORD_INTEGER + 1, -MAX_RECORD_INTEGER - 2):
            self.assertIsNone(self.normalize({'deathReason': value})['survived'])

    def test_absent_survival_is_not_inferred_from_health_or_killer(self):
        self.assertIsNone(self.normalize({'health': 100, 'killerID': 0})['survived'])
        self.assertIsNone(self.normalize({'health': 0, 'killerID': 45})['survived'])

    def test_base_xp_requires_both_reference_components(self):
        self.assertEqual(self.normalize({'originalXP': 700,
                                         'achievementXP': 100})['xp_base'], 600)
        self.assertEqual(self.normalize({'originalXP': 0,
                                         'achievementXP': 0})['xp_base'], 0)
        for values in ({'originalXP': 700}, {'achievementXP': 0},
                       {'originalXP': 10, 'achievementXP': 20},
                       {'originalXP': True, 'achievementXP': 0},
                       {'originalXP': 100, 'achievementXP': False},
                       {'originalXP': -1, 'achievementXP': 0},
                       {'originalXP': 100, 'achievementXP': -1},
                       {'originalXP': MAX_RECORD_INTEGER + 1, 'achievementXP': 0},
                       {'originalXP': 100, 'achievementXP': 0.1},
                       {'baseXP': 100, 'premiumXPFactor100': 150},
                       {'xp': 150, 'premiumXPFactor100': 150}):
            self.assertIsNone(self.normalize(values)['xp_base'])

    def test_net_income_is_not_guessed_from_incomplete_costs(self):
        record = self.normalize({'credits': 1000, 'repair': 200,
                                 'autoAmmoCost': [100, 0], 'creditsNet': 700})
        self.assertEqual(record['credits_gross'], 1000)
        self.assertIsNone(record['credits_net'])

    def test_complete_own_random_result_gets_economy_with_verified_avatar(self):
        from test_economy import complete_personal, complete_avatar
        personal = dict(complete_personal(), damageDealt=83, team=1)
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 1, 'bonusType': 1},
                   'personal': {42: personal, 'avatar': complete_avatar()}}
        context = {'account_id': '88', 'player_vehicle_id': 42}
        result = normalize_result(payload, context, observed_at=1700000000)
        self.assertEqual((result['xp_base'], result['xp_bonus'], result['credits_net']),
                         (900, 700, 14328))
        self.assertEqual(result['data_status'], 'complete')
        for owner in (99, None, True, 0):
            payload['personal']['avatar']['accountDBID'] = owner
            result = normalize_result(payload, context, observed_at=1700000000)
            self.assertIsNone(result['credits_net'])
            self.assertEqual(result['xp_bonus'], 700)

    def test_avatar_credit_events_are_not_repeated_across_multiple_vehicles(self):
        from test_economy import complete_personal, complete_avatar
        personal = dict(complete_personal(), damageDealt=83, team=1)
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 1, 'bonusType': 1},
                   'personal': {42: personal, 43: dict(personal), 'avatar': complete_avatar()}}
        result = normalize_result(payload, {'account_id': '88', 'player_vehicle_id': 42},
                                  observed_at=1700000000)
        self.assertIsNone(result['credits_net'])

    def test_no_received_xp_cannot_invent_bonus_from_the_legacy_base_xp_fallback(self):
        result = self.normalize({'xp': None, 'baseXP': 600,
                                 'originalXP': 700, 'achievementXP': 100})
        self.assertEqual(result['xp'], 600)
        self.assertEqual(result['xp_base'], 600)
        self.assertIsNone(result['xp_bonus'])

    def test_invalid_optional_payload_values_do_not_erase_primary_stats(self):
        record = self.normalize({'kills': True, 'shots': -1,
                                 'directHits': 1.5, 'piercings': 'broken',
                                 'credits': MAX_RECORD_INTEGER + 1},
                                {'arenaTypeID': False})
        self.assertEqual(record['data_status'], 'complete')
        for name in ('kills', 'shots', 'direct_hits', 'penetrations', 'credits_gross', 'map'):
            self.assertIsNone(record[name])

    def test_map_identifier_must_be_positive_and_bounded(self):
        for value in (None, 0, -1, True, False, '', 'malinovka',
                      MAX_RECORD_INTEGER + 1, 1.5):
            self.assertIsNone(self.normalize(common={'arenaTypeID': value})['map'])

    def test_canonical_signed_income_and_false_survival_survive_validation(self):
        record = validate_record({'arena_id': '1', 'credits_net': -500,
                                  'survived': False, 'map': 'arena:11',
                                  'shots': 0, 'kills': 0})
        self.assertEqual(record['credits_net'], -500)
        self.assertIs(record['survived'], False)
        self.assertEqual(record['shots'], 0)
        self.assertEqual(record['kills'], 0)
        self.assertEqual(record['data_status'], 'incomplete')

    def test_malformed_canonical_optional_fields_are_rejected(self):
        for name, value in (('survived', 0), ('survived', 'false'),
                            ('credits_net', True), ('credits_net', 1.5),
                            ('credits_net', MAX_RECORD_INTEGER + 1),
                            ('credits_net', -MAX_RECORD_INTEGER - 2),
                            ('map', 123), ('map', 'x' * 129),
                            ('kills', -1), ('xp_base', False), ('xp_bonus', False),
                            ('xp_bonus', -1), ('xp_bonus', MAX_RECORD_INTEGER + 1)):
            self.assertIsNone(validate_record(dict(arena_id='1', **{name: value})), name)

    def test_optional_fields_do_not_change_primary_completeness(self):
        record = validate_record({'arena_id': '1', 'kills': 0, 'shots': 0,
                                  'xp_base': 0, 'xp_bonus': 0, 'credits_gross': 0,
                                  'credits_net': 0, 'survived': False})
        self.assertEqual(record['data_status'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
