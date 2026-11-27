"""Real PowerShell update/rollback transactions using inert offline release bytes.

The transport is replaced only in test subprocesses; all staging, hash, ZIP,
manifest, install, manager-pointer and relaunch checks are production functions.
Windows CI uses inbox PowerShell 5.1. An explicit local PowerShell override allows
additional cross-platform logic checks, never substitutes for that Windows job.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import unittest
import zipfile

from test_release import ReleaseFixture

POWERSHELL = (shutil.which('powershell.exe') if sys.platform == 'win32' else
              os.environ.get('TANKSESSION_TEST_POWERSHELL'))


@unittest.skipUnless(POWERSHELL, 'Windows PowerShell 5.1 updater integration')
class UpdateManagerTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        archive, _ = self.bundle()
        self.installer = self.root / "manager spaces '$&`"
        with zipfile.ZipFile(archive) as z:
            z.extractall(self.installer)
        self.game = self.root / "game spaces '$&`"
        self.client = '1.46.0.0'
        self.destination = self.game / 'mods' / self.client
        self.destination.mkdir(parents=True)
        (self.game / 'WorldOfTanks.exe').write_bytes(b'inert')
        self.old = self.destination / 'ru.tanksession.analytics_0.1.0.mtmod'
        self.old.write_bytes(b'previous package sentinel')
        self.other = self.destination / 'another-mod.mtmod'
        self.other.write_bytes(b'unrelated sentinel')
        self.data = self.game / 'mods/configs/tanksession_analytics'
        self.data.mkdir(parents=True)
        self.history = self.data / 'battles.jsonl'
        self.history.write_bytes(b'{"account_id":"synthetic","arena_id":"1"}\n')
        self.pointer = self.installer / '.tanksession-current.json'

    @staticmethod
    def q(value):
        return "'" + str(value).replace("'", "''") + "'"

    def ps(self, body):
        command = ("$ErrorActionPreference='Stop'; "
                   "[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false; "
                   "try { & { . %s; %s } } catch { Write-Output $_.Exception.Message; exit 1 }") % (
                       self.q(self.installer / 'Manage-TankSession.ps1'), body)
        args = [POWERSHELL, '-NoProfile']
        if sys.platform == 'win32':
            args.append('-STA')
        return subprocess.run(args + ['-ExecutionPolicy', 'Bypass', '-Command', command],
                              capture_output=True, text=True, encoding='utf-8', timeout=90)

    def good(self, body):
        result = self.ps(body)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        return result.stdout.strip()

    def update_fixture(self, version='9.1.0-rc.1', transform=None):
        folder = self.root / ('release-' + version)
        folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(self.package) as source:
            members = {n: source.read(n) for n in source.namelist()}
        members['meta.xml'] = ('<root><id>%s</id><version>%s</version><name>Fixture</name></root>' %
                               (self.mod_id, version)).encode()
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w', zipfile.ZIP_STORED) as z:
            for name, data in sorted(members.items()):
                z.writestr(name, data)
        package = 'ru.tanksession.analytics_' + version + '.mtmod'
        raw = memory.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        manifest = json.loads((self.installer / 'manifest.json').read_text())
        manifest.update(version=version, package=package, package_size=len(raw), sha256=digest,
                        channel='prerelease' if '-' in version else 'stable',
                        native_validation='pending' if '-' in version else 'verified',
                        members=[{'path': n, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
                                 for n, b in sorted(members.items())])
        files = {p.name: p.read_bytes() for p in self.installer.iterdir()
                 if p.is_file() and not p.name.startswith('.') and
                 not p.name.endswith(('.mtmod', '.mtmod.sha256'))}
        files.update({package: raw, package + '.sha256': (digest + '  ' + package + '\n').encode(),
                      'manifest.json': json.dumps(manifest).encode()})
        if transform:
            transform(files)
        name = 'TankSession_Analytics_' + version + '_Windows.zip'
        archive = folder / name
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, data in sorted(files.items()):
                z.writestr(n, data)
        checksum = folder / (name + '.sha256')
        checksum.write_bytes((hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + name + '\r\n').encode())
        release = {'tag_name': 'v' + version, 'draft': False, 'prerelease': '-' in version, 'assets': []}
        for path in (archive, checksum):
            release['assets'].append({'name': path.name, 'state': 'uploaded', 'size': path.stat().st_size,
                                      'browser_download_url': 'https://github.com/xeemoff/tanksession-analytics/releases/download/v' + version + '/' + path.name,
                                      'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()})
        metadata = folder / 'release.json'
        metadata.write_text(json.dumps(release), encoding='utf-8')
        return dict(folder=folder, archive=archive, checksum=checksum, metadata=metadata,
                    version=version, package=package, package_bytes=raw)

    def offline(self, fixture, extra=''):
        return ("function Get-TankSessionReleaseJson { param($Suffix,$Progress) "
                "Get-Content -LiteralPath %s -Raw -Encoding UTF8 | ConvertFrom-Json }; "
                "function Receive-TankSessionFile { param($Url,$Destination,$Limit,$Progress,$Stage,$Api) "
                "$source=if ($Url.EndsWith('.sha256')) { %s } else { %s }; "
                "[IO.File]::Copy($source,$Destination); %s }; ") % (
                    self.q(fixture['metadata']), self.q(fixture['checksum']), self.q(fixture['archive']), extra)

    def install(self, fixture, directory=None, preview=True):
        return "Install-TankSessionUpdate %s %s %s %s %s %s" % (
            self.q(directory or self.installer), self.q(self.installer), self.q(self.game),
            self.q(self.client), self.q(fixture['version']), '$true' if preview else '$false')

    def assert_untouched(self):
        self.assertEqual(self.old.read_bytes(), b'previous package sentinel')
        self.assertEqual(self.other.read_bytes(), b'unrelated sentinel')
        self.assertEqual(self.history.read_bytes(), b'{"account_id":"synthetic","arena_id":"1"}\n')
        self.assertFalse(self.pointer.exists())

    def test_first_update_backups_and_verified_manager_pointer(self):
        f = self.update_fixture()
        result = json.loads(self.good(self.offline(f) + self.install(f) + ' | ConvertTo-Json -Compress'))
        self.assertEqual(result['Status'], 'updated')
        self.assertEqual((self.destination / f['package']).read_bytes(), f['package_bytes'])
        self.assertFalse(self.old.exists())
        self.assertEqual((Path(result['Backup']) / self.old.name).read_bytes(), b'previous package sentinel')
        with zipfile.ZipFile(result['HistoryBackup']) as z:
            self.assertEqual(z.read('battles.jsonl'), self.history.read_bytes())
        active = json.loads(self.good('Read-TankSessionManagerPointer %s | ConvertTo-Json -Compress' % self.q(self.installer)))
        self.assertEqual(active['Version'], f['version'])
        self.assertTrue(Path(active['Directory']).samefile(result['Directory']))
        self.assertEqual(self.other.read_bytes(), b'unrelated sentinel')
        self.assertTrue((self.installer / self.package.name).is_file())

    def test_second_update_stays_anchored_at_original_launcher(self):
        first = self.update_fixture()
        a = json.loads(self.good(self.offline(first) + self.install(first) + ' | ConvertTo-Json -Compress'))
        second = self.update_fixture('9.1.0-rc.2')
        b = json.loads(self.good(self.offline(second) + self.install(second, a['Directory']) + ' | ConvertTo-Json -Compress'))
        active = json.loads(self.good('Read-TankSessionManagerPointer %s | ConvertTo-Json -Compress' % self.q(self.installer)))
        self.assertEqual(active['Version'], second['version'])
        self.assertTrue(Path(b['Directory']).parent.samefile(self.installer / '.tanksession-updates'))
        self.assertTrue(Path(a['Directory']).is_dir())
        self.assertFalse((Path(a['Directory']) / '.tanksession-current.json').exists())
        self.assertEqual((self.destination / second['package']).read_bytes(), second['package_bytes'])

    def test_cached_prerelease_refused_when_channel_is_now_stable(self):
        f = self.update_fixture()
        result = self.ps(self.offline(f) + self.install(f, preview=False))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()
        self.assertFalse((self.installer / '.tanksession-updates').exists())

    def test_hash_mismatch_and_network_failure_do_not_change_installation(self):
        f = self.update_fixture()
        f['archive'].write_bytes(f['archive'].read_bytes()[:-1] + b'x')
        result = self.ps(self.offline(f) + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()
        result = self.ps(self.offline(f) + "function Receive-TankSessionFile { throw 'synthetic network failure' }; " + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()
        self.assertFalse(list((self.installer / '.tanksession-updates').glob('incoming-*')))

    def test_unsafe_archive_extra_and_traversal_refused_before_install(self):
        for index, name in enumerate(('../escape.ps1', 'evil.exe', 'MANAGER.CMD')):
            def unsafe(files):
                files.pop('LICENSE')
                files[name] = b'inert'
            f = self.update_fixture('9.2.%d-rc.1' % index, unsafe)
            result = self.ps(self.offline(f) + self.install(f))
            self.assertNotEqual(result.returncode, 0, (name, result.stdout))
            self.assert_untouched()
        self.assertFalse((self.installer / 'escape.ps1').exists())

    def test_incompatible_client_refused_before_install(self):
        def change_client(files):
            m = json.loads(files['manifest.json']); m['client_versions'] = ['9.9.9.9']
            files['manifest.json'] = json.dumps(m).encode()
        f = self.update_fixture(transform=change_client)
        result = self.ps(self.offline(f) + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()

    def test_running_game_after_download_blocks_install(self):
        f = self.update_fixture()
        body = "$script:gameStarted=$false; function Get-Process { if ($script:gameStarted) { [PSCustomObject]@{ ProcessName='WorldOfTanks' } } }; "
        result = self.ps(body + self.offline(f, "$script:gameStarted=$true") + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()

    def test_actual_newer_installed_package_blocks_downgrade(self):
        f = self.update_fixture()
        newer = self.destination / 'ru.tanksession.analytics_10.0.0.mtmod'
        newer.write_bytes(b'newer sentinel')
        result = self.ps(self.offline(f) + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(newer.read_bytes(), b'newer sentinel')
        self.assert_untouched()

    def test_pointer_failure_rolls_back_package_and_keeps_history(self):
        f = self.update_fixture()
        result = self.ps(self.offline(f) + "function Set-TankSessionManagerPointer { throw 'synthetic pointer refusal' }; " + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pointer', result.stdout)
        self.assert_untouched()
        self.assertFalse((self.destination / f['package']).exists())
        self.assertTrue(list((self.game / 'mods/tanksession_backups').iterdir()))
        self.assertFalse([p for p in (self.installer / '.tanksession-updates').iterdir() if p.is_dir()])

    def test_interrupted_preparation_does_not_block_retry(self):
        folder = self.installer / '.tanksession-updates' / ('9.1.0-rc.1-' + 'a' * 64 + '-' + 'b' * 32)
        folder.mkdir(parents=True); (folder / 'inert.txt').write_bytes(b'orphan sentinel')
        f = self.update_fixture()
        self.good(self.offline(f) + self.install(f) + ' | ConvertTo-Json -Compress')
        self.assertEqual((folder / 'inert.txt').read_bytes(), b'orphan sentinel')

    def test_installed_new_package_old_pointer_can_finish_manager_update(self):
        f = self.update_fixture()
        # Simulates process exit after package commit but before pointer switch.
        (self.destination / f['package']).write_bytes(f['package_bytes'])
        self.old.unlink()
        result = json.loads(self.good(self.offline(f) + self.install(f) + ' | ConvertTo-Json -Compress'))
        self.assertEqual(result['Version'], f['version'])
        self.assertTrue(self.pointer.exists())

    def test_tampered_manager_member_and_pointer_traversal_are_not_loaded(self):
        f = self.update_fixture()
        result = json.loads(self.good(self.offline(f) + self.install(f) + ' | ConvertTo-Json -Compress'))
        (Path(result['Directory']) / 'TankSession-Manager.ps1').write_bytes(b'tamper sentinel')
        response = self.ps('Read-TankSessionManagerPointer %s' % self.q(self.installer))
        self.assertNotEqual(response.returncode, 0)
        pointer = json.loads(self.pointer.read_text())
        pointer['folder'] = '../outside'
        self.pointer.write_text(json.dumps(pointer))
        response = self.ps('Read-TankSessionManagerPointer %s' % self.q(self.installer))
        self.assertNotEqual(response.returncode, 0)

    def test_url_allowlist_rejects_credentials_nonhttps_other_repository_and_cdn_suffix(self):
        good = [('https://github.com/xeemoff/tanksession-analytics/releases/download/v2.0.0-rc3/TankSession_Analytics_2.0.0-rc3_Windows.zip', False, False),
                ('https://release-assets.githubusercontent.com/a?token=synthetic', True, False),
                ('https://api.github.com/repos/xeemoff/tanksession-analytics/releases?per_page=100', False, True)]
        bad = [('http://release-assets.githubusercontent.com/a', True, False),
               ('https://release-assets.githubusercontent.com.evil.test/a', True, False),
               ('https://user:password@release-assets.githubusercontent.com/a', True, False),
               ('https://release-assets.githubusercontent.com:444/a', True, False),
               ('https://github.com/other/repository/releases/download/v2/a.zip', False, False),
               ('https://api.github.com/repos/xeemoff/tanksession-analytics/releases', True, True)]
        for url, redirect, api in good + bad:
            call = 'Assert-TankSessionDownloadUri ([Uri]%s) %s %s' % (self.q(url), '$true' if redirect else '$false', '$true' if api else '$false')
            result = self.ps(call)
            self.assertEqual(result.returncode == 0, (url, redirect, api) in good, (url, result.stdout))

    def test_cleanup_refuses_unexpected_nested_directory(self):
        parent = self.root / 'temporary parent'; child = parent / 'created stage'; child.mkdir(parents=True)
        sentinel = child / 'unexpected' / 'keep.txt'; sentinel.parent.mkdir(); sentinel.write_bytes(b'keep')
        result = self.ps('Remove-TankSessionStage %s %s' % (self.q(child), self.q(parent)))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_bytes(), b'keep')


    def test_download_plan_rejects_forged_asset_url_and_missing_sidecar(self):
        f = self.update_fixture()
        release = json.loads(f['metadata'].read_text())
        for mutate in (lambda r: r['assets'][0].update(browser_download_url='https://evil.test/update.zip'),
                       lambda r: r['assets'].pop()):
            damaged = json.loads(json.dumps(release))
            mutate(damaged)
            f['metadata'].write_text(json.dumps(damaged))
            result = self.ps(self.offline(f) + self.install(f))
            self.assertNotEqual(result.returncode, 0)
            self.assert_untouched()
            self.assertFalse((self.installer / '.tanksession-updates').exists())

    def test_sidecar_wrong_filename_and_manager_protocol_refused(self):
        f = self.update_fixture()
        f['checksum'].write_bytes((hashlib.sha256(f['archive'].read_bytes()).hexdigest() + '  another.zip\r\n').encode())
        release = json.loads(f['metadata'].read_text())
        release['assets'][1].update(size=f['checksum'].stat().st_size,
                                    digest='sha256:' + hashlib.sha256(f['checksum'].read_bytes()).hexdigest())
        f['metadata'].write_text(json.dumps(release))
        result = self.ps(self.offline(f) + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()
        def incompatible(files):
            m = json.loads(files['manifest.json']); m['manager_update_protocol'] = 2
            files['manifest.json'] = json.dumps(m).encode()
        f = self.update_fixture('9.2.0-rc.1', incompatible)
        result = self.ps(self.offline(f) + self.install(f))
        self.assertNotEqual(result.returncode, 0)
        self.assert_untouched()

    def test_symlink_zip_member_and_oversized_member_refused(self):
        for index, symlink in enumerate((True, False)):
            f = self.update_fixture('9.3.%d-rc.1' % index)
            with zipfile.ZipFile(f['archive']) as z:
                contents = {n: z.read(n) for n in z.namelist()}
            with zipfile.ZipFile(f['archive'], 'w', zipfile.ZIP_DEFLATED) as z:
                for name, data in contents.items():
                    if name == 'LICENSE' and symlink:
                        entry = zipfile.ZipInfo(name)
                        entry.create_system = 3
                        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                        z.writestr(entry, b'../outside')
                    elif name == 'LICENSE':
                        z.writestr(name, b'x' * (2097152 + 1))
                    else:
                        z.writestr(name, data)
            digest = hashlib.sha256(f['archive'].read_bytes()).hexdigest()
            f['checksum'].write_bytes((digest + '  ' + f['archive'].name + '\n').encode())
            release = json.loads(f['metadata'].read_text())
            for asset, path in zip(release['assets'], (f['archive'], f['checksum'])):
                asset.update(size=path.stat().st_size, digest='sha256:' + hashlib.sha256(path.read_bytes()).hexdigest())
            f['metadata'].write_text(json.dumps(release))
            result = self.ps(self.offline(f) + self.install(f))
            self.assertNotEqual(result.returncode, 0)
            self.assert_untouched()

    def test_cleanup_accepts_parent_trailing_separator(self):
        parent = self.root / 'clean parent'; child = parent / 'created stage'; child.mkdir(parents=True)
        (child / 'download.zip').write_bytes(b'inert')
        self.good('Remove-TankSessionStage %s %s' % (self.q(child), self.q(str(parent) + os.sep)))
        self.assertFalse(child.exists())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows File.Replace access failure')
    def test_readonly_pointer_causes_real_replace_failure_and_package_rollback(self):
        first = self.update_fixture()
        a = json.loads(self.good(self.offline(first) + self.install(first) + ' | ConvertTo-Json -Compress'))
        before_pointer = self.pointer.read_bytes()
        self.pointer.chmod(stat.S_IREAD)
        try:
            second = self.update_fixture('9.1.0-rc.2')
            result = self.ps(self.offline(second) + self.install(second, a['Directory']))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.pointer.read_bytes(), before_pointer)
            self.assertEqual((self.destination / first['package']).read_bytes(), first['package_bytes'])
            self.assertFalse((self.destination / second['package']).exists())
        finally:
            self.pointer.chmod(stat.S_IREAD | stat.S_IWRITE)

    @unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Forms bootstrap')
    def test_bootstrap_reopens_new_manager_without_shell_path_interpolation(self):
        f = self.update_fixture()
        self.good(self.offline(f) + self.install(f) + ' | ConvertTo-Json -Compress')
        result = subprocess.run([POWERSHELL, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(self.installer / 'Start-TankSession.ps1'), '-SmokeTest'],
                                capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(json.loads(result.stdout)['Version'], f['version'])
        self.assertTrue(Path(json.loads(result.stdout)['ManagerRoot']).samefile(self.installer))
