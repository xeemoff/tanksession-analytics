import errno
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import preview_ui as preview_module
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

    def enable_writes(self):
        self.stop_server()
        self.server = create_ui_server(str(self.journal), '101', port=0,
                                       assets_dir=str(self.assets), allow_write=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def begin_post(self, headers, path='/api/command'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest('POST', path, skip_host=any(name.lower() == 'host' for name, _ in headers))
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders()
        return connection

    def assert_no_mutations(self, original):
        self.assertEqual(self.journal.read_bytes(), original)
        self.assertFalse((Path(self.folder.name) / 'profiles').exists())
        self.assertFalse((Path(self.folder.name) / 'exports').exists())

    def test_initialization_reads_preferences_but_real_preview_is_read_only_by_default(self):
        request = dict(protocol=1, request_id='init', vehicle='', window=10,
                       page=0, action='initialize')
        status, body = self.post(request)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['workspace']['can_edit'])
        request['action'] = 'export_csv'
        self.assertEqual(self.post(request)[0], 403)
        self.assertFalse((Path(self.folder.name) / 'exports').exists())

    def test_readonly_preview_projects_rollback_without_writes_and_opt_in_recovers(self):
        base = Path(self.folder.name)
        workspace = preview_module.Workspace(str(base))
        path = Path(workspace._path('101'))
        path.parent.mkdir()
        profile = {'version': 2, 'preferences': {'vehicle': '', 'window': 30, 'tab': 'settings',
                   'density': 'compact', 'contrast': 'high'}, 'goals': []}
        raw = (json.dumps(profile) + '\n').encode('utf-8')
        rollback = path.with_name(path.name + '.rollback')
        rollback.write_bytes(raw)
        path.with_name(path.name + '.bak.rollback').write_bytes(raw)
        (path.parent / '.tsa-interrupted.tmp').write_bytes(b'uncommitted temporary bytes')

        def directory_contents():
            return {str(entry.relative_to(base)): None if entry.is_dir() else entry.read_bytes()
                    for entry in base.rglob('*')}

        before = directory_contents()
        initialize = dict(protocol=1, request_id='readonly-init', vehicle='', window=10,
                          action='initialize')
        status, body = self.post(initialize)
        self.assertEqual(status, 200)
        initialized = json.loads(body)
        self.assertEqual(initialized['status'], 'ready')
        self.assertEqual(initialized['summary']['battles'], 2)
        self.assertEqual(initialized['workspace']['preferences']['contrast'], 'high')
        self.assertFalse(initialized['workspace']['can_edit'])
        self.assertEqual(directory_contents(), before)

        status, _, body = self.get('/api/snapshot?request_id=readonly-get')
        self.assertEqual(status, 200)
        refreshed = json.loads(body)
        self.assertEqual(refreshed['status'], 'ready')
        self.assertEqual(refreshed['summary']['battles'], 2)
        self.assertEqual(refreshed['workspace']['preferences']['contrast'], 'high')
        self.assertFalse(refreshed['workspace']['can_edit'])
        self.assertEqual(directory_contents(), before)

        self.enable_writes()
        status, _, body = self.get('/api/snapshot?request_id=writable-get')
        self.assertEqual(status, 200)
        recovered = json.loads(body)
        self.assertTrue(recovered['workspace']['can_edit'])
        self.assertEqual(recovered['workspace']['preferences']['contrast'], 'high')
        self.assertEqual(recovered['summary']['battles'], 2)
        expected = dict(before)
        expected[str(path.relative_to(base))] = expected.pop(str(rollback.relative_to(base)))
        self.assertEqual(directory_contents(), expected)

    def test_cross_origin_or_form_commands_are_rejected(self):
        request = dict(protocol=1, request_id='init', vehicle='', window=10, action='initialize')
        for headers in ({'Content-Type': 'text/plain'},
                        {'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-TankSession-Request': '1',
                         'Origin': 'https://unrelated.example'},
                        {'Content-Type': 'application/json', 'X-TankSession-Request': '1',
                         'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.post(request, headers)[0], 403)

    def test_rejected_split_post_bodies_are_consumed_before_response_and_never_mutate(self):
        self.enable_writes()
        original = self.journal.read_bytes()
        request = dict(protocol=1, request_id='reject-save', vehicle='', window=10,
                       action='save_preferences', preferences=dict(vehicle='', window=10,
                       tab='settings', density='compact', contrast='high'))
        raw = json.dumps(request).encode('utf-8')
        raw += b' ' * (preview_module.MAX_COMMAND_BYTES - len(raw))
        started = threading.Event()
        handler = self.server.RequestHandlerClass
        original_post = handler.do_POST

        def observed_post(instance):
            started.set()
            original_post(instance)

        cases = (({'Content-Type': 'text/plain'}, '/api/command', 403, 'command_rejected'),
                 ({'X-TankSession-Request': None}, '/api/command', 403, 'command_rejected'),
                 ({'Host': 'unrelated.example'}, '/api/command', 403, 'origin_rejected'),
                 ({'Origin': 'https://unrelated.example'}, '/api/command', 403, 'origin_rejected'),
                 ({'Sec-Fetch-Site': 'cross-site'}, '/api/command', 403, 'origin_rejected'),
                 ({}, '/not-a-command', 404, 'not_found'))
        with mock.patch.object(handler, 'do_POST', observed_post):
            for overrides, path, expected_status, expected_error in cases:
                with self.subTest(headers=overrides, path=path):
                    headers = {'Content-Type': 'application/json', 'X-TankSession-Request': '1',
                               'Content-Length': str(len(raw))}
                    headers.update(overrides)
                    started.clear()
                    connection = self.begin_post([(key, value) for key, value in headers.items()
                                                  if value is not None], path)
                    self.assertTrue(started.wait(5), 'Server did not begin handling the POST')
                    # The body has deliberately not been sent. Closing now
                    # races its later bytes and loses the 403 on Windows.
                    connection.sock.settimeout(0.15)
                    with self.assertRaises(socket.timeout):
                        connection.sock.recv(1)
                    connection.sock.settimeout(5)
                    connection.send(raw[:1])
                    connection.send(raw[1:])
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected_status)
                    self.assertEqual(response.getheader('Connection'), 'close')
                    self.assertEqual(json.loads(response.read()), {'error': expected_error})
                    connection.close()
                    self.assert_no_mutations(original)
        # The same command is writable when it passes every boundary check.
        status, body = self.post(request)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['workspace']['operation']['code'], 'preferences_saved')

    def test_ambiguous_unsupported_or_oversized_post_framing_is_rejected_without_reading_body(self):
        self.enable_writes()
        original = self.journal.read_bytes()
        cases = (([], 400),
                 ([('Content-Length', '0')], 400),
                 ([('Content-Length', '-1')], 400),
                 ([('Content-Length', '+1')], 400),
                 ([('Content-Length', '16385')], 400),
                 ([('Content-Length', '100000000000000000000')], 400),
                 ([('Content-Length', '10'), ('Content-Length', '10')], 400),
                 ([('Content-Length', '10'), ('Content-Length', '20')], 400),
                 ([('Content-Length', '10,10')], 400),
                 ([('Transfer-Encoding', 'chunked')], 403),
                 ([('Content-Length', '10'), ('Transfer-Encoding', 'chunked')], 403))
        for framing, expected_status in cases:
            with self.subTest(framing=framing):
                connection = self.begin_post([('Content-Type', 'application/json'),
                                               ('X-TankSession-Request', '1')] + framing)
                # No body is sent: unknown or unbounded framing must not make
                # the single-threaded preview wait for an advertised payload.
                response = connection.getresponse()
                self.assertEqual(response.status, expected_status)
                self.assertEqual(response.getheader('Connection'), 'close')
                self.assertIn(json.loads(response.read())['error'], ('invalid_request', 'command_rejected'))
                connection.close()
                self.assert_no_mutations(original)

    def test_truncated_post_and_body_timeout_do_not_mutate_or_stall_preview(self):
        self.enable_writes()
        original = self.journal.read_bytes()
        headers = [('Content-Type', 'application/json'), ('X-TankSession-Request', '1'),
                   ('Content-Length', '100')]
        connection = self.begin_post(headers)
        connection.send(b'{')
        connection.sock.shutdown(socket.SHUT_WR)
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read()), {'error': 'invalid_request'})
        connection.close()
        with mock.patch.object(preview_module, 'REQUEST_TIMEOUT_SECONDS', 0.3):
            connection = self.begin_post(headers)
            connection.send(b'{')
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(response.read()), {'error': 'invalid_request'})
            connection.close()
        self.assert_no_mutations(original)
        self.assertEqual(self.get('/api/snapshot')[0], 200)

    def test_pages_are_bounded_and_query_cannot_mutate(self):
        status, _, body = self.get('/api/snapshot?request_id=page&window=10&page=100')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['pagination']['page'], 0)
        for query in ('page=-1', 'page=1.5', 'page=true', 'page=1&page=2',
                      'action=export_csv'):
            self.assertEqual(self.get('/api/snapshot?' + query)[0], 400)

    def test_history_search_and_sort_use_the_same_scoped_service_as_native_ui(self):
        status, _, body = self.get('/api/snapshot?request_id=history&history_query=T-34&history_sort=damage_desc&page=9')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['summary']['battles'], 2)
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['pagination']['page'], 0)
        self.assertEqual(data['selection']['history_query'], 'T-34')
        self.assertEqual(data['selection']['history_sort'], 'damage_desc')
        self.assertEqual([row['vehicle'] for row in data['history']], ['T-34'])
        for query in ('history_sort=unsupported', 'history_query=x&history_query=y',
                      'history_query=' + 'x' * 65, 'history_query=x%0Ay'):
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
            environment = dict(os.environ, PYTHONPATH='', PYTHONIOENCODING='cp1252:strict',
                               PYTHONUTF8='0')
            result = subprocess.run([sys.executable, 'tools/preview_ui.py', '--help'], cwd=extracted,
                                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--allow-write', result.stdout)
            self.assertIn('Просмотр нового интерфейса TankSession в браузере', result.stdout)
            self.assertEqual(result.stderr, '')

    def test_cli_errors_preserve_unicode_paths_with_non_unicode_pipe_encoding(self):
        environment = dict(os.environ, PYTHONIOENCODING='cp1252:strict', PYTHONUTF8='0')
        with tempfile.TemporaryDirectory() as folder:
            missing_goals = str(Path(folder) / 'цели игрока 日本語.json')
            cases = (
                (['--data', 'unused.jsonl'], 2,
                 '--data требует --account: история аккаунтов не объединяется'),
                (['--demo', '--no-browser', '--goals', missing_goals], 1, repr(missing_goals)),
            )
            for arguments, expected_code, expected_message in cases:
                with self.subTest(arguments=arguments):
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/preview_ui.py')]
                                            + arguments, env=environment,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            encoding='utf-8', timeout=15)
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertIn(expected_message, result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertNotIn('UnicodeEncodeError', result.stderr)

    def test_startup_messages_use_utf8_with_non_unicode_pipe_encoding(self):
        environment = dict(os.environ, PYTHONIOENCODING='cp1252:strict', PYTHONUTF8='0')
        # Avoid opening a browser or holding a listening socket: the CLI still
        # executes its real argument parsing and all normal startup messages.
        script = """
import sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import preview_ui
preview_ui.create_ui_server = lambda *args, **kwargs: SimpleNamespace(
    server_port=8770, serve_forever=lambda: None, server_close=lambda: None)
sys.exit(preview_ui.main(['--demo', '--no-browser']))
"""
        result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'tools')],
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Интерфейс: http://127.0.0.1:8770/?demo=1', result.stdout)
        self.assertIn('Для остановки нажмите Ctrl+C.', result.stdout)
        self.assertEqual(result.stderr, '')

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
