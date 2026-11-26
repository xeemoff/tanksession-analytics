import errno
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from preview_ui import create_ui_server, main


class UiPreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        base = Path(self.folder.name)
        self.journal = base / 'history.jsonl'
        rows = [dict(arena_id=str(i), account_id=account, timestamp=1700000000 + i,
                     vehicle=vehicle, outcome='win', damage=damage, xp=500)
                for i, account, vehicle, damage in (
                    (1, '101', 'IS-7', 1200), (2, '101', 'T-34', 600),
                    (3, '202', 'Other private tank', 9999))]
        self.journal.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        self.assets = base / 'assets'
        self.assets.mkdir()
        for filename, content in (
                ('index.html', '<html><script src="app.js"></script></html>'),
                ('app.js', '/* preview test fixture */'),
                ('app.css', 'body { display: flex; }'),
                ('THIRD_PARTY_LICENSES.txt', 'MIT License')):
            (self.assets / filename).write_text(content, encoding='utf-8')
        try:
            self.server = create_ui_server(str(self.journal), '101', port=0,
                                           assets_dir=str(self.assets))
        except OSError as error:
            if error.errno in (errno.EPERM, errno.EACCES):
                self.skipTest('Loopback sockets unavailable in this environment; exercised in CI')
            raise
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post(self, data, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', '/api/command', body=json.dumps(data), headers=headers or {
                'Content-Type': 'application/json', 'X-TankSession-Request': '1'})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_initialization_reads_preferences_but_real_preview_is_read_only_by_default(self):
        request = dict(protocol=1, request_id='init', vehicle='', window=10,
                       page=0, action='initialize')
        status, body = self.post(request)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['workspace']['can_edit'])
        request['action'] = 'export_csv'
        self.assertEqual(self.post(request)[0], 403)
        self.assertFalse((Path(self.folder.name) / 'exports').exists())

    def test_cross_origin_or_form_commands_are_rejected(self):
        request = dict(protocol=1, request_id='init', vehicle='', window=10, action='initialize')
        for headers in ({'Content-Type': 'text/plain'},
                        {'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-TankSession-Request': '1',
                         'Origin': 'https://unrelated.example'},
                        {'Content-Type': 'application/json', 'X-TankSession-Request': '1',
                         'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.post(request, headers)[0], 403)

    def test_pages_are_bounded_and_query_cannot_mutate(self):
        status, _, body = self.get('/api/snapshot?request_id=page&window=10&page=100')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['pagination']['page'], 0)
        for query in ('page=-1', 'page=1.5', 'page=true', 'page=1&page=2',
                      'action=export_csv'):
            self.assertEqual(self.get('/api/snapshot?' + query)[0], 400)

    def test_snapshot_is_pinned_to_one_account(self):
        status, headers, body = self.get('/api/snapshot?request_id=test-1&window=10')
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot['summary']['battles'], 2)
        self.assertEqual(snapshot['summary']['avg_damage'], 900)
        self.assertEqual(snapshot['request_id'], 'test-1')
        self.assertNotIn('Other private tank', body.decode())
        self.assertNotIn('account_id', body.decode())
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_vehicle_filter_and_window_are_processed_by_python(self):
        status, _, body = self.get('/api/snapshot?vehicle=IS-7&window=30&request_id=filter')
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot['summary']['battles'], 1)
        self.assertEqual(snapshot['summary']['avg_damage'], 1200)
        self.assertFalse(snapshot['comparison']['enough_previous'])
        self.assertIsNone(snapshot['comparison']['damage_delta'])

    def test_account_switch_and_ambiguous_queries_are_rejected(self):
        for query in ('account=202', 'window=11', 'window=10&window=30',
                      'vehicle=A&vehicle=B', 'request_id=%3Cscript%3E', 'window=true'):
            self.assertEqual(self.get('/api/snapshot?' + query)[0], 400, query)

    def test_host_origin_and_cross_site_requests_are_rejected(self):
        for headers in ({'Host': 'unrelated.example'},
                        {'Origin': 'https://unrelated.example'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.get('/api/snapshot', headers)[0], 403)

    def test_file_paths_and_unlisted_assets_are_not_served(self):
        for path in ('/../history.jsonl', '/%2e%2e/history.jsonl', '/app.js.map',
                     '/package.json', '/history.jsonl'):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_static_resources_have_correct_types_and_csp(self):
        status, headers, _ = self.get('/?demo=1')
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        status, headers, _ = self.get('/app.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', headers['Content-Type'])

    def test_lost_journal_does_not_serve_cached_success(self):
        self.assertEqual(self.get('/api/snapshot')[0], 200)
        self.journal.unlink()
        status, _, body = self.get('/api/snapshot')
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['error'], 'journal_unavailable')
        self.assertNotIn('summary', body.decode())


class UiPreviewConfigurationTests(unittest.TestCase):
    def test_distributed_preview_starts_without_unbundled_source_modules(self):
        import package_preview
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in ('LICENSE', 'demo_hangar.cmd', 'tools/preview_ui.py',
                             'tools/dashboard.py', 'sample_data/battles.jsonl', 'sample_data/goals.json'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            shutil.copytree(ROOT / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            assets = root / 'ui/dist'
            assets.mkdir(parents=True)
            for name in ('index.html', 'app.js', 'app.css', 'THIRD_PARTY_LICENSES.txt'):
                (assets / name).write_text('Preview fixture', encoding='utf-8')
            previous = package_preview.ROOT
            package_preview.ROOT = root
            try:
                archive_path = package_preview.build_preview()
            finally:
                package_preview.ROOT = previous
            extracted = root / 'extracted'
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)
            environment = dict(os.environ, PYTHONPATH='')
            result = subprocess.run([sys.executable, 'tools/preview_ui.py', '--help'], cwd=extracted,
                                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--allow-write', result.stdout)

    def test_external_interface_is_rejected_before_any_bind(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            create_ui_server('unused.jsonl', '101', host='0.0.0.0')

    def test_unknown_account_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'account'):
            create_ui_server('unused.jsonl', None)

    def test_local_journal_requires_an_explicit_account_argument(self):
        with self.assertRaises(SystemExit) as caught:
            main(['--data', 'unused.jsonl', '--no-browser'])
        self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
