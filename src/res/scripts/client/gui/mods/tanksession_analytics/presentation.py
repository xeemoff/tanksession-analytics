# -*- coding: utf-8 -*-
"""Versioned, bounded data snapshots for the optional hangar interface.

This module has no game imports and is compatible with Python 2.7. Pass the
current logical records from BattleStore, not its append-only revision log.
Identity is checked before data is exposed. Account and arena identifiers
never cross the presentation boundary.
"""
import re
import time

from .analytics import rolling_damage, sort_records, vehicle_table, window_comparison
from .core import _as_text, long_type, record_is_complete, summarize, validate_record
from .goals import evaluate_goals, validate_goals
from .recorder import _verified_account

try:
    _text_types = (str, unicode)
except NameError:
    _text_types = (str,)

PROTOCOL_VERSION = 1
MAX_JS_INTEGER = (1 << 53) - 1
MAX_TIMESTAMP = 253402300799
MAX_VEHICLES = 2048
MAX_HISTORY = 12
MAX_SERIES = 60
_REQUEST_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,64}\Z')
_REQUEST_FIELDS = frozenset(('protocol', 'request_id', 'vehicle', 'window'))


def _text(value, limit, name):
    if not isinstance(value, _text_types):
        raise ValueError('%s must be text' % name)
    value = _as_text(value)
    if len(value) > limit:
        raise ValueError('%s is too long' % name)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValueError('%s contains invalid Unicode' % name)
    return value


def validate_request(request):
    """Validate protocol input; never accept an account selector from the UI."""
    if request is None:
        return {'protocol': PROTOCOL_VERSION, 'request_id': 'initial',
                'vehicle': '', 'window': 10}
    if not isinstance(request, dict) or set(request).difference(_REQUEST_FIELDS):
        raise ValueError('Unsupported request fields')
    protocol = request.get('protocol')
    if (isinstance(protocol, bool) or not isinstance(protocol, (int, long_type))
            or protocol != PROTOCOL_VERSION):
        raise ValueError('Unsupported presentation protocol')
    identifier = _text(request.get('request_id'), 64, 'request_id')
    if not _REQUEST_ID.match(identifier):
        raise ValueError('request_id must contain 1..64 ASCII identifier characters')
    window = request.get('window', 10)
    if (isinstance(window, bool) or not isinstance(window, (int, long_type))
            or window not in (10, 30, 100)):
        raise ValueError('Unsupported comparison window')
    vehicle = _text(request.get('vehicle', ''), 128, 'vehicle')
    return {'protocol': PROTOCOL_VERSION, 'request_id': identifier,
            'vehicle': vehicle, 'window': window}


def _confirmed_account(value):
    # Avoid validating a fabricated whole record for each account comparison.
    if (value is None or isinstance(value, bool) or
            not isinstance(value, _text_types + (bytes, int, long_type))):
        return None
    if isinstance(value, (int, long_type)) and value <= 0:
        return None
    account = _verified_account(value)
    if account is None or len(account) > 128:
        return None
    try:
        account.encode('utf-8')
    except UnicodeError:
        return None
    return account


def _counter(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, long_type))
            or value < 0 or value > MAX_JS_INTEGER):
        raise ValueError('Invalid diagnostic counter: %s' % name)
    return value


def _observed_time(now):
    value = int(time.time()) if now is None else now
    value = _counter(value, 'updated_at')
    if value > MAX_TIMESTAMP:
        raise ValueError('updated_at exceeds the supported calendar range')
    return value


def _empty_snapshot(request, source, now, status):
    return {
        'protocol': PROTOCOL_VERSION, 'source': source, 'status': status,
        'request_id': request['request_id'],
        'selection': {'vehicle': request['vehicle'], 'window': request['window']},
        'vehicles': [], 'summary': summarize([]),
        'comparison': window_comparison([], request['window']),
        'series': [], 'goals': [], 'history': [],
        'quality': {'total_records': 0, 'incomplete_records': 0,
                    'invalid_records': 0, 'conflicts': 0},
        'updated_at': now,
    }


def build_snapshot(records, account_id, request=None, goals=None, diagnostics=None,
                   source='game', now=None):
    """Return protocol-1 data for one confirmed account and one UI selection.

    ``total_records`` and ``incomplete_records`` describe the selected history.
    ``invalid_records`` includes invalid/malformed journal counters and records
    rejected by this boundary. ``conflicts`` is a journal diagnostic counter.
    No journal counters are exposed before a current account is confirmed.

    Invalid configuration/requests raise ValueError so the host can show an
    explicit error. Malformed own records are skipped and counted. Values
    outside JavaScript's exact integer range are rejected, not rounded.
    """
    request = validate_request(request)
    if source not in ('game', 'demo'):
        raise ValueError('Unsupported presentation source')
    observed = _observed_time(now)
    account = _confirmed_account(account_id)
    if account is None:
        return _empty_snapshot(request, source, observed, 'account_unavailable')
    if diagnostics is None:
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        raise ValueError('Diagnostics must be an object')
    invalid = sum(_counter(diagnostics.get(name, 0), name)
                  for name in ('invalid', 'malformed'))
    conflicts = _counter(diagnostics.get('conflicts', 0), 'conflicts')
    clean_goals = validate_goals([] if goals is None else goals)
    for goal in clean_goals:
        _text(goal['vehicle'], 128, 'goal vehicle')
    own = []
    for raw in records:
        if not isinstance(raw, dict):
            invalid += 1
            continue
        # Foreign records are not validated or used to populate dropdowns.
        if _confirmed_account(raw.get('account_id')) != account:
            continue
        record = validate_record(raw)
        if record is None:
            invalid += 1
            continue
        if (len(record['vehicle']) > 128 or
                any(record[name] is not None and record[name] > MAX_JS_INTEGER
                    for name in ('timestamp', 'damage', 'xp', 'assistance_radio',
                                 'assistance_track'))):
            invalid += 1
            continue
        try:
            record['vehicle'].encode('utf-8')
        except UnicodeError:
            invalid += 1
            continue
        own.append(record)
    ordered = sort_records(own)
    invalid += len(own) - len(ordered)
    invalid = _counter(invalid, 'invalid_records')
    own = ordered
    vehicles = [{'name': name, 'battles': stats['battles']}
                for name, stats in vehicle_table(own)]
    if len(vehicles) > MAX_VEHICLES:
        raise ValueError('Too many vehicles for a presentation snapshot')
    selected = [row for row in own
                if not request['vehicle'] or row['vehicle'] == request['vehicle']]
    relevant_goals = [goal for goal in clean_goals
                      if not request['vehicle'] or goal['vehicle'] == request['vehicle']]
    rendered_goals = []
    for goal in evaluate_goals(selected, relevant_goals, account_id=account):
        rendered_goals.append(dict((key, value) for key, value in goal.items()
                                   if key != 'account_id'))
    # These calculations only depend on their trailing windows. Limit the
    # repeated sorts inside analytics while preserving absolute battle numbers.
    comparison_rows = selected[-2 * request['window']:]
    trend_rows = selected[-(request['window'] + MAX_SERIES - 1):]
    trend_offset = len(selected) - len(trend_rows)
    snapshot = _empty_snapshot(request, source, observed,
                               'ready' if selected else 'empty')
    snapshot.update({
        'vehicles': vehicles,
        'summary': summarize(selected),
        'comparison': window_comparison(comparison_rows, request['window']),
        'series': [{'battle': battle + trend_offset, 'avg_damage': average, 'known_damage': known}
                   for battle, average, known in rolling_damage(
                       trend_rows, request['window'], max_points=MAX_SERIES)],
        'goals': rendered_goals,
        'history': [dict((key, row[key])
                         for key in ('timestamp', 'vehicle', 'outcome', 'damage', 'xp'))
                    for row in reversed(selected[-MAX_HISTORY:])],
        'quality': {
            'total_records': len(selected),
            'incomplete_records': sum(not record_is_complete(row) for row in selected),
            'invalid_records': invalid,
            'conflicts': conflicts,
        },
    })
    return snapshot
