"""Exercise real PowerShell transactions on Windows; fixture packages are inert."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import zipfile

from test_release import ReleaseFixture


@unittest.skipUnless(sys.platform == 'win32' and shutil.which('powershell.exe'),
                     'Windows PowerShell 5.1 manager integration')
class WindowsManagerTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        archive, _ = self.bundle()
        self.installer = self.root / 'extracted manager'
        with zipfile.ZipFile(archive) as source:
            source.extractall(self.installer)
        self.game = self.root / 'game with spaces'
        self.client = '1.46.0.0'
        self.destination = self.game / 'mods' / self.client
        self.destination.mkdir(parents=True)
        (self.game / 'WorldOfTanks.exe').write_bytes(b'inert')
        self.data = self.game / 'mods/configs/tanksession_analytics'
        self.data.mkdir(parents=True)
        self.history = self.data / 'battles.jsonl'
        self.history.write_bytes(b'{"arena_id":"1","account_id":"a","damage":500}\n')
        self.old = self.destination / 'ru.tanksession.analytics_0.1.0.mtmod'
        self.old.write_bytes(b'previous-package')
        self.unrelated = self.destination / 'unrelated.mtmod'
        self.unrelated.write_bytes(b'unrelated')

    @staticmethod
    def q(value):
        return "'" + str(value).replace("'", "''") + "'"

    def ps(self, body):
        command = ("$ErrorActionPreference='Stop'; "
                   "[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false; "
                   ". %s; try { %s } catch { Write-Output $_.Exception.Message; exit 1 }") % (
                       self.q(self.installer / 'Manage-TankSession.ps1'), body)
        return subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                               '-Command', command], capture_output=True, text=True,
                              encoding='utf-8', timeout=60)

    def good(self, body):
        result = self.ps(body)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        return result.stdout.strip()

    def export(self, path):
        self.good('Export-TankSessionHistory %s %s | ConvertTo-Json -Compress' %
                  (self.q(self.game), self.q(path)))

    def make_archive(self, path, files, extra=None, wrong_digest=False):
        manifest = {'schema': 1, 'kind': 'tanksession-history', 'created_at': '2026-11-27T00:00:00Z',
                    'files': [{'path': name, 'size': len(data),
                               'sha256': '0' * 64 if wrong_digest else hashlib.sha256(data).hexdigest()}
                              for name, data in files.items()]}
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as output:
            output.writestr('history-manifest.json', json.dumps(manifest))
            for name, data in files.items():
                output.writestr(name, data)
            if extra:
                output.writestr(extra[0], extra[1])

    def test_manager_form_constructs_and_scripts_parse(self):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(self.installer / 'TankSession-Manager.ps1'), '-SmokeTest'],
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        constructed = json.loads(result.stdout)
        self.assertEqual(constructed['Status'], 'constructed')
        self.assertGreaterEqual(constructed['Buttons'], 10)
        self.assertEqual(constructed['Client'], self.client)

    def test_discovery_only_accepts_real_game_roots_and_deduplicates(self):
        empty = self.root / 'not game'
        empty.mkdir()
        result = self.good('@(Find-TankSessionGames @(%s, %s, %s)) | ConvertTo-Json -Compress' %
                           (self.q(self.game), self.q(empty), self.q(self.game)))
        self.assertTrue(Path(json.loads(result)).samefile(self.game))

    def test_install_automatically_backs_up_history(self):
        before = self.history.read_bytes()
        result = json.loads(self.good('Install-TankSessionBundle %s %s %s | ConvertTo-Json -Compress' %
                                      (self.q(self.installer), self.q(self.game), self.q(self.client))))
        with zipfile.ZipFile(result['HistoryBackup']) as archive:
            self.assertEqual(archive.read('battles.jsonl'), before)
        self.assertEqual(self.history.read_bytes(), before)
        self.assertTrue((Path(result['Backup']) / 'backup-manifest.json').is_file())

    def test_install_snapshot_preserves_interrupted_profile_and_backup(self):
        profile = hashlib.sha256(b'synthetic-account').hexdigest() + '.json'
        profiles = self.data / 'profiles'
        profiles.mkdir()
        raw = json.dumps({'version': 2, 'preferences': {'vehicle': '', 'window': 10,
                          'tab': 'progress', 'density': 'normal', 'contrast': 'high'},
                          'goals': None}).encode('utf-8')
        for suffix in ('.rollback', '.bak.rollback'):
            (profiles / (profile + suffix)).write_bytes(raw)
        result = json.loads(self.good('Install-TankSessionBundle %s %s %s | ConvertTo-Json -Compress' %
                                      (self.q(self.installer), self.q(self.game), self.q(self.client))))
        with zipfile.ZipFile(result['HistoryBackup']) as archive:
            self.assertEqual(set(archive.namelist()), {'battles.jsonl', 'history-manifest.json',
                             'profiles/' + profile + '.rollback', 'profiles/' + profile + '.bak.rollback'})
            self.assertEqual(archive.read('profiles/' + profile + '.rollback'), raw)
            self.assertEqual(archive.read('profiles/' + profile + '.bak.rollback'), raw)
        self.assertFalse((profiles / profile).exists())
        self.assertEqual((profiles / (profile + '.rollback')).read_bytes(), raw)

    def test_interrupted_profile_export_import_retains_recoverable_bytes(self):
        profile = hashlib.sha256(b'synthetic-account').hexdigest() + '.json'
        profiles = self.data / 'profiles'
        profiles.mkdir()
        raw = json.dumps({'version': 2, 'preferences': {'vehicle': '', 'window': 10,
                          'tab': 'progress', 'density': 'normal', 'contrast': 'high'},
                          'goals': None}).encode('utf-8')
        files = {profile + '.rollback': raw, profile + '.bak.rollback': raw}
        for name, data in files.items():
            (profiles / name).write_bytes(data)
        # Temporary files and arbitrary extra suffixes are never transferable.
        for name in (profile + '.rollback.tmp', profile + '.bak.rollback.rollback', '.tsa-new.tmp'):
            (profiles / name).write_bytes(b'private temporary sentinel')
        archive = self.root / 'interrupted profile.zip'
        self.export(archive)
        with zipfile.ZipFile(archive) as saved:
            self.assertEqual(set(saved.namelist()), {'battles.jsonl', 'history-manifest.json'} |
                             {'profiles/' + name for name in files})
        for name in files:
            (profiles / name).unlink()
        self.good('Import-TankSessionHistory %s %s | ConvertTo-Json -Compress' %
                  (self.q(self.game), self.q(archive)))
        for name, data in files.items():
            self.assertEqual((profiles / name).read_bytes(), data)
        self.assertFalse((profiles / profile).exists())
        runtime_root = Path(__file__).resolve().parents[1] / 'src/res/scripts/client/gui/mods'
        sys.path.insert(0, str(runtime_root))
        from tanksession_analytics.workspace import Workspace
        workspace = Workspace(str(self.data))
        result = workspace.snapshot([], 'synthetic-account', {'protocol': 1, 'request_id': 'restart',
                                    'vehicle': '', 'window': 10, 'action': 'initialize'}, now=1700000999)
        self.assertTrue(result['workspace']['can_edit'])
        self.assertEqual(result['workspace']['preferences']['contrast'], 'high')
        self.assertEqual((profiles / profile).read_bytes(), raw)
        self.assertFalse((profiles / (profile + '.rollback')).exists())

    def test_profile_archive_names_accept_only_the_four_bounded_forms(self):
        profile = 'profiles/' + 'a' * 64 + '.json'
        allowed = [profile, profile + '.bak', profile + '.rollback', profile + '.bak.rollback']
        rejected = [profile + '.tmp', profile + '.rollback.bak', profile + '.rollback.rollback',
                    profile + '.bak.bak', profile + '\n', profile.replace('profiles/', 'profiles/../'),
                    profile.replace('a' * 64, 'a' * 63), profile.replace('a' * 64, 'A' * 64)]
        expressions = ','.join('(Test-TankSessionDataName %s)' % self.q(name) for name in allowed + rejected)
        result = json.loads(self.good('@(%s) | ConvertTo-Json -Compress' % expressions))
        self.assertEqual(result, [True] * len(allowed) + [False] * len(rejected))

    def test_rollback_only_import_refuses_an_existing_corresponding_main_before_writes(self):
        profile = 'a' * 64 + '.json'
        profiles = self.data / 'profiles'
        profiles.mkdir()
        before_history = self.history.read_bytes()
        for suffix in ('', '.bak'):
            main = profiles / (profile + suffix)
            main.write_bytes(b'existing main must not disappear')
            rollback = profiles / (profile + suffix + '.rollback')
            rollback.write_bytes(b'existing recovery must not disappear')
            archive = self.root / ('conflicting' + suffix + '.zip')
            self.make_archive(archive, {'profiles/' + rollback.name: b'imported recovery'})
            result = self.ps('Import-TankSessionHistory %s %s' % (self.q(self.game), self.q(archive)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('.rollback', result.stdout)
            self.assertEqual(main.read_bytes(), b'existing main must not disappear')
            self.assertEqual(rollback.read_bytes(), b'existing recovery must not disappear')
            self.assertEqual(self.history.read_bytes(), before_history)
            self.assertFalse((self.game / 'mods/tanksession_data_backups').exists())
            self.assertFalse(list((self.game / 'mods').glob('.tanksession-import-*')))
            main.unlink()
            rollback.unlink()

    def test_recovery_import_checks_only_its_exact_main_and_allows_complete_snapshot(self):
        profile = 'a' * 64 + '.json'
        profiles = self.data / 'profiles'
        profiles.mkdir()
        for index, (main_suffix, recovery_suffix) in enumerate((('', '.bak.rollback'), ('.bak', '.rollback'))):
            main = profiles / (profile + main_suffix)
            main.write_bytes(b'unrelated current profile file')
            recovery_name = profile + recovery_suffix
            archive = self.root / ('nonconflicting%d.zip' % index)
            self.make_archive(archive, {'profiles/' + recovery_name: b'imported recovery'})
            self.good('Import-TankSessionHistory %s %s | ConvertTo-Json -Compress' %
                      (self.q(self.game), self.q(archive)))
            self.assertEqual(main.read_bytes(), b'unrelated current profile file')
            self.assertEqual((profiles / recovery_name).read_bytes(), b'imported recovery')
            main.unlink()
            (profiles / recovery_name).unlink()
        (profiles / profile).write_bytes(b'current profile')
        archive = self.root / 'complete profile snapshot.zip'
        self.make_archive(archive, {'profiles/' + profile: b'imported main',
                                   'profiles/' + profile + '.rollback': b'imported recovery'})
        self.good('Import-TankSessionHistory %s %s | ConvertTo-Json -Compress' %
                  (self.q(self.game), self.q(archive)))
        self.assertEqual((profiles / profile).read_bytes(), b'imported main')
        self.assertEqual((profiles / (profile + '.rollback')).read_bytes(), b'imported recovery')

    def test_uninstall_and_restore_preserve_history_and_other_mods(self):
        before = self.history.read_bytes()
        result = json.loads(self.good('Set-TankSessionPackages %s %s %s | ConvertTo-Json -Compress' %
                                      (self.q(self.installer), self.q(self.game), self.q(self.client))))
        self.assertFalse(self.old.exists())
        self.good('Set-TankSessionPackages %s %s %s %s | ConvertTo-Json -Compress' %
                  (self.q(self.installer), self.q(self.game), self.q(self.client), self.q(result['Backup'])))
        self.assertEqual(self.old.read_bytes(), b'previous-package')
        self.assertEqual(self.history.read_bytes(), before)
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated')

    def test_corrupt_package_backup_cannot_replace_current(self):
        installed = json.loads(self.good('Install-TankSessionBundle %s %s %s | ConvertTo-Json -Compress' %
                                         (self.q(self.installer), self.q(self.game), self.q(self.client))))
        (Path(installed['Backup']) / self.old.name).write_bytes(b'corrupt')
        result = self.ps('Set-TankSessionPackages %s %s %s %s' %
                         (self.q(self.installer), self.q(self.game), self.q(self.client), self.q(installed['Backup'])))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.destination / self.package.name).read_bytes(), self.package.read_bytes())

    def test_history_export_import_roundtrip_with_previous_snapshot(self):
        original = self.history.read_bytes()
        settings = self.data / 'settings.json'
        settings.write_bytes(b'{"cache_enabled":false}')
        unknown = self.data / 'private-other.txt'
        unknown.write_bytes(b'keep this')
        pending = self.data / 'battles.jsonl.pending.jsonl'
        pending.write_bytes(b'not transferable')
        archive = self.root / 'my history.zip'
        self.export(archive)
        with zipfile.ZipFile(archive) as saved:
            self.assertEqual(set(saved.namelist()), {'battles.jsonl', 'settings.json', 'history-manifest.json'})
        self.history.write_bytes(b'{"arena_id":"2","account_id":"a"}\n')
        changed = self.history.read_bytes()
        restored = json.loads(self.good('Import-TankSessionHistory %s %s | ConvertTo-Json -Compress' %
                                        (self.q(self.game), self.q(archive))))
        self.assertEqual(self.history.read_bytes(), original)
        self.assertEqual(unknown.read_bytes(), b'keep this')
        self.assertEqual(pending.read_bytes(), b'not transferable')
        with zipfile.ZipFile(restored['Backup']) as backup:
            self.assertEqual(backup.read('battles.jsonl'), changed)

    def test_bad_history_hash_traversal_extra_and_duplicate_rejected_before_write(self):
        before = self.history.read_bytes()
        cases = [({'battles.jsonl': b'new'}, None, True),
                 ({'../outside': b'new'}, None, False),
                 ({'battles.jsonl': b'new'}, ('extra.exe', b'bad'), False),
                 ({'battles.jsonl': b'new'}, ('battles.jsonl', b'new'), False)]
        for i, (files, extra, bad_hash) in enumerate(cases):
            archive = self.root / ('bad%d.zip' % i)
            self.make_archive(archive, files, extra, bad_hash)
            result = self.ps('Import-TankSessionHistory %s %s' % (self.q(self.game), self.q(archive)))
            self.assertNotEqual(result.returncode, 0, (result.stdout, result.stderr))
            self.assertEqual(self.history.read_bytes(), before)
        self.assertFalse((self.game / 'mods/tanksession_data_backups').exists())

    def test_import_verification_failure_rolls_back_existing_file(self):
        before = self.history.read_bytes()
        archive = self.root / 'valid.zip'
        self.make_archive(archive, {'battles.jsonl': b'imported sentinel\n'})
        body = ("$script:originalHash=${function:Get-TankSessionHash}; "
                "function Get-TankSessionHash([string]$Path) { "
                "if ($Path.EndsWith('\\configs\\tanksession_analytics\\battles.jsonl') -and [IO.File]::ReadAllText($Path).Contains('imported sentinel')) { return ('0'*64) }; "
                "return & $script:originalHash $Path }; Import-TankSessionHistory %s %s") % (
                    self.q(self.game), self.q(archive))
        result = self.ps(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.history.read_bytes(), before, (result.stdout, result.stderr))
        self.assertEqual(len(list((self.game / 'mods/tanksession_data_backups').glob('*.zip'))), 1)

    def test_export_does_not_overwrite_an_existing_archive(self):
        archive = self.root / 'history.zip'
        archive.write_bytes(b'existing')
        result = self.ps('Export-TankSessionHistory %s %s' % (self.q(self.game), self.q(archive)))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(archive.read_bytes(), b'existing')

    def test_public_export_cannot_overlap_another_manager_transaction(self):
        archive = self.root / 'history.zip'
        lock = self.game / 'mods/.tanksession-install.lock'
        result = self.ps("$held=[IO.File]::Open(%s,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); "
                         "try { Export-TankSessionHistory %s %s } finally { $held.Dispose() }" %
                         (self.q(lock), self.q(self.game), self.q(archive)))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(archive.exists())

    def test_atomic_displaced_file_check_preserves_a_late_writer(self):
        before = self.history.read_bytes()
        archive = self.root / 'valid.zip'
        self.make_archive(archive, {'battles.jsonl': b'imported sentinel\n'})
        body = ("$script:originalHash=${function:Get-TankSessionHash}; $script:changed=$false; "
                "function Get-TankSessionHash([string]$Path) { "
                "$hash=& $script:originalHash $Path; "
                "if (-not $script:changed -and $Path.EndsWith('\\configs\\tanksession_analytics\\battles.jsonl')) { "
                "[IO.File]::AppendAllText($Path, 'late-writer'); $script:changed=$true }; "
                "return $hash }; Import-TankSessionHistory %s %s") % (self.q(self.game), self.q(archive))
        result = self.ps(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.history.read_bytes(), before + b'late-writer', (result.stdout, result.stderr))

    def test_cleanup_error_still_releases_exclusive_lock(self):
        archive = self.root / 'valid.zip'
        self.make_archive(archive, {'battles.jsonl': b'imported sentinel\n'})
        lock = self.game / 'mods/.tanksession-install.lock'
        result = self.good("function Remove-Item { param($LiteralPath,[switch]$Recurse,[switch]$Force) throw 'cleanup failure' }; "
                           "try { $null=Import-TankSessionHistory %s %s } catch { }; "
                           "$probe=[IO.File]::Open(%s,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); "
                           "$probe.Dispose(); Write-Output 'released'" % (self.q(self.game), self.q(archive), self.q(lock)))
        self.assertEqual(result, 'released')

    def test_running_game_blocks_history_and_package_changes(self):
        for call in ('Set-TankSessionPackages %s %s %s' % (self.q(self.installer), self.q(self.game), self.q(self.client)),
                     'Export-TankSessionHistory %s %s' % (self.q(self.game), self.q(self.root / 'archive.zip'))):
            result = self.ps('function Get-Process { return [PSCustomObject]@{ ProcessName="WorldOfTanks" } }; ' + call)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.old.exists())

    def test_update_selection_semver_channel_drafts_and_asset_requirement(self):
        releases = []
        for version, preview, draft, asset in [('1.0.0', False, False, True),
                                                ('2.0.0-rc.2', True, False, True),
                                                ('2.0.0-rc.10', True, False, True),
                                                ('3.0.0', False, True, True),
                                                ('4.0.0', False, False, False)]:
            releases.append({'tag_name': 'v' + version, 'draft': draft, 'prerelease': preview,
                             'assets': [{'name': 'TankSession_Analytics_' + version + '_Windows.zip',
                                         'state': 'uploaded'}] if asset else []})
        fixture = self.root / 'releases.json'
        fixture.write_text(json.dumps(releases), encoding='utf-8')
        for include, expected in [('$false', '1.0.0'), ('$true', '2.0.0-rc.10')]:
            result = json.loads(self.good("$releases=Get-Content -Raw %s | ConvertFrom-Json; "
                                          "Select-TankSessionUpdate @($releases) '0.9.0' %s | ConvertTo-Json -Compress" %
                                          (self.q(fixture), include)))
            self.assertEqual(result['Available'], expected)
            self.assertEqual(result['Url'], 'https://github.com/xeemoff/tanksession-analytics/releases/tag/v' + expected)
        self.assertEqual(self.good("Compare-TankSessionSemVer (ConvertTo-TankSessionSemVer '2.0.0') (ConvertTo-TankSessionSemVer '2.0.0-rc.10')"), '1')
