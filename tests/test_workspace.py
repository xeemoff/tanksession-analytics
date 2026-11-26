# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))
from tanksession_analytics import workspace as module
from tanksession_analytics.workspace import Workspace, DEFAULT_PREFERENCES
from tanksession_analytics.presentation import validate_request


def record(index, account='A', vehicle='Tank', damage=1000):
    return dict(arena_id='private-arena-%s' % index, account_id=account,
                vehicle=vehicle, mode='1', outcome='win', damage=damage, xp=500,
                timestamp=1700000000 + index * 60)


def command(action=None, **fields):
    request = {'protocol': 1, 'request_id': 'command-1', 'vehicle': '', 'window': 10, 'page': 0}
    if action is not None:
        request['action'] = action
    request.update(fields)
    return request


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.folder))
        self.workspace = Workspace(self.folder)
        self.rows = [record(1), record(2, account='B', vehicle='Private other tank')]
        self.original = b'{"journal":"must stay unchanged"}\n'
        for name in ('battles.jsonl', 'battles.jsonl.pending.jsonl', 'goals.json'):
            with open(os.path.join(self.folder, name), 'wb') as stream:
                stream.write(self.original)

    def snapshot(self, request, account='A', **kwargs):
        return self.workspace.snapshot(self.rows, account, request, now=1700000999, **kwargs)

    def test_preferences_survive_reopen_and_are_account_scoped(self):
        preferences = dict(DEFAULT_PREFERENCES, vehicle='Tank', window=30,
                           contrast='high', density='compact', tab='history')
        result = self.snapshot(command('save_preferences', preferences=preferences))
        self.assertEqual(result['workspace']['operation']['code'], 'preferences_saved')
        self.workspace = Workspace(self.folder)
        restored = self.snapshot(command('initialize'))
        self.assertEqual(restored['selection'], {'vehicle': 'Tank', 'window': 30, 'page': 0})
        self.assertEqual(restored['workspace']['preferences'], preferences)
        other = self.snapshot(command('initialize'), account='B')
        self.assertEqual(other['workspace']['preferences'], DEFAULT_PREFERENCES)
        self.assertNotIn('private-arena', json.dumps(restored))
        self.assertNotIn('Private other tank', json.dumps(restored))
        self.assertNotIn('account_id', json.dumps(restored))

    def test_goals_can_be_replaced_and_deleted_without_editing_other_profiles(self):
        legacy = [{'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 500},
                  {'vehicle': 'Private other tank', 'window': 10,
                   'target_avg_damage': 9000, 'account_id': 'B'}]
        goal = {'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 1500}
        result = self.snapshot(command('save_goal', goal=goal), legacy_goals=legacy)
        self.assertEqual(result['workspace']['goals'], [goal])
        self.assertEqual(result['goals'][0]['target'], 1500)
        self.snapshot(command('delete_goal', goal={'vehicle': 'Tank', 'window': 10},
                              request_id='delete'), legacy_goals=legacy)
        self.assertEqual(self.snapshot(command(), legacy_goals=legacy)['workspace']['goals'], [])
        other = self.snapshot(command(), account='B', legacy_goals=legacy)
        self.assertEqual(len(other['workspace']['goals']), 2)
        for name in ('battles.jsonl', 'battles.jsonl.pending.jsonl', 'goals.json'):
            with open(os.path.join(self.folder, name), 'rb') as stream:
                self.assertEqual(stream.read(), self.original)

    def test_export_is_filtered_complete_utf8_and_contains_no_identifiers(self):
        self.rows = [record(i, vehicle=u'Т-34') for i in range(17)]
        self.rows += [record(20, vehicle='Other'), record(21, account='B')]
        result = self.snapshot(command('export_csv', vehicle=u'Т-34', page=2))
        operation = result['workspace']['operation']
        self.assertEqual(operation['status'], 'exported')
        self.assertEqual(operation['rows'], 17)
        self.assertEqual(operation['filename'], os.path.basename(operation['filename']))
        path = os.path.join(self.folder, 'exports', operation['filename'])
        with open(path, 'rb') as stream:
            raw = stream.read()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        text = raw.decode('utf-8-sig')
        self.assertIn(u'Т-34', text)
        self.assertEqual(len(text.splitlines()), 18)
        for secret in ('private-arena', 'account_id', 'arena_id', 'Other'):
            self.assertNotIn(secret, text)
        # A duplicate delivery and later passive refresh never create files.
        self.snapshot(command('export_csv', vehicle=u'Т-34', page=2))
        self.snapshot(command(vehicle=u'Т-34'))
        self.assertEqual(len(os.listdir(os.path.dirname(path))), 1)

    def test_csv_formula_cells_are_text_but_negative_credits_stay_numeric(self):
        self.rows = [dict(record(1, vehicle='=1+2'), map=' @SUM(A1:A2)', credits_net=-100)]
        result = self.snapshot(command('export_csv'))
        with io.open(os.path.join(self.folder, 'exports', result['workspace']['operation']['filename']),
                     encoding='utf-8-sig') as stream:
            text = stream.read()
        self.assertIn('"\'=1+2"', text)
        self.assertIn('"\'@SUM(A1:A2)"', text)
        self.assertIn('"-100"', text)

    def test_unknown_account_never_reads_or_writes_a_profile(self):
        for account in (None, '', 'local', 'unknown', True, -1):
            snapshot = self.snapshot(command('save_preferences', preferences=DEFAULT_PREFERENCES),
                                     account=account)
            self.assertEqual(snapshot['status'], 'account_unavailable')
            self.assertNotIn('workspace', snapshot)
        self.assertFalse(os.path.exists(os.path.join(self.folder, 'profiles')))

    def test_corrupt_profile_is_read_only_and_is_not_overwritten(self):
        path = self.workspace._path('A')
        os.makedirs(os.path.dirname(path))
        with open(path, 'wb') as stream:
            stream.write(b'{broken')
        result = self.snapshot(command('save_preferences', preferences=DEFAULT_PREFERENCES))
        self.assertFalse(result['workspace']['can_edit'])
        self.assertEqual(result['workspace']['operation']['code'], 'read_failed')
        with open(path, 'rb') as stream:
            self.assertEqual(stream.read(), b'{broken')

    def test_profile_goals_do_not_depend_on_a_broken_legacy_file(self):
        goal = {'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 1000}
        self.snapshot(command('save_goal', goal=goal))

        def broken_legacy():
            raise ValueError('Broken old goals file')

        result = self.snapshot(command(), legacy_goals=broken_legacy)
        self.assertTrue(result['workspace']['can_edit'])
        self.assertEqual(result['workspace']['goals'], [goal])
        other = self.snapshot(command(), account='B', legacy_goals=broken_legacy)
        self.assertFalse(other['workspace']['can_edit'])
        self.assertEqual(other['summary']['battles'], 1)

    def test_failed_replacement_keeps_last_profile_and_reports_error(self):
        self.snapshot(command('save_preferences', preferences=DEFAULT_PREFERENCES))
        original_replace = module._replace
        path = self.workspace._path('A')

        def fail_profile(source, destination):
            if destination == path:
                raise IOError('Simulated disk refusal')
            return original_replace(source, destination)

        module._replace = fail_profile
        try:
            result = self.snapshot(command('save_preferences', request_id='second',
                             preferences=dict(DEFAULT_PREFERENCES, contrast='high')))
        finally:
            module._replace = original_replace
        self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
        self.assertEqual(self.workspace._load('A')['preferences'], DEFAULT_PREFERENCES)
        self.assertTrue(os.path.isfile(path + '.bak'))
        self.assertFalse(any(name.endswith('.tmp') for name in os.listdir(os.path.dirname(path))))

    def test_windows_legacy_byte_paths_use_filesystem_encoding(self):
        import ctypes

        class LegacyWindowsOS(object):
            name = 'nt'  # No os.replace, as on Windows Python 2.7.

        class MoveFile(object):
            def __init__(self):
                self.calls = []

            def __call__(self, source, destination, flags):
                self.calls.append((source, destination))
                return 1

        class WindowsLibrary(object):
            pass

        move = MoveFile()
        library = WindowsLibrary()
        library.kernel32 = WindowsLibrary()
        library.kernel32.MoveFileExW = move
        original_os = module.os
        original_encoding = sys.getfilesystemencoding
        original_windll = getattr(ctypes, 'windll', None)
        module.os = LegacyWindowsOS()
        sys.getfilesystemencoding = lambda: 'cp1251'
        ctypes.windll = library
        try:
            source = u'C:\\Игры\\Танки\\profiles\\.tsa-new.tmp'
            destination = u'C:\\Игры\\Танки\\profiles\\profile.json'
            module._replace(source.encode('cp1251'), destination.encode('cp1251'))
            self.assertEqual(move.calls, [(source, destination)])
            # Already-Unicode paths must cross the same boundary unchanged.
            module._replace(source, destination)
            self.assertEqual(move.calls[-1], (source, destination))
            # An undecodable filename must fail instead of moving a different
            # path that contains replacement characters.
            with self.assertRaises(UnicodeDecodeError):
                module._replace(b'C:\\bad-\x98.tmp', destination)
            self.assertEqual(len(move.calls), 2)
        finally:
            module.os = original_os
            sys.getfilesystemencoding = original_encoding
            if original_windll is None:
                del ctypes.windll
            else:
                ctypes.windll = original_windll

    @unittest.skipUnless(os.name == 'nt', 'Exercises the real Windows MoveFileExW fallback')
    def test_windows_legacy_replace_preserves_unicode_profile_and_backup(self):
        # Windows CI normally takes os.replace, which Python 2.7 does not
        # provide. Exercise the real Win32 fallback with Unicode paths and
        # repeated replacements of both the profile and its existing backup.
        original_replace = getattr(os, 'replace', None)
        if original_replace is not None:
            del os.replace
        try:
            folder = os.path.join(self.folder, u'Игры', u'Мир танков')
            workspace = Workspace(folder)
            rows = [record(1, vehicle=u'ИС-7')]
            preferences = dict(DEFAULT_PREFERENCES, vehicle=u'ИС-7', window=30)
            first = workspace.snapshot(rows, 'A', command('save_preferences',
                request_id='win-first', preferences=preferences), now=1700000999)
            self.assertEqual(first['workspace']['operation']['code'], 'preferences_saved')
            path = workspace._path('A')
            with open(path, 'rb') as stream:
                first_bytes = stream.read()

            goal = {'vehicle': u'ИС-7', 'window': 30, 'target_avg_damage': 1500}
            second = workspace.snapshot(rows, 'A', command('save_goal',
                request_id='win-second', goal=goal), now=1700000999)
            self.assertEqual(second['workspace']['operation']['code'], 'goal_saved')
            with open(path + '.bak', 'rb') as stream:
                self.assertEqual(stream.read(), first_bytes)
            with open(path, 'rb') as stream:
                second_bytes = stream.read()

            updated = dict(preferences, contrast='high')
            third = workspace.snapshot(rows, 'A', command('save_preferences',
                request_id='win-third', preferences=updated), now=1700000999)
            self.assertEqual(third['workspace']['operation']['code'], 'preferences_saved')
            with open(path + '.bak', 'rb') as stream:
                self.assertEqual(stream.read(), second_bytes)
            reopened = Workspace(folder).snapshot(rows, 'A', command('initialize'),
                                                 now=1700000999)
            self.assertEqual(reopened['workspace']['preferences'], updated)
            self.assertEqual(reopened['workspace']['goals'], [goal])
            self.assertFalse(any(name.endswith('.tmp') for name in
                                 os.listdir(os.path.dirname(path))))
        finally:
            if original_replace is not None:
                os.replace = original_replace

    def test_commands_reject_identity_paths_invalid_numbers_and_extra_fields(self):
        bad = [command('export_csv', path='../out.csv'), command('export_csv', account_id='B'),
               command(page=True), command(page=-1), command(page=1000001), command(action='unknown'),
               command('save_goal', goal={'vehicle': 'Tank', 'window': True, 'target_avg_damage': 10}),
               command('save_goal', goal={'vehicle': 'Tank', 'window': 10, 'target_avg_damage': '10'}),
               command('delete_goal', goal={'vehicle': 'Tank', 'window': 10, 'account_id': 'B'}),
               command('save_preferences', preferences=dict(DEFAULT_PREFERENCES, window=True)),
               command('save_preferences', preferences=dict(DEFAULT_PREFERENCES, tab='../../')),
               command(preferences=DEFAULT_PREFERENCES)]
        for request in bad:
            with self.assertRaises(ValueError):
                validate_request(request)


if __name__ == '__main__':
    unittest.main()
