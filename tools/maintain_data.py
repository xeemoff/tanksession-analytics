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


def _same_opened_file(by_path, by_handle):
    # CPython 3.12 on Windows exposes creation time through stat(path).ctime
    # but change time through fstat(fd).ctime. Compare ctime only with an
    # earlier observation from the SAME API; keep it in both signatures.
    return (os.path.samestat(by_path, by_handle) and
            by_path.st_size == by_handle.st_size and
            by_path.st_mtime_ns == by_handle.st_mtime_ns)


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
    candidate = None
    try:
        with open(path, 'rb') as original:
            opened_before = os.fstat(original.fileno())
            if not _same_opened_file(before, opened_before):
                raise RuntimeError('Journal changed before reading; original untouched')
            store = BattleStore(path)
            rows = store.compacted_records()
            folder = os.path.dirname(path)
            fd, candidate = tempfile.mkstemp(prefix='.tanksession-', suffix='.tmp', dir=folder)
            with os.fdopen(fd, 'wb') as out:
                for row in rows:
                    out.write((json.dumps(row, ensure_ascii=False, sort_keys=True,
                                          allow_nan=False) + '\n').encode('utf-8'))
                out.flush()
                os.fsync(out.fileno())
            if (_signature(os.stat(path)) != _signature(before) or
                    _signature(os.fstat(original.fileno())) != _signature(opened_before)):
                raise RuntimeError('Journal changed while compacting; original untouched')
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup = path + '.backup-' + stamp
            # Exclusive creation + fsync keep the original recoverable before
            # any replacement. Recheck the opened source after copying too.
            with open(backup, 'xb') as saved:
                shutil.copyfileobj(original, saved)
                saved.flush()
                os.fsync(saved.fileno())
            if _signature(os.fstat(original.fileno())) != _signature(opened_before):
                raise RuntimeError('Journal changed during backup; original untouched')
        # Windows cannot replace a file held by a normal Python read handle.
        # Close it first, then retain the final independent path check.
        if _signature(os.stat(path)) != _signature(before):
            raise RuntimeError('Journal changed during backup; original untouched')
        os.replace(candidate, path)
        return {'backup': backup, 'records': len(store.records), 'bytes': os.path.getsize(path),
                'diagnostics_before': dict(store.diagnostics)}
    finally:
        if candidate is not None and os.path.exists(candidate):
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
