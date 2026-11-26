#!/usr/bin/env python3
"""Generate DEMONSTRATION (not real account) battle history."""
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
path = os.path.join(ROOT, 'sample_data', 'battles.jsonl')
start = datetime(2026, 11, 8, 18, 30, tzinfo=timezone.utc)
vehicles = ['Object 277'] * 10 + ['T-34-85'] * 7 + ['Leopard 1'] * 7 + ['IS-7'] * 24
with open(path, 'w', encoding='utf-8') as target:
    for index in range(48):
        stamp = start + timedelta(days=index // 5, minutes=30 * (index % 5))
        # Fixed UTC timestamps make the synthetic fixture reproducible.
        record = {
            'schema': 1, 'arena_id': 'DEMO-%04d' % (index + 1),
            'account_id': 'demo', 'timestamp': int(stamp.timestamp()),
            # Two full IS-7 comparison windows and full windows for both
            # configured demo goals, without increasing the 48-battle fixture.
            'vehicle': vehicles[index],
            'mode': 'regular',
            'outcome': ['win', 'loss', 'win', 'win', 'loss', 'draw'][index % 6],
            'damage': 1050 + (index * 131) % 2100 + (index // 10) * 140,
            'assistance_radio': 140 + (index * 17) % 500,
            'assistance_track': (index * 13) % 300,
            'xp': 400 + (index * 23) % 570,
            'xp_base': None if index % 7 == 0 else 300 + (index * 23) % 570,
            'kills': index % 4,
            'survived': index % 3 == 0,
            'shots': 10 + index % 9,
            'direct_hits': 8 + index % 9,
            'penetrations': 5 + index % 9,
            'credits_gross': 12000 + (index * 977) % 25000,
            # Synthetic imported net values; the game collector does not
            # infer this field from an incomplete expense breakdown.
            'credits_net': -3000 + (index * 701) % 15000,
            'map': 'arena:%d' % (1 + index % 3),
        }
        target.write(json.dumps(record, ensure_ascii=False) + '\n')
print('Wrote %d synthetic demo battles: %s' % (48, path))
