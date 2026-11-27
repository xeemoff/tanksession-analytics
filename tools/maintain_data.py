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
    """Read once; distinguish revisions, duplicates and genuinely invalid rows."""
    if os.path.islink(path):
        raise ValueError('Symlink journal is not supported')
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    details = dict(BattleStore(path).diagnostics)
    # Retain the old high-level key, but no longer label useful revisions or
    # benign duplicates as invalid data.
    details['invalid_or_unusable'] = details['malformed'] + details['invalid']
    return details


def _signature(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)


def compact(path):
    """Backup original + atomic replacement, only with an explicit user action.

    This is an offline operation: the game and dashboard must be closed. The
    signature checks detect ordinary concurrent modifications, but are not a
    substitute for a transaction/lock shared with every writer.
    """
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError('Expected an existing regular non-symlink file')
    path = os.path.abspath(path)
    before = os.stat(path)
    store = BattleStore(path)
    rows = store.compacted_records()
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
        if _signature(current) != _signature(before):
            raise RuntimeError('Journal changed while compacting; original untouched')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = path + '.backup-' + stamp
        # Exclusive backup creation prevents a previous backup being overwritten.
        with open(path, 'rb') as original, open(backup, 'xb') as saved:
            if _signature(os.fstat(original.fileno())) != _signature(before):
                raise RuntimeError('Journal changed before backup; original untouched')
            shutil.copyfileobj(original, saved)
            saved.flush()
            os.fsync(saved.fileno())
        if _signature(os.stat(path)) != _signature(before):
            raise RuntimeError('Journal changed during backup; original untouched')
        os.replace(candidate, path)
        return {'backup': backup, 'records': len(store.records), 'bytes': os.path.getsize(path),
                'diagnostics_before': dict(store.diagnostics)}
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
