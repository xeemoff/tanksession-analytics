# -*- coding: utf-8 -*-
"""Known-component economics for the reference 1.46 client (Python 2.7).

Reference revision: e241d4d04d610f0747271ff6f044ee809a607b53 in
https://github.com/StranikS-Scan/WorldOfTanks-Decompiled

client/gui/battle_results/components/details.py: MoneyDetailsBlock's total
uses credits, the two draw deductions, avatar credit events and three actual
credit auto-service costs. reusable/personal.py defines the signs, currency
tuple indexes and premium/squad rounding. common/ValueReplay.py updates the
raw credits accumulator with its bonus/penalty operations; do not add those
components or deduct their penalties a second time.

templates/ranked_battles.py clones the regular personal block, replacing only
the vehicle statistics at index 8; index 6 retains TotalMoneyDetailsBlock.
The same verified pipeline therefore applies to bonus types 1, 22 and 24.

The net value is scoped to one vehicle in a supported result with an
identity-verified avatar supplied by the caller. It counts actual credit
charges, not the replacement value of items taken from the depot, and excludes
gold, bonds and future piggy-bank income. Missing values never imply zero.

xp_bonus means received XP above the base row after all applied adjustments:
xp - (originalXP - achievementXP). It is not an itemized sum of boosters, crew
XP or free XP. A negative difference is unknown, never clamped to zero.
"""
import math

MAX_INTEGER = (1 << 63) - 1
MAX_EXACT_FLOAT_INTEGER = (1 << 53) - 1
MAX_CREDIT_EVENTS = 1024
SUPPORTED_BONUS_TYPES = (1, 22, 24)

try:
    _integer_types = (int, long)
except NameError:
    _integer_types = (int,)


def _known_integer(value):
    # These client fields are integer measurements, not formatted UI text.
    if (isinstance(value, bool) or not isinstance(value, _integer_types) or
            not 0 <= value <= MAX_INTEGER):
        return None
    return value


def _rounded_factor(value, factor):
    """Match positive Python 2.7 round(value * (factor / 100.0)).

    Keep its floating multiplication and ties-away-from-zero behavior across
    Python versions. Reject magnitudes where the reference float cannot
    distinguish adjacent integer charges instead of inventing precision.
    """
    if value > MAX_EXACT_FLOAT_INTEGER or factor > MAX_EXACT_FLOAT_INTEGER:
        return None
    product = value * (factor / 100.0)
    if product > MAX_EXACT_FLOAT_INTEGER:
        return None
    fraction, whole = math.modf(product)
    return int(whole) + (1 if fraction >= 0.5 else 0)


def _credit_cost(value, size):
    # Money tuple positions are (credits, gold[, crystal]); never sum them.
    if not isinstance(value, (tuple, list)) or len(value) != size:
        return None
    numbers = [_known_integer(item) for item in value]
    return numbers[0] if all(item is not None for item in numbers) else None


def _avatar_credit_events(avatar):
    if not isinstance(avatar, dict):
        return None
    events = avatar.get('eventCreditsList')
    if not isinstance(events, (tuple, list)) or len(events) > MAX_CREDIT_EVENTS:
        return None
    total = 0
    for event in events:
        if not isinstance(event, (tuple, list)) or len(event) != 2:
            return None
        value = _known_integer(event[1])
        if value is None:
            return None
        total += value
        if total > MAX_INTEGER:
            return None
    return total


def _net_credits(personal, avatar, single_vehicle, bonus_type):
    if (single_vehicle is not True or
            _known_integer(bonus_type) not in SUPPORTED_BONUS_TYPES):
        return None
    if 'rolloutsCount' in personal:
        rollouts = _known_integer(personal['rolloutsCount'])
        if rollouts is None or rollouts > 1:
            return None
    fields = ('credits', 'originalCreditsToDraw', 'appliedPremiumCreditsFactor100',
              'originalCreditsToDrawSquad', 'premSquadCreditsFactor100',
              'autoRepairCost')
    values = dict((name, _known_integer(personal.get(name))) for name in fields)
    if any(value is None for value in values.values()):
        return None
    # Unlike a known zero squad bonus, zero is not a known premium multiplier.
    if values['appliedPremiumCreditsFactor100'] == 0:
        return None
    load = _credit_cost(personal.get('autoLoadCost'), 2)
    equip = _credit_cost(personal.get('autoEquipCost'), 3)
    events = _avatar_credit_events(avatar)
    if load is None or equip is None or events is None:
        return None
    draw = _rounded_factor(values['originalCreditsToDraw'],
                           values['appliedPremiumCreditsFactor100'])
    squad_draw = _rounded_factor(values['originalCreditsToDrawSquad'],
                                 values['premSquadCreditsFactor100'])
    if draw is None or squad_draw is None:
        return None
    result = (values['credits'] - draw - squad_draw + events -
              values['autoRepairCost'] - load - equip)
    return result if -MAX_INTEGER - 1 <= result <= MAX_INTEGER else None


def derive_economy(personal, avatar=None, single_vehicle=False, bonus_type=None):
    """Return optional xp_base, xp_bonus and signed credits_net values.

    The caller must verify avatar.accountDBID against the current own context
    and pass single_vehicle=True only for exactly one personal vehicle entry.
    Avatar-wide rewards are not allocated across several vehicles or respawns.
    Every credit component, including an explicitly empty event list, must be
    present. The reference mapping still requires validation in the live game.
    """
    result = {'xp_base': None, 'xp_bonus': None, 'credits_net': None}
    if not isinstance(personal, dict):
        return result
    original = _known_integer(personal.get('originalXP'))
    achievement = _known_integer(personal.get('achievementXP'))
    total = _known_integer(personal.get('xp'))
    if original is not None and achievement is not None and original >= achievement:
        base = original - achievement
        result['xp_base'] = base
        if total is not None and total >= base:
            result['xp_bonus'] = total - base
    result['credits_net'] = _net_credits(personal, avatar, single_vehicle, bonus_type)
    return result
