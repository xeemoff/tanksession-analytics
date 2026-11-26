#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create deterministic UI fixtures from the Python presentation contract."""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.presentation import build_snapshot
from tanksession_analytics.storage import BattleStore


def fixtures():
    store = BattleStore(str(ROOT / 'sample_data/battles.jsonl'))
    rows = store.records
    goals = json.loads((ROOT / 'sample_data/goals.json').read_text(encoding='utf-8'))
    observed = max(row['timestamp'] for row in rows) + 60

    def snapshot(records, account='demo', vehicle='', window=10):
        return build_snapshot(records, account,
                              request={'protocol': 1, 'request_id': 'fixture',
                                       'vehicle': vehicle, 'window': window},
                              goals=goals, source='demo', now=observed,
                              # Preserve the legacy fixtures to exercise old hosts.
                              # Live preview + Python tests exercise the extension.
                              include_insights=False)

    incomplete = copy.deepcopy(rows)
    for index, row in enumerate(incomplete):
        if index % 3 != 0:
            row['damage'] = None
        if index % 2 == 0:
            row['xp'] = None
        if index % 5 == 0:
            row['outcome'] = 'unknown'
    variants = []
    for vehicle in [''] + sorted(set(row['vehicle'] for row in rows)):
        for window in (10, 30, 100):
            variants.append(snapshot(rows, vehicle=vehicle, window=window))

    def coach_rows(damage):
        return [dict(rows[0], arena_id='coach-demo-%d' % index, account_id='demo',
                     vehicle='IS-7', mode='1', timestamp=rows[0]['timestamp'] + index * 180,
                     damage=value, xp=500, outcome='win')
                for index, value in enumerate(damage)]

    mixed_modes = coach_rows([1000] * 10 + [1200] * 10)
    for row in mixed_modes[10:]:
        row['mode'] = '7'
    return {
        'demo.json': snapshot(rows),
        'demo_filters.json': variants,
        'empty.json': snapshot([]),
        'incomplete.json': snapshot(incomplete),
        'account_unavailable.json': snapshot(rows, account=None),
        'coach_ready.json': snapshot(coach_rows([1000] * 10 + [900] * 9 + [10000])),
        'coach_collecting.json': snapshot(coach_rows([700])),
        'coach_incomplete.json': snapshot(coach_rows([1000] * 10 + [1200] * 9 + [None])),
        'coach_record.json': snapshot(coach_rows([1000] * 20 + [3500])),
        'coach_mixed_modes.json': snapshot(mixed_modes),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check committed fixtures without writing')
    args = parser.parse_args()
    directory = ROOT / 'sample_data/ui'
    mismatches = []
    for name, value in sorted(fixtures().items()):
        path = directory / name
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                mismatches.append(name)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8', newline='\n') as output:
                output.write(text)
            print(path.relative_to(ROOT))
    if mismatches:
        parser.exit(1, 'UI fixtures differ: %s\n' % ', '.join(mismatches))
    if args.check:
        print('UI fixtures match the Python presentation contract.')


if __name__ == '__main__':
    main()
