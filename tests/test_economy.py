# -*- coding: utf-8 -*-
"""Known components, real charges and currency isolation in economy records."""
import copy
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))

from tanksession_analytics.economy import derive_economy, MAX_INTEGER


def complete_personal():
    return {'xp': 1600, 'originalXP': 1000, 'achievementXP': 100,
            'credits': 20000, 'originalCreditsToDraw': 101,
            'appliedPremiumCreditsFactor100': 150,
            'originalCreditsToDrawSquad': 203, 'premSquadCreditsFactor100': 10,
            'autoRepairCost': 3000, 'autoLoadCost': (2500, 99),
            'autoEquipCost': (1000, 25, 500)}


def complete_avatar():
    return {'accountDBID': 88, 'eventCreditsList': [('mission-a', 700), ('mission-b', 300)]}


def calculate(personal=None, avatar=None, **kwargs):
    if personal is None:
        personal = complete_personal()
    if avatar is None:
        avatar = complete_avatar()
    options = {'single_vehicle': True, 'bonus_type': 1}
    options.update(kwargs)
    return derive_economy(personal, avatar, **options)


class EconomyTests(unittest.TestCase):
    def test_complete_reference_components_include_events_and_draw_deductions_once(self):
        personal, avatar = complete_personal(), complete_avatar()
        original = copy.deepcopy((personal, avatar))
        result = calculate(personal, avatar)
        # 20,000 - round(101*1.5) - round(203*0.1) + 1,000 - 3,000 - 2,500 - 1,000
        self.assertEqual(result, {'xp_base': 900, 'xp_bonus': 700, 'credits_net': 14328})
        self.assertEqual((personal, avatar), original)

    def test_explicit_zeroes_are_observations(self):
        personal = dict((name, 0) for name in complete_personal())
        personal.update(appliedPremiumCreditsFactor100=100,
                        autoLoadCost=(0, 0), autoEquipCost=(0, 0, 0))
        self.assertEqual(calculate(personal, {'eventCreditsList': []}),
                         {'xp_base': 0, 'xp_bonus': 0, 'credits_net': 0})

    def test_costs_may_make_the_net_income_negative(self):
        personal = dict(complete_personal(), credits=1000,
                        originalCreditsToDraw=0, originalCreditsToDrawSquad=0)
        self.assertEqual(calculate(personal, {'eventCreditsList': []})['credits_net'], -5500)

    def test_gold_bonds_and_piggy_bank_are_not_credit_income_or_costs(self):
        personal = dict(complete_personal(), autoLoadCost=(2500, 9000000),
                        autoEquipCost=(1000, 8000000, 7000000),
                        gold=6000000, crystal=5000000, piggyBank=4000000,
                        autoEquipBoostersCost=(3000000, 2000000, 1000000))
        avatar = dict(complete_avatar(), eventGoldList=[('gold', 9000000)],
                      eventCrystalList=[('bonds', 8000000)])
        self.assertEqual(calculate(personal, avatar)['credits_net'], 14328)

    def test_only_actual_auto_service_costs_are_deducted(self):
        personal = dict(complete_personal(), repair=9000000,
                        autoAmmoCost=(8000000, 0), creditsNet=7000000)
        self.assertEqual(calculate(personal)['credits_net'], 14328)
        # A known zero charge can mean resupply from the depot. Do not invent
        # its replacement price from repair/damage/ammunition statistics.
        personal.update(autoRepairCost=0, autoLoadCost=(0, 99),
                        autoEquipCost=(0, 25, 500))
        self.assertEqual(calculate(personal)['credits_net'], 20828)

    def test_final_credit_accumulator_does_not_apply_bonuses_and_penalties_twice(self):
        personal = dict(complete_personal(), creditsPenalty=500,
                        originalCreditsPenalty=500, creditsContributionIn=300,
                        creditsContributionOut=200, achievementCredits=100,
                        boosterCredits=1000, teamSubsBonusCredits=700,
                        directivesCredits=600)
        self.assertEqual(calculate(personal)['credits_net'], 14328)

    def test_missing_or_null_credit_component_never_becomes_zero(self):
        fields = ('credits', 'originalCreditsToDraw', 'appliedPremiumCreditsFactor100',
                  'originalCreditsToDrawSquad', 'premSquadCreditsFactor100',
                  'autoRepairCost', 'autoLoadCost', 'autoEquipCost')
        for field in fields:
            missing = complete_personal()
            del missing[field]
            self.assertIsNone(calculate(missing)['credits_net'], field)
            missing[field] = None
            self.assertIsNone(calculate(missing)['credits_net'], field)
        for avatar in ({}, {'eventCreditsList': None}):
            self.assertIsNone(calculate(avatar=avatar)['credits_net'])
        self.assertIsNone(derive_economy(complete_personal(), None,
                                        single_vehicle=True, bonus_type=1)['credits_net'])

    def test_invalid_integer_components_are_not_truncated_or_coerced(self):
        for field in ('credits', 'autoRepairCost', 'originalCreditsToDraw',
                      'appliedPremiumCreditsFactor100', 'originalCreditsToDrawSquad',
                      'premSquadCreditsFactor100'):
            for invalid in (True, False, -1, 0.5, 100.0, '100', MAX_INTEGER + 1):
                personal = dict(complete_personal(), **{field: invalid})
                self.assertIsNone(calculate(personal)['credits_net'], (field, invalid))
        self.assertIsNone(calculate(dict(complete_personal(),
                              appliedPremiumCreditsFactor100=0))['credits_net'])

    def test_currency_tuple_shape_and_values_must_be_known(self):
        for field, invalid in (('autoLoadCost', (100,)), ('autoLoadCost', (100, 0, 0)),
                               ('autoLoadCost', {'credits': 100, 'gold': 0}),
                               ('autoLoadCost', (None, 0)), ('autoLoadCost', (True, 0)),
                               ('autoLoadCost', (-100, 0)), ('autoEquipCost', (100, 0)),
                               ('autoEquipCost', (100, 0, None)),
                               ('autoEquipCost', (100.5, 0, 0))):
            self.assertIsNone(calculate(dict(complete_personal(), **{field: invalid}))[
                              'credits_net'], (field, invalid))
        personal = dict(complete_personal(), autoLoadCost=[2500, 99],
                        autoEquipCost=[1000, 25, 500])
        self.assertEqual(calculate(personal)['credits_net'], 14328)

    def test_avatar_event_list_must_be_complete_and_bounded(self):
        invalid_lists = [None, {}, [100], [('event',)], [('event', None)],
                         [('event', True)], [('event', -1)], [('event', 1.5)],
                         [('event', MAX_INTEGER + 1)], [('event', 1)] * 1025,
                         [('one', MAX_INTEGER), ('two', 1)]]
        for events in invalid_lists:
            self.assertIsNone(calculate(avatar={'eventCreditsList': events})['credits_net'])

    def test_reference_rounding_is_consistent_at_half_credit_boundaries(self):
        personal = dict(complete_personal(), credits=100, originalCreditsToDraw=1,
                        originalCreditsToDrawSquad=5, autoRepairCost=0,
                        autoLoadCost=(0, 0), autoEquipCost=(0, 0, 0))
        # Python 2.7 rounds 1.5 -> 2 and 0.5 -> 1. Python 3 round() differs.
        self.assertEqual(calculate(personal, {'eventCreditsList': []})['credits_net'], 97)

    def test_overflow_or_unsafe_rounding_returns_unknown(self):
        for fields in ({'originalCreditsToDraw': (1 << 53)},
                       {'originalCreditsToDraw': 1 << 52,
                        'appliedPremiumCreditsFactor100': 1000},
                       {'credits': MAX_INTEGER},
                       {'autoRepairCost': MAX_INTEGER, 'autoLoadCost': (MAX_INTEGER, 0),
                        'autoEquipCost': (MAX_INTEGER, 0, 0)}):
            personal = dict(complete_personal(), **fields)
            avatar = {'eventCreditsList': [('large', MAX_INTEGER)]}
            self.assertIsNone(calculate(personal, avatar)['credits_net'], fields)

    def test_account_rewards_are_not_allocated_to_multi_vehicle_or_special_results(self):
        for value in (False, None, 1):
            self.assertIsNone(calculate(single_vehicle=value)['credits_net'])
        for mode in (None, 0, 2, 27, 29, 30, True, '1', 1.0):
            self.assertIsNone(calculate(bonus_type=mode)['credits_net'])
        self.assertEqual(calculate(bonus_type=24)['credits_net'], 14328)
        for rollouts in (2, 3, None, True):
            self.assertIsNone(calculate(dict(complete_personal(), rolloutsCount=rollouts))[
                              'credits_net'])

    def test_bonus_is_received_xp_above_base_not_an_assumed_premium_multiplier(self):
        personal = {'xp': 1200, 'originalXP': 1000, 'achievementXP': 100,
                    'premiumXPFactor100': 500, 'freeXP': 9000, 'tmenXP': 8000}
        result = derive_economy(personal)
        self.assertEqual((result['xp_base'], result['xp_bonus']), (900, 300))
        self.assertIsNone(result['credits_net'])

    def test_bonus_requires_actual_total_and_both_base_components(self):
        for field in ('xp', 'originalXP', 'achievementXP'):
            for invalid in (None, True, False, -1, 0.5, '100', MAX_INTEGER + 1):
                personal = dict(complete_personal(), **{field: invalid})
                self.assertIsNone(derive_economy(personal)['xp_bonus'], (field, invalid))
            personal = complete_personal()
            del personal[field]
            self.assertIsNone(derive_economy(personal)['xp_bonus'], field)
        self.assertIsNone(derive_economy({'baseXP': 900, 'originalXP': 1000,
                                        'achievementXP': 100})['xp_bonus'])

    def test_negative_xp_difference_is_unknown_not_a_false_zero_bonus(self):
        result = derive_economy({'xp': 500, 'originalXP': 1000, 'achievementXP': 0})
        self.assertEqual(result['xp_base'], 1000)
        self.assertIsNone(result['xp_bonus'])
        result = derive_economy({'xp': 1000, 'originalXP': 100, 'achievementXP': 101})
        self.assertIsNone(result['xp_base'])
        self.assertIsNone(result['xp_bonus'])
        self.assertEqual(derive_economy({'xp': 900, 'originalXP': 1000,
                                        'achievementXP': 100})['xp_bonus'], 0)

    def test_non_mapping_input_is_unknown(self):
        for value in (None, [], 1, 'invalid'):
            self.assertEqual(derive_economy(value),
                             {'xp_base': None, 'xp_bonus': None, 'credits_net': None})


if __name__ == '__main__':
    unittest.main()
