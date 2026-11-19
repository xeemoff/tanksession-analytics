#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repeatable local calculation benchmark, no game access or user data."""
import argparse
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.analytics import rolling_damage


def run(count):
    rows = [{'arena_id': str(i + 1), 'timestamp': 1720000000 + i,
             'outcome': 'win' if i % 2 else 'loss',
             'damage': None if i % 23 == 0 else (i * 13 % 7000)}
            for i in range(count)]
    started = time.perf_counter()
    points = rolling_damage(rows, window=100, max_points=80)
    elapsed = time.perf_counter() - started
    return {'battles': count, 'window': 100, 'points': len(points),
            'elapsed_seconds': round(elapsed, 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--battles', type=int, default=100000)
    args = parser.parse_args()
    if args.battles < 100 or args.battles > 1000000:
        parser.error('Battle count must be between 100 and 1000000')
    print(run(args.battles))


if __name__ == '__main__':
    main()
