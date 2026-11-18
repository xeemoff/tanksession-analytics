# -*- coding: utf-8 -*-
"""Pure, Python 2.7-compatible normalization and statistics.

No game imports and no dependency on a running client. Invalid or missing
metrics never turn into plausible-looking zeros. Schema v1 is unchanged.
"""
from __future__ import division
import time
from datetime import datetime

try:
    _text_type = unicode
except NameError:
    _text_type = str


def _as_text(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    try:
        return _text_type(value)
    except (UnicodeError, TypeError, ValueError):
        return _text_type(repr(value))


def _get_first(data, names):
    if isinstance(data, dict):
        for name in names:
            value = data.get(name)
            if value is not None:
                return value
    return None


def _non_negative_int(value):
    """Accept nonnegative, integral values; reject booleans and fractions."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        if number < 0:
            return None
        # Prevent truncation of floats / Decimal-like values.
        if not isinstance(value, (bytes, _text_type, int, long_type)) and value != number:
            return None
        return number
    except (ValueError, TypeError, OverflowError):
        return None


try:
    long_type = long
except NameError:
    long_type = int


def _arena_id(value):
    if value is None or isinstance(value, bool):
        return None
    identifier = _as_text(value).strip()
    if not identifier or identifier == '0':
        return None
    return identifier


def _find_personal(results, player_vehicle_id, allow_singleton=False):
    """Only accept an unambiguously matching personal entry.

    A *provided* key that does not match does not silently fall back unless
    the caller independently confirmed this is the player's own result.
    """
    personal = results.get('personal')
    if not isinstance(personal, dict):
        return None
    if any(key in personal for key in ('damageDealt', 'xp', 'credits', 'vehicleType')):
        return personal  # Already flattened player-only result.
    if player_vehicle_id is not None:
        for key, item in personal.items():
            if _as_text(key) == _as_text(player_vehicle_id) and isinstance(item, dict):
                return item
        if not allow_singleton:
            return None
    if len(personal) == 1:
        only = next(iter(personal.values()))
        if isinstance(only, dict):
            return only
    return None


def normalize_result(results, context=None, observed_at=None):
    """Convert an unverified game-result payload into a minimal record.

    Returns None for missing identifiers, ambiguous players or invalid input.
    Client field names still require validation against the installed Lesta
    build; no guesses about undocumented data are made here.
    """
    if not isinstance(results, dict):
        return None
    if not isinstance(context, dict):
        context = {}
    common = results.get('common')
    if not isinstance(common, dict):
        common = {}
    identifier = _arena_id(_get_first(results, ('arenaUniqueID', 'arenaId')))
    if identifier is None:
        identifier = _arena_id(_get_first(common, ('arenaUniqueID', 'arenaId')))
    if identifier is None:
        return None

    personal = _find_personal(results, context.get('player_vehicle_id'),
                              context.get('confirmed_own_result') is True)
    if personal is None:
        return None
    account = context.get('account_id')
    if account is None:
        account = 'local'
    vehicle = context.get('vehicle_name') or _get_first(personal, ('vehicleName', 'vehicleType')) or 'unknown'

    player_team = _get_first(personal, ('team',))
    if player_team is None:
        player_team = context.get('team')
    winner = _get_first(common, ('winnerTeam',))
    if winner is None:
        winner = _get_first(results, ('winnerTeam',))
    player_team = _non_negative_int(player_team)
    winner = _non_negative_int(winner)
    outcome = 'unknown'
    if player_team is not None and winner is not None:
        if winner == 0:
            outcome = 'draw'
        elif winner == player_team:
            outcome = 'win'
        else:
            outcome = 'loss'

    when = int(time.time()) if observed_at is None else _non_negative_int(observed_at)
    if when is None:
        return None
    mode = _get_first(common, ('bonusType',))
    return {
        'schema': 1,
        'arena_id': identifier,
        'account_id': _as_text(account),
        'timestamp': when,
        'vehicle': _as_text(vehicle),
        'mode': _as_text(mode if mode is not None else 'unknown'),
        'outcome': outcome,
        'damage': _non_negative_int(_get_first(personal, ('damageDealt',))),
        'assistance_radio': _non_negative_int(_get_first(personal, ('damageAssistedRadio',))),
        'assistance_track': _non_negative_int(_get_first(personal, ('damageAssistedTrack',))),
        'xp': _non_negative_int(_get_first(personal, ('xp', 'baseXP'))),
    }


def summarize(records):
    records = [r for r in records if isinstance(r, dict)]
    outcomes = [r['outcome'] for r in records if r.get('outcome') in ('win', 'loss', 'draw')]
    # Use converted numbers, NOT the original values. JSON imports may contain
    # strings: e.g. "1000" is valid while "invalid" is excluded.
    damage = [_non_negative_int(r.get('damage')) for r in records]
    damage = [v for v in damage if v is not None]
    xp = [_non_negative_int(r.get('xp')) for r in records]
    xp = [v for v in xp if v is not None]
    wins = outcomes.count('win')
    return {
        'battles': len(records),
        'known_outcomes': len(outcomes),
        'wins': wins,
        'losses': outcomes.count('loss'),
        'draws': outcomes.count('draw'),
        'win_rate': round(100.0 * wins / len(outcomes), 1) if outcomes else None,
        'avg_damage': round(sum(damage) / len(damage), 1) if damage else None,
        'avg_xp': round(sum(xp) / len(xp), 1) if xp else None,
        'damage_samples': len(damage),
    }


def by_vehicle(records):
    buckets = {}
    for record in records:
        if isinstance(record, dict):
            vehicle = _as_text(record.get('vehicle') or 'unknown')
            buckets.setdefault(vehicle, []).append(record)
    return dict((name, summarize(items)) for name, items in buckets.items())


def by_day(records):
    buckets = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        stamp = _non_negative_int(record.get('timestamp'))
        if stamp is None:
            continue
        try:
            day = datetime.fromtimestamp(stamp).strftime('%Y-%m-%d')
        except (ValueError, OverflowError, OSError):
            continue
        buckets.setdefault(day, []).append(record)
    return dict((day, summarize(items)) for day, items in buckets.items())
