import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build import verify_mtmod, ENTRY


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.archive = os.path.join(self.folder.name, 'sample.mtmod')
        self.meta = b'<root><id>test.mod</id><version>0.4.0-rc1</version><name>Test</name></root>'

    def tearDown(self):
        self.folder.cleanup()

    def make_archive(self, compression=zipfile.ZIP_STORED, meta=None, entry=True,
                     extra=None):
        with zipfile.ZipFile(self.archive, 'w', compression) as output:
            output.writestr('meta.xml', self.meta if meta is None else meta)
            if entry:
                output.writestr(ENTRY, b'\x03\xf3\r\n' + b'abcdefgh')
            output.writestr('res/scripts/client/gui/mods/tanksession_analytics/__init__.pyc',
                            b'\x03\xf3\r\n' + b'abcdefgh')
            if extra:
                output.writestr(extra, b'code')

    def test_valid_stored_mtmod(self):
        self.make_archive()
        self.assertEqual(verify_mtmod(self.archive)['version'], '0.4.0-rc1')
        self.assertEqual(verify_mtmod(self.archive)['compiled_modules'], 2)

    def test_reject_compressed_package(self):
        self.make_archive(zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, 'non-compressed'):
            verify_mtmod(self.archive)

    def test_reject_wrong_xml_root(self):
        self.make_archive(meta=self.meta.replace(b'<root>', b'<mod>').replace(b'</root>', b'</mod>'))
        with self.assertRaisesRegex(ValueError, 'root element'):
            verify_mtmod(self.archive)

    def test_reject_missing_entry(self):
        self.make_archive(entry=False)
        with self.assertRaisesRegex(ValueError, 'entrypoint'):
            verify_mtmod(self.archive)

    def test_reject_python_source(self):
        self.make_archive(extra='res/scripts/client/gui/mods/mod_test.py')
        with self.assertRaisesRegex(ValueError, 'Source'):
            verify_mtmod(self.archive)

    def test_reject_path_traversal(self):
        self.make_archive(extra='../private.txt')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            verify_mtmod(self.archive)

    def test_detect_wrong_expected_version(self):
        self.make_archive()
        with self.assertRaisesRegex(ValueError, 'version'):
            verify_mtmod(self.archive, expected_version='0.3.0')


if __name__ == '__main__':
    unittest.main()
