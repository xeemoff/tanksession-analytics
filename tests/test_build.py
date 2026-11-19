import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build import (build, verify_mtmod, project_metadata, ENTRY, REQUIRED_MODULES,
                   REQUIRED_ASSETS, REQUIRED_FILES, UI_ROOT, RESOURCE_MAP,
                   PY27_MAGIC, ZIP_DATE)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.archive = os.path.join(self.folder.name, 'sample.mtmod')
        self.mod_id, self.version = project_metadata()
        self.meta = ('<root><id>%s</id><version>%s</version><name>Test</name></root>' %
                     (self.mod_id, self.version)).encode('utf-8')
        # Header-only fixture, intentionally NOT executable bytecode.
        # --verify promises structure/headers, never full bytecode validation.
        self.header_fixture = PY27_MAGIC + b'\x00' * 4 + b'c' + b'\x00' * 8
        self.assets = {
            UI_ROOT + 'Analytics.html': b'<html><link href="app.css"><script src="app.js"></script></html>',
            UI_ROOT + 'app.js': b'/* test asset, not a React application */',
            UI_ROOT + 'app.css': b'body { display: flex; }',
            UI_ROOT + 'THIRD_PARTY_LICENSES.txt': b'MIT License\nTest fixture only',
            RESOURCE_MAP: json.dumps([{
                'itemID': 'mods/tanksession/Analytics/layoutID', 'type': 'Layout',
                'path': 'coui://gui/gameface/mods/tanksession/Analytics.html',
                'parameters': {'entrance': 'Analytics', 'extension': '', 'impl': 'gameface'},
            }]).encode('utf-8'),
        }

    def tearDown(self):
        self.folder.cleanup()

    def make_archive(self, compression=zipfile.ZIP_STORED, meta=None, omit=None,
                     extra=None, bytecode=None):
        with zipfile.ZipFile(self.archive, 'w', compression) as output:
            output.writestr('meta.xml', self.meta if meta is None else meta)
            for name in sorted(REQUIRED_MODULES):
                if name != omit:
                    output.writestr(name, self.header_fixture if bytecode is None else bytecode)
            for name in sorted(REQUIRED_ASSETS):
                if name != omit:
                    output.writestr(name, self.assets[name])
            if extra:
                # Preserve the deliberately unsafe raw name on every OS.
                # Passing a string to writestr/ZipInfo normalizes Windows '\\'.
                member = zipfile.ZipInfo()
                member.filename = member.orig_filename = extra
                member.compress_type = compression
                output.writestr(member, b'code')

    def test_valid_manifest_and_headers_have_explicit_structural_scope(self):
        self.make_archive()
        info = verify_mtmod(self.archive)
        self.assertEqual(info['version'], self.version)
        self.assertEqual(info['compiled_modules'], len(REQUIRED_MODULES))
        self.assertEqual(info['validation'], 'structure-and-headers-only')
        self.assertNotIn('code_objects_checked', info)

    def test_reject_compressed_package(self):
        self.make_archive(zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, 'non-compressed'):
            verify_mtmod(self.archive)

    def test_reject_wrong_xml_root(self):
        self.make_archive(meta=self.meta.replace(b'<root>', b'<mod>').replace(b'</root>', b'</mod>'))
        with self.assertRaisesRegex(ValueError, 'root element'):
            verify_mtmod(self.archive)

    def test_reject_missing_entry(self):
        self.make_archive(omit=ENTRY)
        with self.assertRaisesRegex(ValueError, 'entrypoint'):
            verify_mtmod(self.archive)

    def test_reject_missing_dependency_even_with_many_other_modules(self):
        self.make_archive(omit='res/scripts/client/gui/mods/tanksession_analytics/core.pyc')
        with self.assertRaisesRegex(ValueError, 'Missing required modules'):
            verify_mtmod(self.archive)

    def test_reject_missing_ui_resource(self):
        self.make_archive(omit=UI_ROOT + 'app.js')
        with self.assertRaisesRegex(ValueError, 'Missing required UI assets'):
            verify_mtmod(self.archive)

    def test_reject_resource_map_pointing_to_a_different_view(self):
        self.assets[RESOURCE_MAP] = self.assets[RESOURCE_MAP].replace(b'Analytics.html', b'Other.html')
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'resource map'):
            verify_mtmod(self.archive)

    def test_reject_html_without_its_bundle_reference(self):
        self.assets[UI_ROOT + 'Analytics.html'] = b'<html><link href="app.css"></html>'
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'app.js'):
            verify_mtmod(self.archive)

    def test_reject_missing_dependency_license_notice(self):
        self.assets[UI_ROOT + 'THIRD_PARTY_LICENSES.txt'] = b'no notices'
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'license'):
            verify_mtmod(self.archive)

    def test_reject_python_source(self):
        self.make_archive(extra='res/scripts/client/gui/mods/mod_test.py')
        with self.assertRaisesRegex(ValueError, 'Source'):
            verify_mtmod(self.archive)

    def test_reject_unexpected_files(self):
        self.make_archive(extra='res/scripts/client/gui/mods/unrelated.pyc')
        with self.assertRaisesRegex(ValueError, 'Unexpected package files'):
            verify_mtmod(self.archive)

    def test_reject_path_traversal(self):
        for path in ('../private.txt', '/absolute.txt', 'a/./file', 'a\\file'):
            self.make_archive(extra=path)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                verify_mtmod(self.archive)

    def test_reject_raw_name_even_when_zipfile_normalizes_it_on_windows(self):
        raw_name = 'a\\file'
        self.make_archive(extra=raw_name)
        # Real ZIP bytes, with only the platform separator varied. This covers
        # the same read-time normalization on Linux and Windows CI runners.
        with mock.patch.object(zipfile.os, 'sep', '\\'):
            with zipfile.ZipFile(self.archive) as archive:
                member = next(item for item in archive.infolist()
                              if item.orig_filename == raw_name)
                self.assertEqual(member.filename, 'a/file')
                self.assertNotEqual(member.orig_filename, member.filename)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                verify_mtmod(self.archive)

    def test_reject_python3_bytecode_header(self):
        self.make_archive(bytecode=importlib.util.MAGIC_NUMBER + self.header_fixture[4:])
        with self.assertRaisesRegex(ValueError, 'CPython 2.7'):
            verify_mtmod(self.archive)

    def test_reject_empty_bytecode(self):
        self.make_archive(bytecode=PY27_MAGIC + b'\x00' * 4)
        with self.assertRaisesRegex(ValueError, 'empty'):
            verify_mtmod(self.archive)

    def test_reject_non_code_marshal_marker(self):
        self.make_archive(bytecode=PY27_MAGIC + b'\x00' * 4 + b'N')
        with self.assertRaisesRegex(ValueError, 'code-object'):
            verify_mtmod(self.archive)

    def test_reject_duplicate_members(self):
        self.make_archive()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'a') as output:
                output.writestr(ENTRY, self.header_fixture)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            verify_mtmod(self.archive)

    def test_detect_wrong_id_and_version(self):
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'version'):
            verify_mtmod(self.archive, expected_version='0.0.0')
        with self.assertRaisesRegex(ValueError, 'mod ID'):
            verify_mtmod(self.archive, expected_id='different.mod')

    def test_reject_metadata_that_could_escape_output_folder(self):
        self.make_archive(meta=self.meta.replace(self.version.encode(), b'../../escape'))
        with self.assertRaisesRegex(ValueError, 'Unsafe mod ID or version'):
            verify_mtmod(self.archive)

    def test_detect_member_corruption_by_crc(self):
        self.make_archive()
        with zipfile.ZipFile(self.archive) as source:
            member = source.getinfo(ENTRY)
            offset = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
        with open(self.archive, 'r+b') as source:
            source.seek(offset + 10)
            source.write(b'X')
        with self.assertRaises(zipfile.BadZipFile):
            verify_mtmod(self.archive)

    def test_reject_python3_as_build_interpreter(self):
        with self.assertRaisesRegex(ValueError, 'real CPython 2.7'):
            build(sys.executable)


@unittest.skipUnless(os.environ.get('PYTHON2'), 'Real CPython 2.7 is checked in the dedicated build job')
class RealPython2BuildTests(unittest.TestCase):
    def test_actual_build_is_reproducible_and_has_checksum(self):
        with tempfile.TemporaryDirectory() as target_dir:
            with mock.patch('build.OUT', target_dir):
                path, info = build(os.environ['PYTHON2'])
                with open(path, 'rb') as archive:
                    first = archive.read()
                self.assertTrue(info['code_objects_checked'])
                self.assertEqual(info['build_interpreter']['implementation'], 'CPython')
                self.assertEqual(info['build_interpreter']['version'][:2], [2, 7])
                self.assertEqual(info['sha256'], hashlib.sha256(first).hexdigest())
                with open(path + '.sha256', encoding='ascii') as checksum:
                    self.assertEqual(checksum.read(), '%s  %s\n' %
                                     (info['sha256'], os.path.basename(path)))
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.namelist(), sorted(REQUIRED_FILES))
                    self.assertTrue(all(item.date_time == ZIP_DATE for item in archive.infolist()))
                second_path, second_info = build(os.environ['PYTHON2'])
                with open(second_path, 'rb') as archive:
                    self.assertEqual(first, archive.read())
                self.assertEqual(info['sha256'], second_info['sha256'])

    def test_python2_runtime_smoke_on_trusted_checkout(self):
        helper = os.path.join(ROOT, 'tools', 'verify_python2.py')
        subprocess.run([os.environ['PYTHON2'], '-S', '-B', helper],
                       check=True, timeout=60)


if __name__ == '__main__':
    unittest.main()
