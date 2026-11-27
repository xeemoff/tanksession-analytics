# -*- coding: utf-8 -*-
"""Coverage-aware optional metrics and receipt-time sessions (Python 2.7)."""
from __future__ import division

from datetime import datetime, timedelta

from .core import summarize, _as_text

SESSION_GAP = 60 * 60
MIN_SESSION_BATTLES = 10
MAX_SESSIONS = 7
MAX_MAPS = 12
MAX_EXACT_INTEGER = (1 << 53) - 1
CALENDAR_DAYS = 90
MAX_DIMENSION_GROUPS = 24
MAX_ECONOMY_VEHICLES = 64


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
    for name in ('kills', 'xp_base', 'xp_bonus', 'credits_gross', 'credits_net'):
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
    elif any(row.get('_vehicle_ambiguous') for row in current + previous):
        comparison['status'] = 'identity_ambiguous'
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


def total_metric(records, field):
    """Observed sum and mean, with explicit coverage and no invented zeros."""
    values = [row[field] for row in records if row.get(field) is not None]
    if not values:
        return {'samples': 0, 'average': None, 'total': None}
    total = sum(values)
    average = round(total / float(len(values)), 1)
    return {'samples': len(values),
            'average': average if abs(average) <= MAX_EXACT_INTEGER else None,
            'total': total if abs(total) <= MAX_EXACT_INTEGER else None}


def _group(key, label, rows):
    return {'key': key, 'label': label, 'summary': summarize(rows),
            'credits_net': total_metric(rows, 'credits_net')}


def _groups(records, field, limit, label_field=None, labels=None):
    """Bound an aggregate without dropping rows: the remainder is one group."""
    buckets = {}
    for row in records:
        value = row.get(field)
        key = _as_text(value) if value not in (None, '') else 'unknown'
        buckets.setdefault(key, []).append(row)
    keys = sorted(buckets, key=lambda key: (-len(buckets[key]), key))
    kept = keys if len(keys) <= limit else keys[:limit - 1]
    result = []
    for key in kept:
        group_rows = buckets[key]
        label = (labels or {}).get(key, key)
        if label_field:
            known = [row[label_field] for row in group_rows if row.get(label_field)]
            if known:
                label = known[-1]
        if key == 'unknown' and label == key:
            label = u'Неизвестно'
        item = _group(key, label, group_rows)
        if field == 'vehicle' and label != key:
            item['vehicle_label'] = label
        result.append(item)
    if len(kept) < len(keys):
        remainder = [row for key in keys[len(kept):] for row in buckets[key]]
        other_key = 'other'
        while other_key in buckets:
            other_key = '_' + other_key
        result.append(_group(other_key, u'Остальные', remainder))
    return result


def _utc(stamp):
    # Arithmetic works for the same supported calendar on Windows Python 2.7,
    # without delegating a far-future timestamp to the C runtime's time_t.
    return datetime(1970, 1, 1) + timedelta(seconds=stamp)


def build_analytics(records, now):
    """Account-scoped descriptive slices supplied by the presentation boundary.

    Metadata stays attached to the observed battle; a current catalog does not
    retroactively fill unknown historical tiers/classes. Time is UTC receipt
    time, not the unobserved time of playing a recovered battle.
    """
    class_labels = {'lightTank': u'Лёгкие танки', 'mediumTank': u'Средние танки',
                    'heavyTank': u'Тяжёлые танки', 'AT-SPG': u'ПТ-САУ', 'SPG': u'САУ'}
    week_labels = (u'Понедельник', u'Вторник', u'Среда', u'Четверг',
                   u'Пятница', u'Суббота', u'Воскресенье')
    day_end = (now // 86400) * 86400
    first_day = day_end - (CALENDAR_DAYS - 1) * 86400
    days = dict((first_day + index * 86400, []) for index in range(CALENDAR_DAYS))
    weekdays, hours = [[] for unused in range(7)], [[] for unused in range(24)]
    for row in records:
        stamp = row['timestamp']
        day = (stamp // 86400) * 86400
        if day in days:
            days[day].append(row)
        instant = _utc(stamp)
        weekdays[instant.weekday()].append(row)
        hours[instant.hour].append(row)
    return {
        'version': 1, 'basis': 'received_at', 'timezone': 'UTC',
        'dimensions': {
            'maps': _groups(records, 'map', MAX_DIMENSION_GROUPS, 'map_label'),
            'tiers': _groups(records, 'vehicle_tier', 12),
            'classes': _groups(records, 'vehicle_class', 6, labels=class_labels),
            'nations': _groups(records, 'vehicle_nation', 13),
        },
        'activity': {
            'days': [_group(_utc(day).strftime('%Y-%m-%d'), _utc(day).strftime('%Y-%m-%d'),
                            days[day]) for day in sorted(days)],
            'weekdays': [_group(str(index), week_labels[index], group)
                         for index, group in enumerate(weekdays)],
            'hours': [_group('%02d' % index, '%02d:00' % index, group)
                      for index, group in enumerate(hours)],
        },
        'economy': {
            'credits_gross': total_metric(records, 'credits_gross'),
            'credits_net': total_metric(records, 'credits_net'),
            'xp_bonus': total_metric(records, 'xp_bonus'),
            'vehicles': _groups(records, 'vehicle', MAX_ECONOMY_VEHICLES, 'vehicle_label'),
        },
        'coverage': dict((field, sum(row.get(field) is not None for row in records))
                         for field in ('map_label', 'vehicle_tier', 'vehicle_class',
                                       'vehicle_nation')),
    }


def _report_comparison(current, previous, current_net, previous_net):
    result = {'status': 'insufficient_data', 'avg_damage_delta': None,
              'win_rate_delta_pp': None, 'credits_net_average_delta': None}
    if not current['battles'] or not previous['battles']:
        return result
    damage_complete = all(stats['damage_samples'] == stats['battles']
                          for stats in (current, previous))
    outcomes_complete = all(stats['known_outcomes'] == stats['battles']
                            for stats in (current, previous))
    result['status'] = 'ready' if damage_complete and outcomes_complete else 'partial_data'
    if damage_complete:
        result['avg_damage_delta'] = round(current['avg_damage'] - previous['avg_damage'], 1)
    if outcomes_complete:
        result['win_rate_delta_pp'] = round(current['win_rate'] - previous['win_rate'], 1)
    if (current_net['samples'] == current['battles'] and
            previous_net['samples'] == previous['battles'] and
            current_net['average'] is not None and previous_net['average'] is not None):
        delta = round(current_net['average'] - previous_net['average'], 1)
        result['credits_net_average_delta'] = delta if abs(delta) <= MAX_EXACT_INTEGER else None
    return result


def build_reports(records, now):
    """Rolling seven/thirty-day reports and all received history up to now.

    Intervals are explicit half-open UTC ranges. A previous interval has the
    same duration; no incomplete calendar month is compared to a whole month.
    Deltas are descriptive and require full coverage of their own metric.
    """
    end = now + 1
    eligible = [row for row in records if row['timestamp'] < end]
    periods = []
    for key, label, duration in (('week', u'Последние 7 суток', 7 * 86400),
                                 ('month', u'Последние 30 суток', 30 * 86400),
                                 ('all_time', u'Вся история', None)):
        start = end - duration if duration is not None else (
            min(row['timestamp'] for row in eligible) if eligible else None)
        current = [row for row in eligible if start is not None and row['timestamp'] >= start]
        stats = summarize(current)
        net = total_metric(current, 'credits_net')
        previous = None
        comparison = {'status': 'not_applicable', 'avg_damage_delta': None,
                      'win_rate_delta_pp': None, 'credits_net_average_delta': None}
        if duration is not None:
            before = [row for row in eligible if start - duration <= row['timestamp'] < start]
            previous = {'start_at': start - duration, 'end_at': start,
                        'summary': summarize(before), 'credits_net': total_metric(before, 'credits_net')}
            comparison = _report_comparison(stats, previous['summary'], net, previous['credits_net'])
        periods.append({'key': key, 'label': label, 'start_at': start, 'end_at': end,
                        'summary': stats, 'credits_net': net, 'xp_bonus': total_metric(current, 'xp_bonus'),
                        'vehicles': _groups(current, 'vehicle', 10, 'vehicle_label'),
                        'previous': previous, 'comparison': comparison})
    return {'version': 1, 'basis': 'received_at', 'timezone': 'UTC',
            'excluded_future': len(records) - len(eligible), 'periods': periods}
