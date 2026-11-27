# -*- coding: utf-8 -*-
"""Pure, Python 2.7-compatible normalization and statistics.

No game imports and no dependency on a running client. Invalid or missing
metrics never turn into plausible-looking zeros. Schema v1 is unchanged.
"""
from __future__ import division
import time
from datetime import datetime

from .economy import derive_economy
from .vehicles import (coherent_identity, identity_from_internal_name,
                       identity_from_type_descr, normalize_vehicle_id,
                       nation_for_identity, normalize_vehicle_metadata,
                       VEHICLE_METADATA_FIELDS)

try:
    _text_type = unicode
except NameError:
    _text_type = str

# Storage accepts nonnegative signed 64-bit numbers for metrics/timestamps.
# Arena/account identifiers are text and are not subject to this metric limit.
# The bound rejects corrupt giant JSON integers before float-based statistics.
MAX_RECORD_INTEGER = (1 << 63) - 1


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
    """Accept 0..2**63-1 integral values; reject bools, fractions and overflow."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        if number < 0 or number > MAX_RECORD_INTEGER:
            return None
        # Prevent truncation of floats / Decimal-like values.
        if not isinstance(value, (bytes, _text_type, int, long_type)) and value != number:
            return None
        return number
    except (ValueError, TypeError, OverflowError):
        return None


def _signed_int(value):
    """Signed 64-bit local metrics, including a known negative net income."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        if number < -MAX_RECORD_INTEGER - 1 or number > MAX_RECORD_INTEGER:
            return None
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
    if (value is None or isinstance(value, bool) or
            not isinstance(value, (bytes, _text_type, int, long_type))):
        return None
    if isinstance(value, (int, long_type)) and value <= 0:
        return None
    identifier = _as_text(value).strip()
    if not identifier or identifier == '0' or len(identifier) > 128:
        return None
    return identifier


def record_is_complete(record):
    """Completeness of the three primary statistics, not all client fields.

    An outcome, damage and XP must be known. Zero damage/XP is valid;
    assistance is optional and never replaced by a fabricated zero.
    """
    return (isinstance(record, dict) and
            record.get('outcome') in ('win', 'loss', 'draw') and
            _non_negative_int(record.get('damage')) is not None and
            _non_negative_int(record.get('xp')) is not None)


def _record_text(value, default, limit):
    if value is None or value == '':
        return default
    if not isinstance(value, (bytes, _text_type)):
        raise ValueError('Expected a text field')
    text = _as_text(value).strip()
    if len(text) > limit:
        raise ValueError('Text field is too long')
    return text or default


def validate_record(record):
    """Return a safe schema-1 snapshot, or None for invalid external input.

    Legacy minimal records without a schema/version are still accepted.
    Missing measurements remain None. Unknown schema versions and malformed
    field types are rejected; the caller keeps their original journal lines.
    Only this documented schema is exposed to the dashboard. Completeness is
    derived again, so an imported data_status cannot claim missing data exists.
    """
    try:
        return _validate_record(record)
    except (ValueError, TypeError, OverflowError):
        return None


def _validate_record(record):
    if not isinstance(record, dict):
        raise ValueError('A battle record must be an object')
    schema = record.get('schema', 1)
    if isinstance(schema, bool) or not isinstance(schema, (int, long_type)) or schema != 1:
        raise ValueError('Unsupported battle-record schema')
    arena = _arena_id(record.get('arena_id'))
    if arena is None:
        raise ValueError('A battle needs a valid arena_id')
    account = record.get('account_id')
    if isinstance(account, bool):
        raise ValueError('Invalid account_id')
    if account is None or account == 0:
        account = 'local'
    elif isinstance(account, (int, long_type)):
        if account < 0:
            raise ValueError('Invalid account_id')
        account = _as_text(account)
    account = _record_text(account, 'local', 128)
    outcome = record.get('outcome')
    if outcome is None:
        outcome = 'unknown'
    if not isinstance(outcome, (bytes, _text_type)):
        raise ValueError('Invalid outcome type')
    outcome = _as_text(outcome)
    if outcome not in ('win', 'loss', 'draw', 'unknown'):
        raise ValueError('Invalid outcome')
    clean = {
        'schema': 1, 'arena_id': arena, 'account_id': account,
        'vehicle': _record_text(record.get('vehicle'), 'unknown', 256),
        'mode': _record_text(record.get('mode'), 'unknown', 128),
        'outcome': outcome,
    }
    identity = record.get('vehicle_id')
    clean['vehicle_id'] = normalize_vehicle_id(identity)
    if identity is not None and clean['vehicle_id'] is None:
        raise ValueError('Invalid vehicle_id')
    metadata = normalize_vehicle_metadata(record, clean['vehicle_id'])
    for name in VEHICLE_METADATA_FIELDS:
        if record.get(name) is not None and metadata[name] is None:
            raise ValueError('Invalid vehicle metadata: ' + name)
        clean[name] = metadata[name]
    for name in ('timestamp', 'damage', 'assistance_radio', 'assistance_track', 'xp',
                 'kills', 'shots', 'direct_hits', 'penetrations', 'xp_base', 'xp_bonus',
                 'credits_gross'):
        value = record.get(name)
        number = _non_negative_int(value)
        if value is not None and number is None:
            raise ValueError('Invalid numeric field: ' + name)
        clean[name] = number
    clean['map'] = _record_text(record.get('map'), None, 128)
    clean['map_label'] = _record_text(record.get('map_label'), None, 128)
    if clean['map_label'] is not None and clean['map'] is None:
        raise ValueError('A map label needs a map identity')
    value = record.get('credits_net')
    clean['credits_net'] = _signed_int(value)
    if value is not None and clean['credits_net'] is None:
        raise ValueError('Invalid numeric field: credits_net')
    survived = record.get('survived')
    if survived is not None and not isinstance(survived, bool):
        raise ValueError('Invalid survived field')
    clean['survived'] = survived
    clean['data_status'] = 'complete' if record_is_complete(clean) else 'incomplete'
    return clean


def _find_personal(results, player_vehicle_id, allow_singleton=False,
                   account_id=None):
    """Select only an unambiguously OWN personal entry.

    Game builds may index the own entry by account ID rather than Avatar
    vehicle ID; 'avatar' may coexist as an unrelated metadata entry. Never
    select a random participant when multiple candidate entries remain.
    """
    personal = results.get('personal')
    if not isinstance(personal, dict):
        return None
    if any(key in personal for key in ('damageDealt', 'xp', 'credits', 'vehicleType')):
        return personal  # Already flattened player-only result.

    matches = []
    for identifier in (account_id, player_vehicle_id):
        if identifier is None:
            continue
        for key, item in personal.items():
            if (_as_text(key) == _as_text(identifier) and
                    isinstance(item, dict) and
                    not any(item is old for old in matches)):
                matches.append(item)
    if len(matches) > 1:
        return None
    if matches:
        return matches[0]

    # A confirmed-own client event can have exactly one per-player entry plus
    # the separately keyed avatar metadata. Without confirmation, keep the
    # old exact-singleton behavior; neither path selects 'avatar' itself.
    candidates = [item for key, item in personal.items()
                  if _as_text(key) != 'avatar' and isinstance(item, dict)]
    if len(candidates) == 1 and (allow_singleton or
                                 (account_id is None and
                                  player_vehicle_id is None and
                                  len(personal) == 1)):
        return candidates[0]
    return None


def result_rejection_reason(results, context=None):
    """Return a fixed category only: no account IDs, names or raw payloads."""
    if not isinstance(results, dict):
        return 'payload_not_mapping'
    common = results.get('common')
    if _arena_id(_get_first(results, ('arenaUniqueID', 'arenaId'))) is None:
        if _arena_id(_get_first(common, ('arenaUniqueID', 'arenaId'))) is None:
            return 'arena_id_unavailable'
    if not isinstance(results.get('personal'), dict):
        return 'personal_map_unavailable'
    context = context if isinstance(context, dict) else {}
    match = _find_personal(results,
                           context.get('player_vehicle_id'),
                           context.get('confirmed_own_result') is True,
                           context.get('account_id'))
    if match is None:
        return 'own_personal_entry_unavailable'
    return 'record_validation_failed'


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
                              context.get('confirmed_own_result') is True,
                              context.get('account_id'))
    if personal is None:
        return None
    account = context.get('account_id')
    if account is None:
        account = 'local'
    result_name = _get_first(personal, ('vehicleName', 'vehicleType'))
    vehicle = context.get('vehicle_name') or result_name or 'unknown'
    # Entity/playerVehicleID selects the own result; it is never a type ID.
    # Pending battle context and the result must agree when both are known.
    captured_identity = normalize_vehicle_id(context.get('vehicle_id'))
    if context.get('vehicle_id') is not None and captured_identity is None:
        return None
    try:
        vehicle_identity = coherent_identity((
            captured_identity,
            identity_from_type_descr(personal.get('typeCompDescr')),
            identity_from_internal_name(context.get('vehicle_name')),
            identity_from_internal_name(result_name),
        ))
    except ValueError:
        return None

    player_team = _get_first(personal, ('team',))
    if player_team is None:
        # The full result may store the own team in personal.avatar rather
        # than the vehicle entry. Trust it only for the verified account.
        avatar = results['personal'].get('avatar')
        if (isinstance(avatar, dict) and context.get('account_id') is not None
                and _as_text(avatar.get('accountDBID')) == _as_text(context['account_id'])):
            player_team = _get_first(avatar, ('team',))
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
    arena_type = _non_negative_int(common.get('arenaTypeID'))
    death_reason = _signed_int(personal.get('deathReason'))
    survived = None
    if death_reason is not None and death_reason >= -1:
        survived = death_reason == -1
    # Avatar credit rewards belong to the whole account result. Include them
    # only for an identity-confirmed single vehicle in a supported battle mode.
    personal_map = results['personal']
    avatar = personal_map.get('avatar')
    own_account = _non_negative_int(context.get('account_id'))
    avatar_account = (_non_negative_int(avatar.get('accountDBID'))
                      if isinstance(avatar, dict) else None)
    verified_avatar = (avatar if own_account is not None and own_account > 0 and
                       avatar_account == own_account else None)
    vehicle_entries = [item for key, item in personal_map.items() if key != 'avatar']
    single_vehicle = len(vehicle_entries) == 1 and vehicle_entries[0] is personal
    economics = derive_economy(personal, verified_avatar, single_vehicle, mode)
    # Only a captured, identity-checked own type may contribute battle-start
    # metadata. A current hangar vehicle must never label an older result.
    metadata = normalize_vehicle_metadata(
        context if captured_identity is not None else {}, vehicle_identity)
    metadata['vehicle_nation'] = nation_for_identity(vehicle_identity)
    record = {
        'schema': 1,
        'arena_id': identifier,
        'account_id': _as_text(account),
        'timestamp': when,
        'vehicle': _as_text(vehicle),
        'vehicle_id': vehicle_identity,
        'mode': _as_text(mode if mode is not None else 'unknown'),
        'outcome': outcome,
        'damage': _non_negative_int(_get_first(personal, ('damageDealt',))),
        'assistance_radio': _non_negative_int(_get_first(personal, ('damageAssistedRadio',))),
        'assistance_track': _non_negative_int(_get_first(personal, ('damageAssistedTrack',))),
        'xp': _non_negative_int(_get_first(personal, ('xp', 'baseXP'))),
        'map': 'arena:%s' % arena_type if arena_type else None,
        'kills': _non_negative_int(personal.get('kills')),
        'shots': _non_negative_int(personal.get('shots')),
        'direct_hits': _non_negative_int(personal.get('directHits')),
        'penetrations': _non_negative_int(personal.get('piercings')),
        'survived': survived,
        'xp_base': economics['xp_base'],
        'xp_bonus': economics['xp_bonus'],
        'credits_gross': _non_negative_int(personal.get('credits')),
        'credits_net': economics['credits_net'],
    }
    record.update(metadata)
    return validate_record(record)


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
