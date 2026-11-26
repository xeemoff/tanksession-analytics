#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repeatable local calculation benchmark, no game access or user data."""
import argparse
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.analytics import rolling_damage
from tanksession_analytics.presentation import build_snapshot
from tanksession_analytics.workspace import Workspace


def run(count, goal_count=0):
    rows = [{'arena_id': str(i + 1), 'timestamp': 1720000000 + i,
             'account_id': 'synthetic-benchmark', 'vehicle': 'Demo tank',
             'mode': '1', 'xp': 500,
             'outcome': 'win' if i % 2 else 'loss',
             'damage': None if i % 23 == 0 else (i * 13 % 7000)}
            for i in range(count)]
    started = time.perf_counter()
    points = rolling_damage(rows, window=100, max_points=80)
    elapsed = time.perf_counter() - started
    started = time.perf_counter()
    snapshot = build_snapshot(rows, 'synthetic-benchmark',
                              {'protocol': 1, 'request_id': 'benchmark',
                               'vehicle': '', 'window': 100, 'page': 0}, now=1721000000)
    snapshot_elapsed = time.perf_counter() - started
    result = {'battles': count, 'window': 100, 'points': len(points),
            'elapsed_seconds': round(elapsed, 3),
            'snapshot_seconds': round(snapshot_elapsed, 3),
            'snapshot_bytes': len(json.dumps(snapshot, separators=(',', ':')).encode('utf-8'))}
    if goal_count:
        for index, row in enumerate(rows):
            number = index % goal_count
            row['vehicle'] = 'Demo tank %d' % number
            row['vehicle_id'] = 'type:%d' % ((number + 1) * 256 + 1)
        goals = [{'vehicle': 'Demo tank %d' % index, 'window': 10,
                  'target_avg_damage': 1000} for index in range(goal_count)]
        started = time.perf_counter()
        Workspace(ROOT, memory=True).snapshot(
            rows, 'synthetic-benchmark',
            {'protocol': 1, 'request_id': 'benchmark', 'vehicle': '',
             'window': 10, 'page': 0}, legacy_goals=goals, now=1721000000)
        result.update(goals=goal_count,
                      workspace_seconds=round(time.perf_counter() - started, 3))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--battles', type=int, default=100000)
    parser.add_argument('--goals', type=int, default=0,
                        help='Also measure account-scoped legacy goal migration (0..30)')
    args = parser.parse_args()
    if args.battles < 100 or args.battles > 1000000:
        parser.error('Battle count must be between 100 and 1000000')
    if not 0 <= args.goals <= 30:
        parser.error('Goal count must be between 0 and 30')
    print(run(args.battles, args.goals))


if __name__ == '__main__':
    main()
