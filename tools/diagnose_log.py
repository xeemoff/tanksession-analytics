#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read TankSession events only and print counts, never raw identifiers or paths."""
import argparse
import json

MARKER = '[TankSession] '
CATEGORIES = (
    ('Started;', 'mod_started'),
    ('Stopped', 'mod_stopped'),
    ('Staged own battle', 'battle_staged'),
    ('Saved battle:', 'battle_saved'),
    ('Recovered battle:', 'battle_recovered'),
    ('Skipped incomplete/ambiguous', 'result_skipped'),
    ('Skipped battle due to account identity: identity_missing', 'identity_missing'),
    ('Skipped battle due to account identity: account_mismatch', 'account_mismatch'),
    ('Startup failed:', 'startup_error'),
    ('Battle capture failed:', 'capture_error'),
    ('Unable to stage battle:', 'stage_error'),
    ('Optional event unavailable:', 'optional_event_missing'),
    ('Hangar notification hook unavailable', 'hangar_hook_missing'),
    ('Optional cache recovery unavailable', 'cache_unavailable'),
    ('Result cache request unsupported', 'cache_request_error'),
)


def summarize_log(lines):
    counts = dict((name, 0) for _, name in CATEGORIES)
    counts['other_mod_messages'] = 0
    for line in lines:
        if MARKER not in line:
            continue
        message = line.split(MARKER, 1)[1].strip()
        for prefix, category in CATEGORIES:
            if message.startswith(prefix):
                counts[category] += 1
                break
        else:
            counts['other_mod_messages'] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description='Safe TankSession python.log diagnostics')
    parser.add_argument('--log', required=True, help='Path to the local python.log')
    parser.add_argument('--json', action='store_true', help='Print aggregate counts as JSON')
    args = parser.parse_args()
    try:
        with open(args.log, 'r', encoding='utf-8', errors='replace') as stream:
            report = summarize_log(stream)
    except OSError as error:
        parser.exit(1, 'Cannot read log: %s\n' % type(error).__name__)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print('TankSession Analytics — безопасная диагностика (только счётчики)')
        for name in sorted(report):
            print('%s: %d' % (name, report[name]))
        print('Отчёт не содержит ID аккаунтов, арены и путей к файлам.')


if __name__ == '__main__':
    main()
