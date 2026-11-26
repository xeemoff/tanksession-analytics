import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import package_release
from build import project_metadata, REQUIRED_MODULES, UI_ROOT, RESOURCE_MAP, PY27_MAGIC


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.mod_id, self.version = project_metadata()
        self.package = self.root / ('%s_%s.mtmod' % (self.mod_id, self.version))
        self.metadata = ('<root><id>%s</id><version>%s</version><name>Test</name></root>' %
                         (self.mod_id, self.version)).encode('utf-8')
        # A non-executable structural fixture. Installation copies bytes only.
        assets = {
            'meta.xml': self.metadata,
            UI_ROOT + 'Analytics.html': b'<html><link href="app.css"><script src="app.js"></script></html>',
            UI_ROOT + 'app.js': b'/* fixture, not a game application */',
            UI_ROOT + 'app.css': b'body { display: flex; }',
            UI_ROOT + 'THIRD_PARTY_LICENSES.txt': b'MIT License\nTest fixture only',
            RESOURCE_MAP: json.dumps([{
                'itemID': 'mods/tanksession/Analytics/layoutID', 'type': 'Layout',
                'path': 'coui://gui/gameface/mods/tanksession/Analytics.html',
                'parameters': {'entrance': 'Analytics', 'extension': '', 'impl': 'gameface'},
            }]).encode('utf-8'),
        }
        for name in REQUIRED_MODULES:
            assets[name] = PY27_MAGIC + b'\0' * 4 + b'c' + b'\0' * 8
        with zipfile.ZipFile(self.package, 'w', zipfile.ZIP_STORED) as output:
            for name, data in sorted(assets.items()):
                output.writestr(name, data)
        self.digest = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.package.with_suffix('.mtmod.sha256').write_text(
            '%s  %s\n' % (self.digest, self.package.name), encoding='ascii')
        for relative in ('installer/install.cmd', 'installer/Install-TankSession.ps1',
                         'docs/INSTALL_RU.md', 'docs/release-validation.json', 'LICENSE'):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        (self.root / 'docs/releases').mkdir()
        (self.root / ('docs/releases/v%s.md' % self.version)).write_text('Fixture release notes\n', encoding='utf-8')
        (self.root / 'docs/CLIENT_VALIDATION_RU.md').write_text('Fixture report\n', encoding='utf-8')
        if '-' not in self.version:
            validation_path = self.root / 'docs/release-validation.json'
            validation = json.loads(validation_path.read_text(encoding='utf-8'))
            validation.update({'status': 'verified', 'release_version': self.version,
                               'tested_client_version': '1.46.0.0', 'tested_at': '2026-01-01',
                               'tested_package_sha256': self.digest,
                               'checks': dict.fromkeys(package_release.CHECKS, True)})
            validation_path.write_text(json.dumps(validation), encoding='utf-8')
        self.root_patch = mock.patch.object(package_release, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def bundle(self):
        path, info = package_release.build_release(self.package)
        return path, info


class ReleaseTests(ReleaseFixture):
    def test_bundle_is_reproducible_and_contains_only_allowlisted_files(self):
        first, info = self.bundle()
        original = first.read_bytes()
        os.utime(self.package, (100, 100))
        second, _ = self.bundle()
        self.assertEqual(original, second.read_bytes())
        self.assertEqual(info['archive_sha256'], hashlib.sha256(original).hexdigest())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), {
                self.package.name, self.package.name + '.sha256', 'manifest.json',
                'install.cmd', 'Install-TankSession.ps1', 'INSTALL_RU.md',
                'RELEASE_NOTES_RU.md', 'LICENSE',
            })
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['sha256'], self.digest)
            self.assertEqual(manifest['package_size'], len(self.package.read_bytes()))
            self.assertEqual(manifest['client_versions'], ['1.46.0.0'])
            self.assertEqual(manifest['channel'], 'prerelease' if '-' in self.version else 'stable')
            self.assertEqual(manifest['native_validation'], 'pending' if '-' in self.version else 'verified')
            with zipfile.ZipFile(self.package) as package:
                self.assertEqual({member['path'] for member in manifest['members']}, set(package.namelist()))
                for member in manifest['members']:
                    self.assertEqual(member['sha256'], hashlib.sha256(package.read(member['path'])).hexdigest())

    def test_checksum_mismatch_stops_packaging(self):
        self.package.with_suffix('.mtmod.sha256').write_text('0' * 64 + '  ' + self.package.name, encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'SHA-256 sidecar'):
            self.bundle()

    def test_missing_notes_stops_instead_of_silently_shipping_old_notes(self):
        (self.root / ('docs/releases/v%s.md' % self.version)).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing regular release file'):
            self.bundle()

    def test_tag_must_match_package_version(self):
        with self.assertRaisesRegex(ValueError, 'Tag must match'):
            package_release.build_release(self.package, tag='v999.0.0')

    def test_stable_requires_exact_native_evidence(self):
        validation = json.loads((self.root / 'docs/release-validation.json').read_text(encoding='utf-8'))
        validation['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            package_release.release_gate('1.0.0', self.digest, validation)
        validation.update({'status': 'verified', 'release_version': '1.0.0',
                           'tested_client_version': '1.46.0.0', 'tested_at': '2026-01-01',
                           'tested_package_sha256': self.digest,
                           'checks': dict.fromkeys(package_release.CHECKS, True)})
        self.assertEqual(package_release.release_gate('1.0.0', self.digest, validation)['channel'], 'stable')
        for field, value, message in (
            ('tested_package_sha256', '0' * 64, 'SHA-256'),
            ('tested_client_version', '1.47.0.0', 'incomplete'),
            ('tested_at', '3000-01-01', 'future'),
            ('evidence', '../private.log', 'repository-local'),
        ):
            broken = dict(validation, **{field: value})
            with self.assertRaisesRegex(ValueError, message):
                package_release.release_gate('1.0.0', self.digest, broken)
        broken = dict(validation, checks=dict(validation['checks'], delayed_result='true'))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            package_release.release_gate('1.0.0', self.digest, broken)

    def test_installer_has_utf8_bom_for_windows_powershell_51(self):
        self.assertTrue((ROOT / 'installer/Install-TankSession.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))


@unittest.skipUnless(sys.platform == 'win32' and shutil.which('powershell.exe'),
                     'Installer transactions are exercised on Windows PowerShell 5.1 CI')
class WindowsInstallerTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        self.installer = self.root / 'extracted'
        self.installer.mkdir()
        archive, _ = self.bundle()
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(self.installer)
        self.game = self.root / 'game with spaces'
        self.version = '1.46.0.0'
        self.destination = self.game / 'mods' / self.version
        self.destination.mkdir(parents=True)
        (self.game / 'WorldOfTanks.exe').write_bytes(b'not an executable')
        self.config = self.game / 'mods/configs/tanksession_analytics/battles.jsonl'
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'private-history-sentinel\n')
        self.old = self.destination / 'ru.tanksession.analytics_0.1.0.mtmod'
        self.old.write_bytes(b'previous-package-sentinel')
        self.unrelated = self.destination / 'another.mod.mtmod'
        self.unrelated.write_bytes(b'unrelated-sentinel')

    @staticmethod
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    def run_installer(self, before='', version=None, check_only=False):
        args = ' '.join(self.quote(value) for value in (
            self.installer, self.game, self.version if version is None else version))
        expression = (
            "$ErrorActionPreference='Stop'; "
            ". %s; %s; try { Install-TankSessionBundle %s %s | ConvertTo-Json -Compress; exit 0 } "
            "catch { Write-Output $_.Exception.Message; exit 1 }"
        ) % (self.quote(self.installer / 'Install-TankSession.ps1'), before or '$null = 0',
             args, '$true' if check_only else '$false')
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-Command', expression], capture_output=True, timeout=45)

    def assert_private_data_untouched(self):
        self.assertEqual(self.config.read_bytes(), b'private-history-sentinel\n')
        self.assertEqual(self.unrelated.read_bytes(), b'unrelated-sentinel')

    def test_check_only_and_explicit_version(self):
        result = self.run_installer(check_only=True)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertTrue(self.old.exists())
        self.assertFalse((self.game / 'mods/tanksession_backups').exists())
        for version in ('', '1.47.0.0', '../configs'):
            rejected = self.run_installer(version=version)
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
        self.assert_private_data_untouched()

    def test_install_copies_new_and_preserves_old_in_verified_backup(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual((self.destination / self.package.name).read_bytes(), self.package.read_bytes())
        self.assertFalse(self.old.exists())
        backups = list((self.game / 'mods/tanksession_backups').glob('*/' + self.old.name))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'previous-package-sentinel')
        self.assert_private_data_untouched()

    def test_bad_hash_does_not_touch_game(self):
        (self.installer / self.package.name).write_bytes(b'broken')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.old.read_bytes(), b'previous-package-sentinel')
        self.assertFalse((self.game / 'mods/tanksession_backups').exists())
        self.assert_private_data_untouched()

    def test_failed_replacement_restores_old_package(self):
        result = self.run_installer(before="function Move-Item { throw 'Simulated destination failure' }")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.old.read_bytes(), b'previous-package-sentinel')
        self.assertFalse((self.destination / self.package.name).exists())
        self.assert_private_data_untouched()

    def test_running_game_prevents_changes(self):
        result = self.run_installer(before="function Get-Process { return [PSCustomObject]@{ ProcessName = 'WorldOfTanks' } }")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.old.read_bytes(), b'previous-package-sentinel')
        self.assertFalse((self.game / 'mods/tanksession_backups').exists())
        self.assert_private_data_untouched()
