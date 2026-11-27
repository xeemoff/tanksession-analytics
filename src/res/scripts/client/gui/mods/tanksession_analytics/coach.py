# -*- coding: utf-8 -*-
"""Descriptive progress and local records for one vehicle.

The presentation boundary supplies validated, chronological logical records
for one confirmed account. Comparisons require two consecutive full windows
with every damage value known. They describe the observed samples and do not
infer skill, causes, battle modes or future results. XP is deliberately unused.
"""
from __future__ import division

from collections import deque

from .analytics import safe_window
from .core import _non_negative_int

COACH_VERSION = 1
MAX_JS_INTEGER = (1 << 53) - 1


def _damage(record):
    value = _non_negative_int(record.get('damage'))
    return value if value is not None and value <= MAX_JS_INTEGER else None


def _rounded_ratio(numerator, denominator):
    """Round an exact ratio to one decimal identically in Python 2 and 3.

    Integer sums and comparisons retain their precision. Only displayed
    metrics become floating-point values. An unrepresentable percentage is
    unavailable rather than an out-of-range JSON number.
    """
    if denominator <= 0 or abs(numerator) > MAX_JS_INTEGER * denominator:
        return None
    sign = -1 if numerator < 0 else 1
    scaled = (abs(numerator) * 20 + denominator) // (2 * denominator)
    whole, fraction = divmod(scaled, 10)
    if not fraction:
        return sign * whole
    return sign * (whole + fraction / 10.0)


def _median_parts(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle], 1
    return ordered[middle - 1] + ordered[middle], 2


def _empty(vehicle, window, status='empty'):
    return {
        'version': COACH_VERSION, 'status': status, 'vehicle': vehicle,
        'window': window, 'battles': 0, 'required_battles': 2 * window,
        'remaining_battles': 2 * window,
        'coverage': {'current_battles': 0, 'current_damage': 0,
                     'previous_battles': 0, 'previous_damage': 0},
        'comparison': None,
        'consistency': {'status': 'insufficient_data', 'samples': 0, 'required': window,
                        'median': None, 'lower_quartile': None, 'upper_quartile': None,
                        'interquartile_range': None, 'median_absolute_deviation': None},
        'observations': [], 'goal_suggestions': [],
        'records': {
            'best_damage': None, 'latest_damage': None,
            'previous_best_damage': None, 'new_damage_record': False,
            'best_window_avg': None, 'previous_best_window_avg': None,
            'current_window_avg': None, 'new_window_record': False,
        },
    }


def _consistency(values):
    """Median-of-halves quartiles and median absolute deviation, not causation."""
    values = sorted(values)
    median, divisor = _median_parts(values)
    low, low_divisor = _median_parts(values[:len(values) // 2])
    high, high_divisor = _median_parts(values[(len(values) + 1) // 2:])
    deviation, deviation_divisor = _median_parts([abs(value * divisor - median) for value in values])
    return {'median': _rounded_ratio(median, divisor),
            'lower_quartile': _rounded_ratio(low, low_divisor),
            'upper_quartile': _rounded_ratio(high, high_divisor),
            'interquartile_range': _rounded_ratio(high * low_divisor - low * high_divisor,
                                                  high_divisor * low_divisor),
            'median_absolute_deviation': _rounded_ratio(deviation, divisor * deviation_divisor)}


def _with_evidence(result, selected, window):
    """Evidence and a reversible goal proposal require comparable known data."""
    current, previous = selected[-window:], selected[-2 * window:-window]
    values = [_damage(row) for row in current]
    known = [value for value in values if value is not None]
    consistency = result['consistency']
    consistency['samples'] = len(known)
    modes = set(row.get('mode') for row in current + previous)
    if (result['status'] in ('identity_ambiguous', 'mixed_modes') or len(modes) != 1
            or any(mode in (None, '', '0', 'unknown') for mode in modes)):
        consistency['status'] = 'not_comparable'
        return result
    if len(known) != window:
        return result
    consistency.update(_consistency(known))
    consistency['status'] = 'ready'
    if result['status'] != 'ready':
        return result
    before = _consistency([_damage(row) for row in previous])
    comparison = result['comparison']
    observations = []
    for kind, current_value, previous_value, delta in (
            ('damage_average', comparison['current_avg'], comparison['previous_avg'], comparison['delta']),
            ('damage_median', comparison['current_median'], comparison['previous_median'], comparison['median_delta']),
            ('damage_spread', consistency['interquartile_range'], before['interquartile_range'],
             consistency['interquartile_range'] - before['interquartile_range'])):
        observations.append({'kind': kind, 'current': current_value, 'previous': previous_value,
                             'delta': delta, 'samples': window, 'previous_samples': window,
                             'window': window, 'scope': 'last_windows'})
    current_net = [row.get('credits_net') for row in current if row.get('credits_net') is not None]
    previous_net = [row.get('credits_net') for row in previous if row.get('credits_net') is not None]
    if len(current_net) == window:
        value = _rounded_ratio(sum(current_net), window)
        old = _rounded_ratio(sum(previous_net), window) if len(previous_net) == window else None
        delta = (_rounded_ratio(sum(current_net) - sum(previous_net), window)
                 if old is not None else None)
        if value is not None:
            observations.append({'kind': 'net_credits', 'current': value, 'previous': old,
                                 'delta': delta, 'samples': window,
                                 'previous_samples': len(previous_net), 'window': window,
                                 'scope': 'last_windows' if old is not None else 'current_window'})
    result['observations'] = observations
    # Explicit product policy, not a prediction: 5% above the observed recent
    # mean, rounded upward to 50 damage. The UI must ask the user to save it.
    step_denominator = window * 100 * 50
    target = max(50, ((sum(known) * 105 + step_denominator - 1) // step_denominator) * 50)
    if target <= 50000:
        result['goal_suggestions'] = [{'vehicle': result['vehicle'], 'window': window,
            'target_avg_damage': target, 'baseline_avg_damage': comparison['current_avg'],
            'samples': window, 'adjustment_percent': 5, 'rounding_step': 50,
            'basis': 'recent_window', 'requires_confirmation': True}]
    return result


def _records(damage, window):
    """Calculate rolling records in one pass, with exact integer sums."""
    latest = damage[-1]
    best, previous_best = None, None
    best_sum, previous_best_sum, current_sum = None, None, None
    values = deque()
    total, known_count = 0, 0
    for index, value in enumerate(damage):
        values.append(value)
        if value is not None:
            best = value if best is None else max(best, value)
            if index < len(damage) - 1:
                previous_best = (value if previous_best is None
                                 else max(previous_best, value))
            total += value
            known_count += 1
        if len(values) > window:
            oldest = values.popleft()
            if oldest is not None:
                total -= oldest
                known_count -= 1
        if len(values) == window and known_count == window:
            best_sum = total if best_sum is None else max(best_sum, total)
            if index < len(damage) - 1:
                previous_best_sum = (total if previous_best_sum is None
                                     else max(previous_best_sum, total))
            else:
                current_sum = total
    return {
        'best_damage': best,
        'latest_damage': latest,
        'previous_best_damage': previous_best,
        'new_damage_record': (latest is not None and previous_best is not None
                              and latest > previous_best),
        'best_window_avg': (_rounded_ratio(best_sum, window)
                            if best_sum is not None else None),
        'previous_best_window_avg': (_rounded_ratio(previous_best_sum, window)
                                     if previous_best_sum is not None else None),
        'current_window_avg': (_rounded_ratio(current_sum, window)
                               if current_sum is not None else None),
        'new_window_record': (current_sum is not None and previous_best_sum is not None
                              and current_sum > previous_best_sum),
    }


def build_coach(ordered_records, vehicle='', window=10):
    """Describe one tank's chronological, account-isolated local history.

    With no explicit vehicle, a single available tank is selected. Multiple
    tanks produce ``choose_vehicle`` and no aggregate coaching metrics.
    Missing measurements keep their positions in both consecutive windows.
    Callers must validate records, de-duplicate revisions and isolate accounts
    before calling this function; ``build_snapshot`` performs that boundary.
    """
    window = safe_window(window)
    records = list(ordered_records)
    if not vehicle:
        vehicles = set(row['vehicle'] for row in records)
        if len(vehicles) > 1:
            return _empty('', window, 'choose_vehicle')
        if vehicles:
            vehicle = next(iter(vehicles))
    if vehicle == 'unknown':
        return _empty('', window, 'choose_vehicle')
    selected = [row for row in records if row['vehicle'] == vehicle]
    result = _empty(vehicle, window)
    if not selected:
        return result
    damage = [_damage(row) for row in selected]
    current = damage[-window:]
    previous = damage[-2 * window:-window]
    current_known = [value for value in current if value is not None]
    previous_known = [value for value in previous if value is not None]
    result.update({
        'status': 'collecting' if len(damage) < 2 * window else 'incomplete',
        'battles': len(damage),
        'remaining_battles': max(0, 2 * window - len(damage)),
        'coverage': {'current_battles': len(current), 'current_damage': len(current_known),
                     'previous_battles': len(previous), 'previous_damage': len(previous_known)},
    })
    if any(row.get('_vehicle_ambiguous') for row in selected):
        result['status'] = 'identity_ambiguous'
        return _with_evidence(result, selected, window)
    result['records'] = _records(damage, window)
    known_modes = set(row.get('mode') for row in selected[-2 * window:]
                      if row.get('mode') not in (None, '', 'unknown'))
    if len(damage) >= 2 * window and len(known_modes) > 1:
        result['status'] = 'mixed_modes'
        return _with_evidence(result, selected, window)
    if len(current_known) == window and len(previous_known) == window:
        current_total, previous_total = sum(current_known), sum(previous_known)
        current_median, current_divisor = _median_parts(current_known)
        previous_median, previous_divisor = _median_parts(previous_known)
        result['status'] = 'ready'
        result['comparison'] = {
            'current_avg': _rounded_ratio(current_total, window),
            'previous_avg': _rounded_ratio(previous_total, window),
            'delta': _rounded_ratio(current_total - previous_total, window),
            'delta_percent': _rounded_ratio((current_total - previous_total) * 100,
                                             previous_total),
            'current_median': _rounded_ratio(current_median, current_divisor),
            'previous_median': _rounded_ratio(previous_median, previous_divisor),
            'median_delta': _rounded_ratio(current_median * previous_divisor -
                                            previous_median * current_divisor,
                                            current_divisor * previous_divisor),
        }
    return _with_evidence(result, selected, window)
