# -*- coding: utf-8 -*-
"""Deterministic, dependency-free analytics (also runs on Python 2.7).

Never infer unobserved results. Time grouping uses the machine's local timezone,
consistent with the dashboard. This is NOT a measure of actual battle start time.
"""
from __future__ import division

from datetime import datetime
from collections import deque

from .core import _as_text, _non_negative_int, summarize

WINDOWS = (10, 30, 100)


def safe_window(value):
    """Only accept the predefined rolling-window sizes."""
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return 10
    return number if number in WINDOWS else 10


def valid_date(value):
    """Accept ISO date strings only; invalid user input means no filter."""
    if not isinstance(value, (str, bytes)):
        try:
            value = unicode(value)
        except (NameError, TypeError, ValueError):
            return ''
    if isinstance(value, bytes):
        try:
            value = value.decode('ascii')
        except UnicodeDecodeError:
            return ''
    if len(value) != 10:
        return ''
    try:
        date = datetime.strptime(value, '%Y-%m-%d')
    except (ValueError, TypeError):
        return ''
    return date.strftime('%Y-%m-%d') if date.strftime('%Y-%m-%d') == value else ''


def record_date(record):
    """Return local YYYY-MM-DD for an observed timestamp, or None."""
    if not isinstance(record, dict):
        return None
    stamp = _non_negative_int(record.get('timestamp'))
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(stamp).strftime('%Y-%m-%d')
    except (ValueError, OverflowError, OSError):
        return None


def sort_records(records):
    """Stable chronological order, with arena ID as an explicit tie-breaker."""
    valid = []
    for record in records:
        if not isinstance(record, dict) or record_date(record) is None:
            continue
        stamp = _non_negative_int(record.get('timestamp'))
        valid.append((stamp, _as_text(record.get('arena_id') or ''), record))
    valid.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in valid]


def select_records(records, vehicle='', account='', from_day='', to_day=''):
    """Filter own local battle journal using strict date bounds (inclusive).

    Records without a valid timestamp are ignored rather than assigned a day.
    Callers can list accounts/vehicles first to populate exact-match options.
    """
    from_day, to_day = valid_date(from_day), valid_date(to_day)
    selected = []
    for item in sort_records(records):
        if vehicle and _as_text(item.get('vehicle') or 'unknown') != vehicle:
            continue
        if account and _as_text(item.get('account_id') or 'local') != account:
            continue
        day = record_date(item)
        if from_day and day < from_day:
            continue
        if to_day and day > to_day:
            continue
        selected.append(item)
    return selected


def vehicle_table(records):
    """Compute per-tank ranking, with ties broken by the tank's label."""
    buckets = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        name = _as_text(item.get('vehicle') or 'unknown')
        buckets.setdefault(name, []).append(item)
    entries = [(name, summarize(rows)) for name, rows in buckets.items()]
    return sorted(entries, key=lambda entry: (-entry[1]['battles'], entry[0]))


def _delta(current, previous):
    if current is None or previous is None:
        return None
    return round(current - previous, 1)


def window_comparison(records, window=10):
    """Compare two *full*, consecutive non-overlapping windows.

    No reference period is reported unless there are at least 2*window battles.
    Rates are only computed for known outcomes; numerical coverage is explicit.
    """
    window = safe_window(window)
    ordered = sort_records(records)
    recent = ordered[-window:]
    previous = ordered[-2 * window:-window] if len(ordered) >= 2 * window else []
    current_stats = summarize(recent)
    previous_stats = summarize(previous) if previous else None
    return {
        'window': window,
        'current': current_stats,
        'previous': previous_stats,
        'enough_current': len(recent) == window,
        'enough_previous': len(previous) == window,
        'damage_delta': _delta(current_stats['avg_damage'], previous_stats['avg_damage'])
                        if previous_stats else None,
        'win_rate_delta_pp': _delta(current_stats['win_rate'], previous_stats['win_rate'])
                            if previous_stats else None,
    }


def rolling_damage(records, window=10, max_points=80):
    """Return (battle_number, average_damage, known_count) for full windows.

    If under 70%% of battle damage is known, return None for that point rather
    than visually treating missing data as zero. Skip no battles on the x-axis.
    """
    window = safe_window(window)
    ordered = sort_records(records)
    if len(ordered) < window:
        return []
    points = []
    values = deque()
    total, known = 0, 0
    minimum = (7 * window + 9) // 10  # ceil(70%%), no float rounding.
    for end, item in enumerate(ordered, 1):
        value = _non_negative_int(item.get('damage'))
        values.append(value)
        if value is not None:
            total += value
            known += 1
        if len(values) > window:
            oldest = values.popleft()
            if oldest is not None:
                total -= oldest
                known -= 1
        if len(values) == window:
            mean = round(total / known, 1) if known >= minimum else None
            points.append((end, mean, known))
    try:
        limit = int(max_points)
    except (ValueError, TypeError, OverflowError):
        limit = 80
    return points[-max(1, min(limit, 500)):]
