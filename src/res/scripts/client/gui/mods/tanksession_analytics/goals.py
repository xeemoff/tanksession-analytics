# -*- coding: utf-8 -*-
"""Optional, offline, own-battle targets. Compatible with Python 2.7.

Targets use rolling windows; a target is never marked as achieved until a
complete window and sufficient observed damage metrics are available.
"""
from __future__ import division
from .core import _as_text, _non_negative_int, summarize

try:
    _text_types = (str, unicode)
except NameError:
    _text_types = (str, bytes)
from .analytics import sort_records


def validate_goals(raw):
    if not isinstance(raw, list):
        raise ValueError('Goals must be a JSON array')
    if len(raw) > 30:
        raise ValueError('Too many goals (max 30)')
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('Each goal must be an object')
        vehicle = item.get('vehicle')
        target = _non_negative_int(item.get('target_avg_damage'))
        window = _non_negative_int(item.get('window'))
        if not isinstance(vehicle, _text_types) or not vehicle or len(vehicle) > 128:
            raise ValueError('Goal vehicle must be a short non-empty string')
        if target is None or not 1 <= target <= 50000:
            raise ValueError('Invalid damage target')
        if window is None or not 10 <= window <= 1000:
            raise ValueError('Goal window must be between 10 and 1000')
        clean.append({'vehicle': vehicle, 'target_avg_damage': target, 'window': window})
    return clean


def evaluate_goals(records, goals):
    """Statuses: in_progress, insufficient_data, achieved, not_achieved."""
    ordered = sort_records(records)
    results = []
    for goal in validate_goals(goals):
        own = [row for row in ordered if row.get('vehicle') == goal['vehicle']]
        sample = own[-goal['window']:]
        stats = summarize(sample)
        complete = len(sample) == goal['window']
        minimum = (7 * goal['window'] + 9) // 10
        if complete and stats['damage_samples'] < minimum:
            status = 'insufficient_data'
        elif not complete:
            status = 'in_progress'
        elif stats['avg_damage'] >= goal['target_avg_damage']:
            status = 'achieved'
        else:
            status = 'not_achieved'
        results.append({
            'vehicle': goal['vehicle'], 'target': goal['target_avg_damage'],
            'window': goal['window'], 'battles': len(sample),
            'known_damage': stats['damage_samples'],
            'avg_damage': stats['avg_damage'], 'status': status,
        })
    return results
