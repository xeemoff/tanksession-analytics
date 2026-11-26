# -*- coding: utf-8 -*-
"""Optional, offline, own-battle targets. Compatible with Python 2.7.

Targets use rolling windows separately for each account. A target is never
marked as achieved until a complete window and enough known damage exists.
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
        if not isinstance(vehicle, _text_types) or not vehicle.strip() or len(vehicle) > 128:
            raise ValueError('Goal vehicle must be a short non-empty string')
        if target is None or not 1 <= target <= 50000:
            raise ValueError('Invalid damage target')
        if window is None or not 10 <= window <= 1000:
            raise ValueError('Goal window must be between 10 and 1000')
        goal = {'vehicle': _as_text(vehicle).strip(),
                'target_avg_damage': target, 'window': window}
        if 'account_id' in item:
            account = item['account_id']
            if (not isinstance(account, _text_types) or not account.strip()
                    or len(account) > 128):
                raise ValueError('Goal account_id must be a short non-empty string')
            goal['account_id'] = _as_text(account).strip()
        clean.append(goal)
    return clean


def evaluate_goals(records, goals, account_id=None):
    """Evaluate each account separately, even in the all-accounts view.

    An unbound goal is a template applied independently to each visible account.
    An explicit account_id binds the goal to that account only. The optional
    argument is the dashboard's account selection, including an empty history.
    """
    ordered = sort_records(records)
    selected_account = _as_text(account_id).strip() if account_id else None
    accounts = sorted(set(_as_text(row.get('account_id') or 'local') for row in ordered))
    results = []
    for goal in validate_goals(goals):
        bound = goal.get('account_id')
        if bound and selected_account and bound != selected_account:
            continue
        if bound:
            target_accounts = [bound]
        elif selected_account:
            target_accounts = [selected_account]
        else:
            target_accounts = accounts or [None]
        for account in target_accounts:
            own = [row for row in ordered
                   if _as_text(row.get('account_id') or 'local') == account
                   and row.get('vehicle') == goal['vehicle']]
            sample = own[-goal['window']:]
            stats = summarize(sample)
            complete = len(sample) == goal['window']
            # A missing low-damage result must not award a target using only
            # the visible high-damage subset of the window.
            minimum = goal['window']
            if account is None:
                status = 'no_data'
            elif not complete:
                status = 'in_progress'
            elif stats['damage_samples'] < minimum:
                status = 'insufficient_data'
            else:
                values = [_non_negative_int(row.get('damage')) for row in sample]
                total = sum(value for value in values if value is not None)
                # Decide before display rounding; 1999.96 is not a 2000 target.
                achieved = total >= goal['target_avg_damage'] * stats['damage_samples']
                status = 'achieved' if achieved else 'not_achieved'
            results.append({
                'account_id': account,
                'vehicle': goal['vehicle'], 'target': goal['target_avg_damage'],
                'window': goal['window'], 'battles': len(sample),
                'known_damage': stats['damage_samples'],
                'avg_damage': stats['avg_damage'], 'status': status,
            })
    return results
