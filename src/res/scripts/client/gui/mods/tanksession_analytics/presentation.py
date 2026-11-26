# -*- coding: utf-8 -*-
"""Versioned, bounded data snapshots for the optional hangar interface.

This module has no game imports and is compatible with Python 2.7. Pass the
current logical records from BattleStore, not its append-only revision log.
Identity is checked before data is exposed. Account and arena identifiers
never cross the presentation boundary.
"""
import re
import time

from .analytics import rolling_damage, sort_records, window_comparison
from .coach import build_coach
from .core import _as_text, by_day, by_vehicle, long_type, record_is_complete, summarize, validate_record
from .goals import evaluate_goals, migrate_goal_selectors, validate_goals
from .insights import build_metrics, build_sessions
from .recorder import _verified_account
from .workspace import validate_command
from .vehicles import resolve_records, selector_resolver, selector_for

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
MAX_RAW_POINTS = 24
MAX_INSIGHT_DAYS = 14
MAX_INSIGHT_VEHICLES = 20
_REQUEST_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,64}\Z')
_REQUEST_FIELDS = frozenset(('protocol', 'request_id', 'vehicle', 'window', 'page',
                             'action', 'preferences', 'goal'))
PAGE_SIZE = 5
DETAIL_FIELDS = ('map', 'kills', 'survived', 'shots', 'direct_hits', 'penetrations',
                 'xp_base', 'xp_bonus', 'credits_gross', 'credits_net', 'assistance_radio',
                 'assistance_track')


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
    return validate_command(request, {'protocol': PROTOCOL_VERSION, 'request_id': identifier,
                                     'vehicle': vehicle, 'window': window})


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
        'coach': build_coach([], '' if status == 'account_unavailable' else request['vehicle'],
                             request['window']),
        'series': [], 'goals': [], 'history': [],
        'quality': {'total_records': 0, 'incomplete_records': 0,
                    'invalid_records': 0, 'conflicts': 0},
        'updated_at': now,
    }


def clean_own_records(records, account):
    """One shared boundary for presentation and explicit account-scoped export."""
    account = _confirmed_account(account)
    if account is None:
        return [], 0
    own, invalid = [], 0
    for raw in records:
        if not isinstance(raw, dict):
            invalid += 1
            continue
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
            if record.get('map') is not None:
                record['map'].encode('utf-8')
        except UnicodeError:
            invalid += 1
            continue
        # Optional outliers must not hide previously readable primary metrics.
        for name in ('kills', 'shots', 'direct_hits', 'penetrations', 'xp_base', 'xp_bonus',
                     'credits_gross', 'credits_net'):
            value = record.get(name)
            if value is not None and abs(value) > MAX_JS_INTEGER:
                record[name] = None
                invalid += 1
        own.append(record)
    ordered = sort_records(resolve_records(own, account))
    return ordered, invalid + len(own) - len(ordered)


def vehicle_labels(records):
    """Display names are separate from selectors and never establish identity."""
    candidates = {}
    for row in records:
        selector = selector_for(row)
        label = row.get('vehicle_label') or row.get('vehicle')
        if label and label != 'unknown':
            candidates[selector] = label
    duplicates = {}
    for selector, label in candidates.items():
        duplicates.setdefault(label, []).append(selector)
    labels = {}
    for selector, label in candidates.items():
        if len(duplicates[label]) > 1:
            if selector.startswith('type:'):
                suffix = u' · #' + selector[5:]
            elif selector.startswith('name:'):
                suffix = u' · ' + selector[5:]
            else:
                suffix = u' · старая запись'
            label = label[:128 - len(suffix)] + suffix
        if label != selector:
            labels[selector] = label
    return labels


def _projected_vehicle_table(records):
    # Rows here already carry selectors in vehicle. Reapplying the raw-row
    # identity boundary would escape a reserved legacy selector twice.
    return sorted(by_vehicle(records).items(),
                  key=lambda entry: (-entry[1]['battles'], entry[0]))


def _project_vehicle_records(records, labels):
    projected = []
    for row in records:
        item = dict(row)
        selector = selector_for(row)
        if selector in labels:
            item['vehicle_label'] = labels[selector]
        item['vehicle'] = selector
        projected.append(item)
    return projected


def _labelled(value, selector, labels, field='vehicle_label'):
    label = labels.get(selector)
    if label is not None:
        value[field] = label
    return value


def _history_row(row, fields):
    value = dict((key, row.get(key)) for key in fields)
    if row.get('vehicle_label') is not None:
        value['vehicle_label'] = row['vehicle_label']
    return value


def _add_pagination(snapshot, selected, request):
    if 'page' not in request:
        return
    total = len(selected)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(request['page'], pages - 1)
    end = total - page * PAGE_SIZE
    start = max(0, end - PAGE_SIZE)
    fields = ('timestamp', 'vehicle', 'outcome', 'damage', 'xp') + DETAIL_FIELDS
    snapshot['history'] = [_history_row(row, fields)
                           for row in reversed(selected[start:end])]
    snapshot['pagination'] = {'page': page, 'page_size': PAGE_SIZE,
                              'pages': pages, 'total': total}
    snapshot['selection']['page'] = page


def _build_insights(selected, pending_count):
    """Describe the saved history only, never infer missing matches."""
    size = len(selected)
    recent = selected[-MAX_RAW_POINTS:]
    outcome = selected[-1]['outcome'] if selected else None
    length = 0
    if outcome in ('win', 'loss', 'draw'):
        for row in reversed(selected):
            if row['outcome'] != outcome:
                break
            length += 1
    else:
        outcome = None
    days = by_day(selected)
    labels = dict((row['vehicle'], row['vehicle_label']) for row in selected
                  if row.get('vehicle_label') is not None)

    def assistance(field):
        values = [row[field] for row in selected if row[field] is not None]
        return {'samples': len(values),
                'average': round(sum(values) / float(len(values)), 1) if values else None}

    return {
        'version': 1,
        'pending_count': pending_count,
        'recent_damage': [{'battle': size - len(recent) + index + 1,
                           'damage': row['damage'], 'outcome': row['outcome']}
                          for index, row in enumerate(recent)],
        'streak': {'outcome': outcome, 'length': length},
        'days': [{'label': day, 'summary': days[day]}
                 for day in sorted(days, reverse=True)[:MAX_INSIGHT_DAYS]],
        'tanks': [_labelled({'label': name, 'summary': stats}, name, labels)
                  for name, stats in _projected_vehicle_table(selected)[:MAX_INSIGHT_VEHICLES]],
        'assistance_radio': assistance('assistance_radio'),
        'assistance_track': assistance('assistance_track'),
    }


def build_snapshot(records, account_id, request=None, goals=None, diagnostics=None,
                   source='game', now=None, pending_count=None, include_insights=True):
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
        snapshot = _empty_snapshot(request, source, observed, 'account_unavailable')
        if include_insights:
            snapshot['insights'] = _build_insights([], None)
            snapshot['metrics'] = build_metrics([])
            snapshot['sessions'] = build_sessions([])
        _add_pagination(snapshot, [], request)
        return snapshot
    if pending_count is not None:
        pending_count = _counter(pending_count, 'pending_count')
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
    raw_own, rejected = clean_own_records(records, account)
    resolve = selector_resolver(raw_own)
    request['vehicle'] = resolve(request['vehicle'])
    # Resolve legacy goal names only inside this account. Conflicting old goals
    # remain separate until an explicit edit; reading never rewrites a profile.
    clean_goals = migrate_goal_selectors([
        goal for goal in clean_goals
        if 'account_id' not in goal or goal['account_id'] == account], raw_own, resolve)
    labels = vehicle_labels(raw_own)
    own = _project_vehicle_records(raw_own, labels)
    invalid += rejected
    invalid = _counter(invalid, 'invalid_records')
    vehicles = [_labelled({'name': name, 'battles': stats['battles']},
                         name, labels, field='label')
                for name, stats in _projected_vehicle_table(own)]
    if len(vehicles) > MAX_VEHICLES:
        raise ValueError('Too many vehicles for a presentation snapshot')
    selected = [row for row in own
                if not request['vehicle'] or row['vehicle'] == request['vehicle']]
    relevant_goals = [goal for goal in clean_goals
                      if not request['vehicle'] or
                      resolve(goal['vehicle']) == request['vehicle']]
    rendered_goals = []
    for goal in evaluate_goals(raw_own, relevant_goals, account_id=account):
        value = dict((key, value) for key, value in goal.items() if key != 'account_id')
        rendered_goals.append(_labelled(value, resolve(goal['vehicle']), labels))
    # These calculations only depend on their trailing windows. Limit the
    # repeated sorts inside analytics while preserving absolute battle numbers.
    comparison_rows = selected[-2 * request['window']:]
    trend_rows = selected[-(request['window'] + MAX_SERIES - 1):]
    trend_offset = len(selected) - len(trend_rows)
    snapshot = _empty_snapshot(request, source, observed,
                               'ready' if selected else 'empty')
    coach = build_coach(selected, request['vehicle'], request['window'])
    _labelled(coach, coach['vehicle'], labels)
    snapshot.update({
        'vehicles': vehicles,
        'summary': summarize(selected),
        'comparison': window_comparison(comparison_rows, request['window']),
        'coach': coach,
        'series': [{'battle': battle + trend_offset, 'avg_damage': average, 'known_damage': known}
                   for battle, average, known in rolling_damage(
                       trend_rows, request['window'], max_points=MAX_SERIES)],
        'goals': rendered_goals,
        'history': [_history_row(row, ('timestamp', 'vehicle', 'outcome', 'damage', 'xp'))
                    for row in reversed(selected[-MAX_HISTORY:])],
        'quality': {
            'total_records': len(selected),
            'incomplete_records': sum(not record_is_complete(row) for row in selected),
            'invalid_records': invalid,
            'conflicts': conflicts,
        },
    })
    if include_insights:
        snapshot['insights'] = _build_insights(selected, pending_count)
        snapshot['metrics'] = build_metrics(selected)
        snapshot['sessions'] = build_sessions(own, request['vehicle'])
    _add_pagination(snapshot, selected, request)
    return snapshot
