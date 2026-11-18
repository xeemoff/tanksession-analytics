#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicitly offline, backup-first JSONL maintenance for battle history.

Close the game and dashboard before --compact. No automatic deletions are made.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.storage import BattleStore


def inspect(path):
    """Count valid, malformed and deduplicated rows without modifying the file."""
    if os.path.islink(path):
        raise ValueError('Symlink journal is not supported')
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    total, malformed = 0, 0
    with open(path, 'rb') as f:
        for line in f:
            total += 1
            try:
                if len(line) > 262144 or not isinstance(json.loads(line.decode('utf-8')), dict):
                    malformed += 1
            except (UnicodeDecodeError, ValueError, TypeError):
                malformed += 1
    records = BattleStore(path).records
    return {'lines': total, 'valid_unique': len(records),
            'invalid_or_unusable': total - len(records),
            'malformed': malformed,
            'duplicates_or_missing_id': total - len(records) - malformed}


def compact(path):
    """Backup original + atomic replacement, only with an explicit user action."""
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError('Expected an existing regular non-symlink file')
    path = os.path.abspath(path)
    before = os.stat(path)
    rows = BattleStore(path).records
    folder = os.path.dirname(path)
    fd, candidate = tempfile.mkstemp(prefix='.tanksession-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as out:
            for row in rows:
                out.write((json.dumps(row, ensure_ascii=False, sort_keys=True,
                                      allow_nan=False) + '\n').encode('utf-8'))
            out.flush()
            os.fsync(out.fileno())
        current = os.stat(path)
        if (current.st_size, current.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise RuntimeError('Journal changed while compacting; original untouched')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = path + '.backup-' + stamp
        # Exclusive backup creation prevents a previous backup being overwritten.
        with open(path, 'rb') as original, open(backup, 'xb') as saved:
            shutil.copyfileobj(original, saved)
            saved.flush()
            os.fsync(saved.fileno())
        os.replace(candidate, path)
        return {'backup': backup, 'records': len(rows), 'bytes': os.path.getsize(path)}
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


def main():
    parser = argparse.ArgumentParser(description='Safe offline battle-history maintenance')
    parser.add_argument('--data', required=True, help='Full path to battles.jsonl')
    parser.add_argument('--compact', action='store_true',
                        help='Backup + replace the journal, only when game is closed')
    args = parser.parse_args()
    try:
        print(json.dumps({'before': inspect(args.data)}, ensure_ascii=False))
        if args.compact:
            print('NOTICE: close the game/dashboard before compacting!')
            details = compact(args.data)
            print(json.dumps({'compacted': details, 'after': inspect(args.data)}, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, 'Maintenance failed: %s\n' % str(error))


if __name__ == '__main__':
    main()
