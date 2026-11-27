import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import package_native


def fixture_binary(platform_name):
    data = bytearray(256)
    if platform_name == 'windows-x64':
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3c, 128)
        data[128:132] = b'PE\0\0'
        struct.pack_into('<H', data, 132, 0x8664)
        struct.pack_into('<H', data, 152, 0x20b)
    else:
        data[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<H', data, 18, 62)
    return bytes(data)


class NativePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in package_native.SOURCE_FILES + ('src/meta.xml',):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        self.binary = self.root / 'fixture-binary'
        self.binary.write_bytes(fixture_binary('linux-x64'))
        self.probe = mock.patch.object(package_native.subprocess, 'run', return_value=
                                      subprocess.CompletedProcess([], 0, b'tanksession-native protocol 1\n', b''))
        self.probe_mock = self.probe.start()

    def tearDown(self):
        self.probe.stop()
        self.temporary.cleanup()

    def build(self, platform_name='linux-x64'):
        return package_native.build_bundle(self.binary, platform_name, root=self.root, source_commit='a' * 40)

    def test_fixed_allowlist_manifest_checksums_and_reproducible_bytes(self):
        private = self.root / 'profiles/private.json'
        private.parent.mkdir()
        private.write_text('PRIVATE-ACCOUNT-DO-NOT-PACK', encoding='utf-8')
        first, info = self.build()
        original = first.read_bytes()
        os.utime(self.binary, (100, 100))
        second, _ = self.build()
        self.assertEqual(original, second.read_bytes())
        self.assertEqual(info['archive_sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(first.name.startswith('TankSession_Analytics_'))
        self.assertTrue(first.name.endswith('_Native_Linux_x64.zip'))
        with zipfile.ZipFile(first) as archive:
            expected = set(package_native.SOURCE_FILES) | {
                'bin/tanksession-native', 'native_report.sh', 'START_NATIVE_RU.txt', 'manifest.json'}
            self.assertEqual(set(archive.namelist()), expected)
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['native_protocol'], 1)
            self.assertEqual(manifest['platform'], 'linux-x64')
            self.assertEqual(manifest['source_commit'], 'a' * 40)
            self.assertEqual({item['path'] for item in manifest['members']}, expected - {'manifest.json'})
            for item in manifest['members']:
                data = archive.read(item['path'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
                self.assertEqual(len(data), item['size'])
                self.assertNotIn(b'PRIVATE-ACCOUNT-DO-NOT-PACK', data)
            self.assertEqual((archive.getinfo('bin/tanksession-native').external_attr >> 16) & 0o777, 0o755)
            self.assertEqual((archive.getinfo('native_report.sh').external_attr >> 16) & 0o777, 0o755)
        self.assertEqual(first.with_suffix('.zip.sha256').read_text(encoding='ascii'),
                         '%s  %s\n' % (info['archive_sha256'], first.name))

    def test_windows_package_and_human_platform_alias(self):
        self.binary.write_bytes(fixture_binary('windows-x64'))
        path, info = self.build('Windows')
        self.assertEqual(info['platform'], 'windows-x64')
        self.assertTrue(path.name.endswith('_Native_Windows_x64.zip'))
        with zipfile.ZipFile(path) as archive:
            self.assertIn('bin/tanksession-native.exe', archive.namelist())
            launcher = archive.read('native_report.cmd')
            self.assertIn(b'--binary "%~dp0bin\\tanksession-native.exe"', launcher)
            self.assertIn(b'%*', launcher)
            self.assertNotIn('native_report.sh', archive.namelist())

    def test_malformed_architecture_and_failed_protocol_probe_are_rejected(self):
        for data in (b'not executable', fixture_binary('windows-x64')):
            self.binary.write_bytes(data)
            with self.assertRaises(ValueError):
                self.build()
        self.binary.write_bytes(fixture_binary('linux-x64'))
        for result in (subprocess.CompletedProcess([], 1, b'', b''),
                       subprocess.CompletedProcess([], 0, b'tanksession-native protocol 2\n', b'')):
            self.probe_mock.return_value = result
            with self.assertRaisesRegex(ValueError, 'protocol 1'):
                self.build()

    def test_missing_source_and_unsafe_commit_stop_before_archive(self):
        (self.root / 'tools/native_report.py').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            self.build()
        self.assertFalse((self.root / 'dist').exists())
        with self.assertRaisesRegex(ValueError, 'full SHA'):
            package_native.build_bundle(self.binary, 'linux-x64', root=self.root, source_commit='short')

    @unittest.skipIf(os.name == 'nt', 'Creating symlinks requires optional Windows privileges')
    def test_symlinked_sources_are_not_silently_packaged(self):
        path = self.root / 'tools/native_report.py'
        path.unlink()
        path.symlink_to(ROOT / 'tools/native_report.py')
        with self.assertRaisesRegex(ValueError, 'escapes|linked'):
            self.build()


class NativePackageExecutionTests(unittest.TestCase):
    def test_extracted_companion_runs_without_repository_or_downloaded_dependencies(self):
        configured = os.environ.get('TANKSESSION_NATIVE_BINARY')
        if not configured:
            self.skipTest('Set TANKSESSION_NATIVE_BINARY for the extracted-package executable smoke test')
        platform_name = 'windows-x64' if os.name == 'nt' else 'linux-x64'
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            archive, _ = package_native.build_bundle(configured, platform_name, output=folder)
            extracted = folder / 'companion with spaces'
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)
                for member in bundle.infolist():
                    if os.name != 'nt':
                        (extracted / member.filename).chmod((member.external_attr >> 16) & 0o777)
            binary = extracted / 'bin' / package_native.PLATFORMS[platform_name][1]
            data = extracted / 'sample_data/battles.jsonl'
            original = data.read_bytes()
            args = ['--data', str(data), '--account', 'demo', '--json']
            environment = dict(os.environ)
            environment.pop('TANKSESSION_NATIVE_BINARY', None)
            environment.pop('PYTHONPATH', None)
            # -I excludes PYTHONPATH and user site packages: imports must come
            # from the explicit allowlisted modules inside the extracted ZIP.
            result = subprocess.run([sys.executable, '-I', str(extracted / 'tools/native_report.py'),
                                     '--binary', str(binary)] + args, cwd=folder,
                                    env=environment, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            report = json.loads(result.stdout)
            self.assertEqual(report['engine'], 'cpp23')
            self.assertGreater(report['overall']['battles'], 0)
            self.assertEqual(data.read_bytes(), original)
            launcher = extracted / ('native_report.cmd' if os.name == 'nt' else 'native_report.sh')
            command = ['cmd.exe', '/d', '/c', str(launcher)] if os.name == 'nt' else [str(launcher)]
            launched = subprocess.run(command + args, cwd=folder, env=environment,
                                      capture_output=True, timeout=30)
            self.assertEqual(launched.returncode, 0, launched.stderr.decode('utf-8', 'replace'))
            self.assertEqual(json.loads(launched.stdout)['overall'], report['overall'])


if __name__ == '__main__':
    unittest.main()
