#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Run pure-module smoke tests or compile this checkout using real CPython 2.7.

The private --compile-stage mode reads only bytecode it has just created with
py_compile. It never imports source modules or accepts an existing .mtmod.
The default mode exercises the trusted checkout, without any game client.
"""
from __future__ import print_function

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GAME_ROOT = os.path.join('res', 'scripts', 'client', 'gui', 'mods')
SOURCE_EPOCH = 946684800  # 2000-01-01 UTC, independent of checkout and build time.


def require_python2():
    if sys.version_info[:2] != (2, 7) or platform.python_implementation() != 'CPython':
        raise ValueError('This helper requires a real CPython 2.7 interpreter')
    import imp
    if imp.get_magic() != b'\x03\xf3\r\n':
        raise ValueError('Unexpected CPython 2.7 bytecode magic')


def compile_stage(stage):
    import imp
    import marshal
    import py_compile
    import types

    stage = os.path.abspath(stage)
    count = 0
    for base, folders, files in os.walk(os.path.join(stage, GAME_ROOT)):
        folders[:] = sorted(folders)
        for name in sorted(files):
            if not name.endswith('.py'):
                continue
            source = os.path.join(base, name)
            relative = os.path.relpath(source, stage).replace(os.sep, '/')
            os.utime(source, (SOURCE_EPOCH, SOURCE_EPOCH))
            py_compile.compile(source, cfile=source + 'c', dfile=relative, doraise=True)
            with open(source + 'c', 'rb') as compiled:
                if compiled.read(4) != imp.get_magic():
                    raise ValueError('Compiler emitted an unexpected bytecode header')
                compiled.read(4)  # Timestamp, fixed above.
                # Only our own immediately generated output is deserialized.
                code = marshal.load(compiled)
                if not isinstance(code, types.CodeType) or compiled.read(1):
                    raise ValueError('Compiler did not emit exactly one code object')
            pending = [code]
            while pending:
                current = pending.pop()
                if current.co_filename != relative:
                    raise ValueError('Absolute/unstable filename in generated code')
                pending.extend(value for value in current.co_consts
                               if isinstance(value, types.CodeType))
            count += 1
    if not count:
        raise ValueError('No source modules in the staging directory')
    return {'compiled_modules': count, 'code_objects_checked': True}


def runtime_suite():
    sys.path.insert(0, os.path.join(ROOT, 'src', GAME_ROOT))
    from tanksession_analytics.analytics import rolling_damage
    from tanksession_analytics.core import normalize_result, summarize, validate_record
    from tanksession_analytics.goals import evaluate_goals, validate_goals
    from tanksession_analytics.recorder import ResultRecorder
    from tanksession_analytics.storage import BattleStore, PendingJournal

    class Python2RuntimeTests(unittest.TestCase):
        def make_record(self, arena=101):
            return normalize_result(
                {'arenaUniqueID': arena, 'common': {'winnerTeam': 1, 'bonusType': 1},
                 'personal': {42: {'team': 1, 'damageDealt': '2500', 'xp': 900}}},
                {'account_id': '101', 'player_vehicle_id': 42, 'vehicle_name': u'ИС-7'},
                observed_at=1700000000 + arena)

        def test_normalization_and_unknown_metric(self):
            record = self.make_record()
            self.assertEqual(record['vehicle'], u'ИС-7')
            self.assertEqual(record['damage'], 2500)
            self.assertEqual(record['outcome'], 'win')
            self.assertIsNone(record['assistance_radio'])
            self.assertEqual(summarize([record])['avg_damage'], 2500.0)
            self.assertIsNone(validate_record(dict(record, outcome=[])))

        def test_utf8_storage_survives_restart_and_duplicate(self):
            folder = tempfile.mkdtemp(prefix='tanksession-py27-')
            try:
                path = os.path.join(folder, u'журнал', 'battles.jsonl')
                row = self.make_record()
                first = BattleStore(path)
                self.assertTrue(first.append(row))
                reopened = BattleStore(path)
                self.assertFalse(reopened.append(row))
                self.assertEqual(len(reopened.records), 1)
                self.assertEqual(reopened.records[0]['vehicle'], u'ИС-7')
            finally:
                shutil.rmtree(folder)

        def test_full_window_and_goals(self):
            rows = [self.make_record(100 + i) for i in range(10)]
            goals = validate_goals([{'vehicle': u'ИС-7', 'target_avg_damage': 2400,
                                     'window': 10}])
            self.assertEqual(rolling_damage(rows, window=10)[-1][1], 2500.0)
            self.assertEqual(evaluate_goals(rows[:9], goals)[0]['status'], 'in_progress')
            self.assertEqual(evaluate_goals(rows, goals)[0]['status'], 'achieved')

        def test_partial_result_revision_closes_pending_after_restart(self):
            folder = tempfile.mkdtemp(prefix='tanksession-py27-revision-')
            try:
                path = os.path.join(folder, 'battles.jsonl')
                pending_path = os.path.join(folder, 'pending.jsonl')
                context = {'account_id': '101', 'player_vehicle_id': 42,
                           'vehicle_name': u'ИС-7', 'team': 1}
                payload = {'arenaUniqueID': 101,
                           'common': {'winnerTeam': 1, 'bonusType': 1},
                           'personal': {42: {'team': 1, 'damageDealt': None, 'xp': 900}}}
                pending = PendingJournal(pending_path)
                self.assertTrue(pending.start(101, context, 1700000000))
                recorder = ResultRecorder(BattleStore(path), pending, require_account=True)
                status, record = recorder.receive(payload, context, observed_at=1700000010)
                self.assertEqual((status, record['data_status']), ('saved', 'incomplete'))
                self.assertIn('101', PendingJournal(pending_path).pending)

                pending = PendingJournal(pending_path)
                recorder = ResultRecorder(BattleStore(path), pending, require_account=True)
                payload['personal'][42]['damageDealt'] = 2500
                status, record = recorder.receive(payload, context, observed_at=1700000020)
                self.assertEqual((status, record['data_status'], record['damage']),
                                 ('updated', 'complete', 2500))
                self.assertEqual(PendingJournal(pending_path).pending, {})

                reopened = BattleStore(path)
                recorder = ResultRecorder(reopened, PendingJournal(pending_path),
                                          require_account=True)
                self.assertEqual(recorder.receive(payload, context,
                                                  observed_at=1700000030)[0], 'duplicate')
                self.assertEqual(len(reopened.records), 1)
                self.assertEqual(reopened.records[0]['timestamp'], 1700000010)
                self.assertEqual(reopened.diagnostics['lines'], 2)
                self.assertEqual(reopened.diagnostics['revisions'], 1)
            finally:
                shutil.rmtree(folder)

        def test_goals_do_not_combine_two_accounts_into_a_full_window(self):
            rows = [self.make_record(300 + i) for i in range(10)]
            for row in rows[5:]:
                row['account_id'] = '202'
            goals = [{'vehicle': u'ИС-7', 'target_avg_damage': 2400, 'window': 10}]
            results = evaluate_goals(rows, goals)
            self.assertEqual(set(item['account_id'] for item in results), set(['101', '202']))
            self.assertEqual(len(results), 2)
            self.assertTrue(all(item['battles'] == 5 and item['status'] == 'in_progress'
                                for item in results))

    return unittest.defaultTestLoader.loadTestsFromTestCase(Python2RuntimeTests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-stage', metavar='DIRECTORY',
                        help='Private build mode: compile staged source, not an existing package')
    args = parser.parse_args()
    try:
        require_python2()
        if args.compile_stage:
            print(json.dumps(compile_stage(args.compile_stage), sort_keys=True))
            return 0
        print('Runtime smoke test: CPython %s (no live game)' % platform.python_version())
        result = unittest.TextTestRunner(verbosity=2).run(runtime_suite())
        return 0 if result.wasSuccessful() else 1
    except (IOError, OSError, ValueError) as error:
        parser.exit(1, '%s\n' % error)


if __name__ == '__main__':
    sys.exit(main())
