# -*- coding: utf-8 -*-
"""Coverage-aware optional metrics and receipt-time sessions (Python 2.7)."""
from __future__ import division

from .core import summarize

SESSION_GAP = 60 * 60
MIN_SESSION_BATTLES = 10
MAX_SESSIONS = 7
MAX_MAPS = 12
MAX_EXACT_INTEGER = (1 << 53) - 1


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (ordered[middle] if len(ordered) % 2 else
            (ordered[middle - 1] + ordered[middle]) / 2.0)


def build_metrics(records):
    """Use only observed fields; pair denominators with their numerators."""
    fields = {}
    for name in ('kills', 'xp_base', 'credits_gross', 'credits_net'):
        values = [row[name] for row in records if row.get(name) is not None]
        fields[name] = {'samples': len(values), 'average': _mean(values)}
    survivors = [row['survived'] for row in records
                 if isinstance(row.get('survived'), bool)]

    def ratio(numerator, denominator, total_name, value_name):
        pairs = [(row[denominator], row[numerator]) for row in records
                 if row.get(denominator) is not None and
                 row.get(numerator) is not None and
                 0 <= row[numerator] <= row[denominator]]
        total = sum(pair[0] for pair in pairs)
        value = sum(pair[1] for pair in pairs)
        # Do not round overflowing integer counters on the JS boundary.
        if total > MAX_EXACT_INTEGER or value > MAX_EXACT_INTEGER:
            return {'samples': 0, total_name: 0, value_name: 0, 'rate': None}
        return {'samples': len(pairs), total_name: total, value_name: value,
                'rate': round(100.0 * value / total, 1) if total else None}

    maps = {}
    for row in records:
        name = row.get('map')
        if name:
            maps.setdefault(name, []).append(row)
    return {
        'version': 1, 'fields': fields,
        'survival': {'samples': len(survivors), 'survived': sum(survivors),
                     'rate': round(100.0 * sum(survivors) / len(survivors), 1)
                     if survivors else None},
        'accuracy': ratio('direct_hits', 'shots', 'shots', 'hits'),
        'penetration': ratio('penetrations', 'direct_hits', 'hits', 'penetrations'),
        'maps': [{'label': name, 'summary': summarize(rows)} for name, rows in
                 sorted(maps.items(), key=lambda item: (-len(item[1]), item[0]))[:MAX_MAPS]],
    }


def build_sessions(ordered, vehicle=''):
    """Split one account before filtering, so another tank bridges a session.

    Input must already be normalized, account-scoped and chronological.
    Receipt time is the only available clock for legacy records. It cannot
    establish when a battle was played or why a player's results changed.
    """
    groups = []
    last = None
    for row in ordered:
        stamp = row['timestamp']
        if last is None or stamp - last >= SESSION_GAP:
            groups.append([])
        groups[-1].append(row)
        last = stamp
    selected = [[row for row in group if not vehicle or row['vehicle'] == vehicle]
                for group in groups]
    selected = [group for group in selected if group]
    recent = selected[-MAX_SESSIONS:]
    items = [{'started_at': group[0]['timestamp'], 'ended_at': group[-1]['timestamp'],
              'summary': summarize(group),
              'median_damage': _median([row['damage'] for row in group
                                        if row['damage'] is not None])}
             for group in reversed(recent)]
    current = selected[-1] if selected else []
    previous = selected[-2] if len(selected) > 1 else []
    comparison = {
        'status': 'insufficient_data', 'minimum_battles': MIN_SESSION_BATTLES,
        'current_battles': len(current), 'previous_battles': len(previous),
        'current_average': None, 'previous_average': None,
        'current_median': None, 'previous_median': None,
        'delta_average': None, 'delta_median': None,
    }
    vehicles = set(row['vehicle'] for row in current + previous)
    modes = set(row.get('mode', 'unknown') for row in current + previous)
    if len(vehicles) > 1 or 'unknown' in vehicles or (not vehicle and not vehicles):
        comparison['status'] = 'choose_vehicle'
    elif min(len(current), len(previous)) < MIN_SESSION_BATTLES:
        pass
    elif any(row['damage'] is None for row in current + previous):
        comparison['status'] = 'incomplete'
    elif 'unknown' in modes or '0' in modes or None in modes:
        comparison['status'] = 'mode_unknown'
    elif len(modes) != 1:
        comparison['status'] = 'mixed_modes'
    else:
        current_values = [row['damage'] for row in current]
        previous_values = [row['damage'] for row in previous]
        mean_current, mean_previous = _mean(current_values), _mean(previous_values)
        median_current, median_previous = _median(current_values), _median(previous_values)
        comparison.update(status='ready', current_average=mean_current,
                          previous_average=mean_previous, current_median=median_current,
                          previous_median=median_previous,
                          delta_average=round(mean_current - mean_previous, 1),
                          delta_median=median_current - median_previous)
    return {'version': 1, 'gap_minutes': SESSION_GAP // 60, 'basis': 'received_at',
            'items': items, 'comparison': comparison}
