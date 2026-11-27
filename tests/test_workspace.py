# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
try:
    import builtins as builtins_module
except ImportError:
    import __builtin__ as builtins_module

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


class StrippedWindowsRuntime(object):
    """Model Windows Py2 rename rules with neither os.replace nor ctypes."""
    name = 'nt'

    def __init__(self):
        self.before_rename = None
        self.before_remove = None
        self.imports = []

    def __getattr__(self, name):
        if name == 'replace':
            raise AttributeError(name)
        return getattr(self.original_os, name)

    def rename(self, source, destination):
        if self.before_rename is not None:
            self.before_rename(source, destination)
        # POSIX rename overwrites, so explicitly model the Windows behavior.
        if self.original_os.path.lexists(destination):
            raise OSError('Windows rename destination already exists')
        return self.original_os.rename(source, destination)

    def remove(self, path):
        if self.before_remove is not None:
            self.before_remove(path)
        return self.original_os.remove(path)

    def __enter__(self):
        self.original_os = module.os
        self.original_import = builtins_module.__import__

        def without_ctypes(name, *args, **kwargs):
            if name == 'ctypes' or name.startswith('ctypes.') or name == '_ctypes':
                self.imports.append(name)
                raise ImportError('Embedded Python omits ctypes')
            return self.original_import(name, *args, **kwargs)

        module.os = self
        builtins_module.__import__ = without_ctypes
        return self

    def __exit__(self, *unused):
        module.os = self.original_os
        builtins_module.__import__ = self.original_import


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

    def read_bytes(self, path):
        with open(path, 'rb') as stream:
            return stream.read()

    def seed_profile(self):
        first = self.snapshot(command('save_preferences', request_id='seed-first',
                                      preferences=DEFAULT_PREFERENCES))
        self.assertEqual(first['workspace']['operation']['code'], 'preferences_saved')
        path = self.workspace._path('A')
        first_bytes = self.read_bytes(path)
        preferences = dict(DEFAULT_PREFERENCES, contrast='high')
        second = self.snapshot(command('save_preferences', request_id='seed-second',
                                       preferences=preferences))
        self.assertEqual(second['workspace']['operation']['code'], 'preferences_saved')
        return path, self.read_bytes(path), first_bytes

    def test_preferences_survive_reopen_and_are_account_scoped(self):
        preferences = dict(DEFAULT_PREFERENCES, vehicle='Tank', window=30,
                           contrast='high', density='compact', tab='history')
        result = self.snapshot(command('save_preferences', preferences=preferences))
        self.assertEqual(result['workspace']['operation']['code'], 'preferences_saved')
        self.workspace = Workspace(self.folder)
        restored = self.snapshot(command('initialize'))
        self.assertEqual(restored['selection'], {'vehicle': 'Tank', 'window': 30, 'page': 0,
                                                'history_query': '', 'history_sort': 'time_desc'})
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

    def test_stripped_windows_runtime_saves_new_existing_profiles_and_goals(self):
        folder = os.path.join(self.folder, u'Игры', u'Мир танков')
        self.workspace = Workspace(folder)
        self.rows = [record(1, vehicle=u'ИС-7'), record(2, account='B')]
        preferences = dict(DEFAULT_PREFERENCES, vehicle=u'ИС-7', contrast='high', window=30)
        goal = {'vehicle': u'ИС-7', 'window': 30, 'target_avg_damage': 1500}
        with StrippedWindowsRuntime() as runtime:
            first = self.snapshot(command('save_preferences', preferences=preferences))
            self.assertEqual(first['workspace']['operation']['code'], 'preferences_saved')
            path = self.workspace._path('A')
            first_bytes = self.read_bytes(path)
            second = self.snapshot(command('save_goal', request_id='add-goal', goal=goal))
            self.assertEqual(second['workspace']['operation']['code'], 'goal_saved')
            self.assertEqual(self.read_bytes(path + '.bak'), first_bytes)
            second_bytes = self.read_bytes(path)
            preferences = dict(preferences, density='compact')
            third = self.snapshot(command('save_preferences', request_id='repeat',
                                          preferences=preferences))
            self.assertEqual(third['workspace']['operation']['code'], 'preferences_saved')
            self.assertEqual(self.read_bytes(path + '.bak'), second_bytes)
            self.workspace = Workspace(folder)
            reopened = self.snapshot(command('initialize'))
            self.assertEqual(reopened['workspace']['preferences'], preferences)
            self.assertEqual(reopened['workspace']['goals'], [goal])
            self.assertEqual(reopened['summary']['battles'], 1)
            other = self.snapshot(command('initialize'), account='B')
            self.assertEqual(other['workspace']['preferences'], DEFAULT_PREFERENCES)
            deleted = self.snapshot(command('delete_goal', request_id='remove-goal',
                                            goal={'vehicle': u'ИС-7', 'window': 30}))
            self.assertEqual(deleted['workspace']['operation']['code'], 'goal_deleted')
            self.assertEqual(self.workspace._load('A')['goals'], [])
            self.assertTrue(runtime.imports)
            self.assertEqual(set(runtime.imports), {'ctypes'})
            self.assertFalse(any(name.endswith(('.tmp', '.rollback')) for name in
                                 os.listdir(os.path.dirname(path))))
        for name in ('battles.jsonl', 'battles.jsonl.pending.jsonl', 'goals.json'):
            self.assertEqual(self.read_bytes(os.path.join(self.folder, name)), self.original)

    def test_stripped_runtime_first_save_failure_keeps_default_snapshot(self):
        path = self.workspace._path('A')
        with StrippedWindowsRuntime() as runtime:
            def fail_install(source, destination):
                if destination == path:
                    raise IOError('PRIVATE_PROFILE_PATH')

            runtime.before_rename = fail_install
            result = self.snapshot(command('save_preferences',
                                          preferences=dict(DEFAULT_PREFERENCES, contrast='high')))
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['summary']['battles'], 1)
            self.assertEqual(result['workspace']['preferences'], DEFAULT_PREFERENCES)
            self.assertFalse(os.path.exists(path))
            self.assertEqual(os.listdir(os.path.dirname(path)), [])
            runtime.before_rename = None
            retried = self.snapshot(command('save_preferences', request_id='retry',
                                            preferences=dict(DEFAULT_PREFERENCES, contrast='high')))
            self.assertEqual(retried['workspace']['operation']['code'], 'preferences_saved')

    def test_stripped_runtime_replacement_failure_restores_previous_profile(self):
        path, previous, unused = self.seed_profile()
        with StrippedWindowsRuntime() as runtime:
            def fail_install(source, destination):
                if destination == path and source.endswith('.tmp'):
                    raise IOError('PRIVATE_DISK_REFUSAL')

            runtime.before_rename = fail_install
            result = self.snapshot(command('save_preferences', request_id='failed-save',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['summary']['battles'], 1)
            self.assertEqual(result['workspace']['preferences']['contrast'], 'high')
            self.assertEqual(self.read_bytes(path), previous)
            self.assertEqual(self.read_bytes(path + '.bak'), previous)
            self.assertFalse(any(name.endswith(('.tmp', '.rollback')) for name in
                                 os.listdir(os.path.dirname(path))))
            self.workspace = Workspace(self.folder)
            self.assertEqual(self.snapshot(command('initialize'))['workspace']['preferences']
                             ['contrast'], 'high')

    def test_stripped_runtime_backup_failure_keeps_current_and_previous_backup(self):
        path, previous, backup = self.seed_profile()
        with StrippedWindowsRuntime() as runtime:
            def fail_backup(source, destination):
                if destination == path + '.bak' and source.endswith('.tmp'):
                    raise IOError('PRIVATE_BACKUP_REFUSAL')

            runtime.before_rename = fail_backup
            result = self.snapshot(command('save_preferences', request_id='failed-backup',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(self.read_bytes(path), previous)
            self.assertEqual(self.read_bytes(path + '.bak'), backup)
            self.assertFalse(any(name.endswith(('.tmp', '.rollback')) for name in
                                 os.listdir(os.path.dirname(path))))

    def test_invalid_backup_recovery_reports_write_failure_not_an_invalid_goal(self):
        path, previous, backup = self.seed_profile()
        os.rename(path + '.bak', path + '.bak.rollback')
        with open(path + '.bak', 'wb') as stream:
            stream.write(b'{corrupt backup')
        with StrippedWindowsRuntime():
            result = self.snapshot(command('save_goal', request_id='invalid-backup',
                                          goal={'vehicle': 'Tank', 'window': 10,
                                                'target_avg_damage': 1500}))
        self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
        self.assertEqual(result['summary']['battles'], 1)
        self.assertEqual(result['workspace']['goals'], [])
        self.assertEqual(self.read_bytes(path), previous)
        self.assertEqual(self.read_bytes(path + '.bak'), b'{corrupt backup')
        self.assertEqual(self.read_bytes(path + '.bak.rollback'), backup)

    def test_stripped_runtime_failed_rollback_recovers_valid_profile_after_restart(self):
        path, previous, unused = self.seed_profile()
        with StrippedWindowsRuntime() as runtime:
            def fail_install_and_restore(source, destination):
                if destination == path:
                    raise IOError('PRIVATE_DESTINATION_UNAVAILABLE')

            runtime.before_rename = fail_install_and_restore
            result = self.snapshot(command('save_preferences', request_id='failed-rollback',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(result['workspace']['preferences']['contrast'], 'high')
            self.assertFalse(os.path.exists(path))
            self.assertEqual(self.read_bytes(path + '.rollback'), previous)
            # A new service instance must recover without a successful previous
            # finally/rollback, once the temporary filesystem failure ends.
            runtime.before_rename = None
            self.workspace = Workspace(self.folder)
            reopened = self.snapshot(command('initialize'))
            self.assertEqual(reopened['status'], 'ready')
            self.assertTrue(reopened['workspace']['can_edit'])
            self.assertEqual(reopened['workspace']['preferences']['contrast'], 'high')
            self.assertEqual(self.read_bytes(path), previous)
            self.assertFalse(os.path.exists(path + '.rollback'))
            retried = self.snapshot(command('save_preferences', request_id='recovered-save',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(retried['workspace']['operation']['code'], 'preferences_saved')

    def test_readonly_workspace_projects_recovery_and_refuses_all_mutations(self):
        path, previous, unused = self.seed_profile()
        os.rename(path, path + '.rollback')
        folder = os.path.dirname(path)
        before = dict((name, self.read_bytes(os.path.join(folder, name))) for name in os.listdir(folder))
        self.workspace = Workspace(self.folder, read_only=True)
        requests = [command('initialize'), command(),
                    command('save_preferences', preferences=DEFAULT_PREFERENCES),
                    command('save_goal', goal={'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 1500}),
                    command('delete_goal', goal={'vehicle': 'Tank', 'window': 10}),
                    command('export_csv')]
        for request in requests:
            result = self.snapshot(request)
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['summary']['battles'], 1)
            self.assertEqual(result['workspace']['preferences']['contrast'], 'high')
            self.assertFalse(result['workspace']['can_edit'])
            if request.get('action') in module.MUTATIONS:
                self.assertEqual(result['workspace']['operation']['code'], 'read_only')
            after = dict((name, self.read_bytes(os.path.join(folder, name))) for name in os.listdir(folder))
            self.assertEqual(after, before)
            self.assertFalse(os.path.exists(os.path.join(self.folder, 'exports')))
        for name in ('battles.jsonl', 'battles.jsonl.pending.jsonl', 'goals.json'):
            self.assertEqual(self.read_bytes(os.path.join(self.folder, name)), self.original)
        self.workspace = Workspace(self.folder)
        self.assertTrue(self.snapshot(command('initialize'))['workspace']['can_edit'])
        self.assertEqual(self.read_bytes(path), previous)
        self.assertFalse(os.path.exists(path + '.rollback'))

    def test_readonly_recovery_still_rejects_invalid_and_oversized_profiles(self):
        path = self.workspace._path('A')
        os.makedirs(os.path.dirname(path))
        self.workspace = Workspace(self.folder, read_only=True)
        for raw in (b'{broken', b'{}', b'x' * (module.MAX_PROFILE_BYTES + 1)):
            with open(path + '.rollback', 'wb') as stream:
                stream.write(raw)
            result = self.snapshot(command('initialize'))
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['summary']['battles'], 1)
            self.assertFalse(result['workspace']['can_edit'])
            self.assertEqual(result['workspace']['operation']['code'], 'read_failed')
            self.assertFalse(os.path.exists(path))
            self.assertEqual(self.read_bytes(path + '.rollback'), raw)

    def test_stripped_runtime_failed_backup_rollback_preserves_old_backup_for_retry(self):
        path, previous, backup = self.seed_profile()
        with StrippedWindowsRuntime() as runtime:
            def fail_backup_and_restore(source, destination):
                if destination == path + '.bak':
                    raise IOError('PRIVATE_BACKUP_DESTINATION_UNAVAILABLE')

            runtime.before_rename = fail_backup_and_restore
            result = self.snapshot(command('save_preferences', request_id='failed-backup-rollback',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(self.read_bytes(path), previous)
            self.assertFalse(os.path.exists(path + '.bak'))
            self.assertEqual(self.read_bytes(path + '.bak.rollback'), backup)
            runtime.before_rename = None
            self.workspace = Workspace(self.folder)
            retried = self.snapshot(command('save_preferences', request_id='backup-retry',
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(retried['workspace']['operation']['code'], 'preferences_saved')
            self.assertEqual(self.read_bytes(path + '.bak'), previous)
            self.assertFalse(os.path.exists(path + '.bak.rollback'))

    def test_stripped_runtime_interrupted_rename_recovers_previous_profile(self):
        path, previous, unused = self.seed_profile()
        # Abruptly exit a separate interpreter: neither rollback nor finally
        # cleanup may run. This leaves the real on-disk interrupted state.
        script = '''
import os
import sys
sys.path.insert(0, sys.argv[2])
from test_workspace import Workspace, StrippedWindowsRuntime, command, record, DEFAULT_PREFERENCES
workspace = Workspace(sys.argv[1])
path = workspace._path('A')
with StrippedWindowsRuntime() as runtime:
    def stop_before_install(source, destination):
        if destination == path and source.endswith('.tmp'):
            os._exit(23)
    runtime.before_rename = stop_before_install
    workspace.snapshot([record(1)], 'A', command('save_preferences', request_id='interrupted-save',
        preferences=dict(DEFAULT_PREFERENCES, density='compact')), now=1700000999)
sys.exit(24)
'''
        process = subprocess.Popen([sys.executable, '-c', script, self.folder,
                                    os.path.join(ROOT, 'tests')],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, errors = process.communicate()
        self.assertEqual(process.returncode, 23, (output, errors))
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.read_bytes(path + '.rollback'), previous)
        self.assertTrue(any(name.endswith('.tmp') for name in os.listdir(os.path.dirname(path))))
        with StrippedWindowsRuntime() as runtime:
            self.workspace = Workspace(self.folder)
            reopened = self.snapshot(command('initialize'))
            self.assertEqual(reopened['workspace']['preferences']['contrast'], 'high')
            self.assertEqual(self.read_bytes(path), previous)

    def test_stripped_runtime_committed_profile_wins_when_cleanup_is_interrupted(self):
        path, previous, unused = self.seed_profile()
        preferences = dict(DEFAULT_PREFERENCES, density='compact')
        with StrippedWindowsRuntime() as runtime:
            def failed_cleanup(candidate):
                if candidate == path + '.rollback':
                    raise OSError('PRIVATE_CLEANUP_REFUSAL')

            runtime.before_remove = failed_cleanup
            result = self.snapshot(command('save_preferences', request_id='committed-save',
                                          preferences=preferences))
            self.assertEqual(result['workspace']['operation']['code'], 'preferences_saved')
            self.assertEqual(self.read_bytes(path + '.rollback'), previous)
            self.workspace = Workspace(self.folder)
            reopened = self.snapshot(command('initialize'))
            self.assertEqual(reopened['workspace']['preferences'], preferences)
            # Read does not need cleanup permission. A later save retries it.
            self.assertTrue(os.path.exists(path + '.rollback'))
            runtime.before_remove = None
            self.snapshot(command('save_preferences', request_id='cleaned-save',
                                  preferences=DEFAULT_PREFERENCES))
            self.assertFalse(os.path.exists(path + '.rollback'))

    def test_invalid_destination_never_discards_a_valid_recovery_copy(self):
        path, previous, unused = self.seed_profile()
        os.rename(path, path + '.rollback')
        with open(path, 'wb') as stream:
            stream.write(b'{corrupt destination')
        result = self.snapshot(command('save_preferences', request_id='corrupt-recovery',
                                      preferences=DEFAULT_PREFERENCES))
        self.assertFalse(result['workspace']['can_edit'])
        self.assertEqual(result['workspace']['operation']['code'], 'read_failed')
        self.assertEqual(result['summary']['battles'], 1)
        self.assertEqual(self.read_bytes(path + '.rollback'), previous)
        self.assertEqual(self.read_bytes(path), b'{corrupt destination')

    def test_missing_destination_does_not_recover_invalid_or_oversized_bytes(self):
        path = self.workspace._path('A')
        os.makedirs(os.path.dirname(path))
        invalid_profiles = [b'{broken', b'{}', b'\xff', b'x' * (module.MAX_PROFILE_BYTES + 1),
                            json.dumps({'version': 2, 'preferences': DEFAULT_PREFERENCES,
                                        'goals': [{'vehicle': 'Tank', 'window': 10,
                                                   'target_avg_damage': 100, 'account_id': 'B'}]
                                        }).encode('utf-8')]
        for index, raw in enumerate(invalid_profiles):
            with open(path + '.rollback', 'wb') as stream:
                stream.write(raw)
            result = self.snapshot(command('save_preferences', request_id='invalid-%s' % index,
                                          preferences=DEFAULT_PREFERENCES))
            self.assertFalse(result['workspace']['can_edit'])
            self.assertEqual(result['workspace']['operation']['code'], 'read_failed')
            self.assertFalse(os.path.exists(path))
            self.assertEqual(self.read_bytes(path + '.rollback'), raw)

    def test_linked_recovery_file_is_never_followed(self):
        if not hasattr(os, 'symlink'):
            self.skipTest('Filesystem has no symlink API')
        path, previous, unused = self.seed_profile()
        target = path + '.outside'
        os.rename(path, target)
        try:
            os.symlink(target, path + '.rollback')
        except OSError:
            self.skipTest('Symlink creation is not available to this process')
        result = self.snapshot(command('save_preferences', preferences=DEFAULT_PREFERENCES))
        self.assertFalse(result['workspace']['can_edit'])
        self.assertEqual(result['workspace']['operation']['code'], 'read_failed')
        self.assertEqual(self.read_bytes(target), previous)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.islink(path + '.rollback'))

    def test_unavailable_write_dependency_keeps_snapshot_and_logs_only_stage_and_type(self):
        path, previous, unused = self.seed_profile()
        logs = []
        self.workspace._log = logs.append

        def fail_save(account, profile):
            raise ImportError('PRIVATE_PATH PRIVATE_ACCOUNT PRIVATE_PAYLOAD')

        self.workspace._save = fail_save
        for index in range(2):
            result = self.snapshot(command('save_preferences', request_id='no-module-%s' % index,
                                          preferences=dict(DEFAULT_PREFERENCES, density='compact')))
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['summary']['battles'], 1)
            self.assertEqual(result['workspace']['operation']['code'], 'write_failed')
            self.assertEqual(result['workspace']['preferences']['contrast'], 'high')
        self.assertEqual(logs, ['Workspace: save_preferences failed (ImportError)'])
        self.assertEqual(self.read_bytes(path), previous)

        def broken_logger(message):
            raise RuntimeError('PRIVATE_LOG_FAILURE')

        self.workspace._log = broken_logger
        self.workspace._reported.clear()
        result = self.snapshot(command('save_preferences', request_id='broken-log',
                                      preferences=DEFAULT_PREFERENCES))
        self.assertEqual(result['workspace']['operation']['code'], 'write_failed')

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
        # Python 2.7's real ctypes.wintypes imports VARIANT_BOOL, which cannot
        # be constructed by non-Windows ctypes. This test simulates the API;
        # the separate Windows-only test exercises the actual native types.
        windows_types = WindowsLibrary()
        windows_types.LPCWSTR = ctypes.c_wchar_p
        windows_types.DWORD = ctypes.c_ulong
        windows_types.BOOL = ctypes.c_int
        missing = object()
        original_os = module.os
        original_encoding = sys.getfilesystemencoding
        original_windll = getattr(ctypes, 'windll', missing)
        original_wintypes = getattr(ctypes, 'wintypes', missing)
        module.os = LegacyWindowsOS()
        sys.getfilesystemencoding = lambda: 'cp1251'
        ctypes.windll = library
        ctypes.wintypes = windows_types
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
            if original_windll is missing:
                del ctypes.windll
            else:
                ctypes.windll = original_windll
            if original_wintypes is missing:
                del ctypes.wintypes
            else:
                ctypes.wintypes = original_wintypes

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
