#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serve the React view and its Python snapshot API on loopback only.

This preview does not load Gameface or modify the game. Demonstration data is
selected explicitly; a real journal requires one explicit account identifier.
"""
import argparse
import json
import os
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from dashboard import ROOT, CachedJournal, load_goals
from tanksession_analytics.goals import validate_goals
from tanksession_analytics.presentation import build_snapshot, validate_request
from tanksession_analytics.recorder import _verified_account
from tanksession_analytics.workspace import Workspace, MUTATIONS
from tanksession_analytics.gameface import decode_request

ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/app.css': ('app.css', 'text/css; charset=utf-8'),
    '/THIRD_PARTY_LICENSES.txt': ('THIRD_PARTY_LICENSES.txt', 'text/plain; charset=utf-8'),
}
MAX_COMMAND_BYTES = 16384
REQUEST_TIMEOUT_SECONDS = 10


def create_ui_server(data_path, account_id, goals=None, demo=False,
                     port=8770, assets_dir=None, host='127.0.0.1', allow_write=False):
    """Return an unstarted loopback server; real writes require explicit opt-in."""
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('Only loopback is supported')
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError('Port must be 0..65535')
    account = _verified_account(account_id)
    if account is None:
        raise ValueError('Укажите один аккаунт через --account.')
    assets_dir = os.path.abspath(assets_dir or os.path.join(ROOT, 'ui', 'dist'))
    assets = {}
    for filename, _ in set(ASSETS.values()):
        path = os.path.join(assets_dir, filename)
        if not os.path.isfile(path) or os.path.islink(path):
            raise ValueError('Интерфейс не собран. Выполните npm ci и npm run build в папке ui.')
        with open(path, 'rb') as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('UI asset exceeds the size limit')
        assets[filename] = data
    journal = CachedJournal(os.path.abspath(data_path))
    goals = validate_goals([] if goals is None else goals)
    temporary = tempfile.TemporaryDirectory(prefix='tanksession-demo-') if demo else None
    writable = demo or allow_write
    workspace = Workspace(temporary.name if temporary else os.path.dirname(os.path.abspath(data_path)),
                          memory=demo, read_only=not writable)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)

        def log_message(self, format, *args):
            # Do not log URLs, account identifiers or local filesystem paths.
            pass

        def respond(self, status, data, content_type):
            self.close_connection = True
            self.send_response(status)
            self.send_header('Connection', 'close')
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; script-src 'self'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                             "connect-src 'self'; font-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def json_response(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False,
                              separators=(',', ':')).encode('utf-8')
            self.respond(status, data, 'application/json; charset=utf-8')

        def valid_origin(self):
            hosts = ('127.0.0.1:%d' % self.server.server_port,
                     'localhost:%d' % self.server.server_port)
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if (host not in hosts or
                    (origin is not None and origin != 'http://' + host) or
                    self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.json_response(403, {'error': 'origin_rejected'})
                return False
            return True

        def snapshot_response(self, request):
            records = journal.records()
            if journal.state in ('missing', 'unreadable'):
                self.json_response(503, {'error': 'journal_unavailable'})
                return
            try:
                snapshot = workspace.snapshot(records, account, request=request,
                                               legacy_goals=goals, diagnostics=journal.diagnostics,
                                               source='demo' if demo else 'game')
                snapshot['workspace']['can_edit'] = writable and snapshot['workspace']['can_edit']
            except (ValueError, TypeError, OverflowError, UnicodeError):
                self.json_response(503, {'error': 'snapshot_unavailable'})
                return
            self.json_response(200, snapshot)

        def command_body(self):
            lengths = self.headers.get_all('Content-Length', [])
            if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                    or len(lengths[0]) > 5):
                raise ValueError('Ambiguous or missing command length')
            length = int(lengths[0])
            if not 1 <= length <= MAX_COMMAND_BYTES:
                raise ValueError('Oversized command')
            chunks = []
            remaining = length
            deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
            try:
                while remaining:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        raise TimeoutError('Command body timed out')
                    self.connection.settimeout(timeout)
                    # read1 performs at most one socket read. A trickle of
                    # bytes cannot restart the full timeout for every read.
                    chunk = self.rfile.read1(remaining)
                    if not chunk:
                        raise ValueError('Incomplete command')
                    chunks.append(chunk)
                    remaining -= len(chunk)
            finally:
                self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)
            return b''.join(chunks)

        def do_POST(self):
            # HTTP/1.0 closes this connection after its response. Consume a
            # small, unambiguously framed body before any early rejection;
            # closing with body bytes in flight can reset the TCP connection
            # and erase the 403 response on Windows (RFC 9112 section 9.6).
            # Unknown/oversized framing is closed without unbounded draining.
            if self.headers.get('Transfer-Encoding') is not None:
                self.json_response(403, {'error': 'command_rejected'})
                return
            try:
                raw = self.command_body()
            except (ValueError, TypeError, UnicodeError, OSError):
                self.json_response(400, {'error': 'invalid_request'})
                return
            if not self.valid_origin():
                return
            if self.path != '/api/command':
                self.json_response(404, {'error': 'not_found'})
                return
            # An unrelated webpage cannot send this non-simple request: no
            # CORS headers or OPTIONS endpoint are provided by this server.
            if (self.headers.get('X-TankSession-Request') != '1' or
                    self.headers.get_content_type() != 'application/json'):
                self.json_response(403, {'error': 'command_rejected'})
                return
            try:
                request = decode_request({'payload': raw})
                if request.get('action') in MUTATIONS and not writable:
                    self.json_response(403, {'error': 'read_only'})
                    return
            except (ValueError, TypeError, UnicodeError, OSError):
                self.json_response(400, {'error': 'invalid_request'})
                return
            self.snapshot_response(request)

        def do_GET(self):
            if not self.valid_origin():
                return
            if len(self.path) > 4096:
                self.json_response(414, {'error': 'request_too_large'})
                return
            try:
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc or parsed.fragment:
                    raise ValueError('Absolute URLs are not accepted')
                params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8,
                                  encoding='utf-8', errors='strict')
            except (ValueError, UnicodeError):
                self.json_response(400, {'error': 'invalid_request'})
                return
            if parsed.path in ASSETS:
                filename, content_type = ASSETS[parsed.path]
                self.respond(200, assets[filename], content_type)
                return
            if parsed.path != '/api/snapshot':
                self.json_response(404, {'error': 'not_found'})
                return
            try:
                if set(params).difference(('window', 'vehicle', 'request_id', 'page',
                                           'history_query', 'history_sort')):
                    raise ValueError('Unsupported query field')
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError('Duplicate query field')
                window = params.get('window', ['10'])[0]
                if window not in ('10', '30', '100'):
                    raise ValueError('Unsupported window')
                request = {
                    'protocol': 1,
                    'request_id': params.get('request_id', ['preview'])[0],
                    'vehicle': params.get('vehicle', [''])[0],
                    'window': int(window),
                }
                if 'page' in params:
                    page = params['page'][0]
                    if not page.isascii() or not page.isdigit() or len(page) > 7:
                        raise ValueError('Invalid page')
                    request['page'] = int(page)
                for name in ('history_query', 'history_sort'):
                    if name in params:
                        request[name] = params[name][0]
                request = validate_request(request)
            except ValueError:
                self.json_response(400, {'error': 'invalid_request'})
                return
            self.snapshot_response(request)

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.journal = journal
    close = server.server_close

    def close_server():
        close()
        if temporary:
            temporary.cleanup()

    server.server_close = close_server
    return server


def _configure_cli_output():
    """Keep Russian messages and Unicode paths intact in redirected output.

    Windows pipes may otherwise use an ANSI code page which cannot encode the
    help text. Configure the application, not its launcher's environment, and
    leave in-memory text streams used by embedders alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(encoding='utf-8', errors='backslashreplace')


def main(argv=None):
    _configure_cli_output()
    parser = argparse.ArgumentParser(description='Просмотр нового интерфейса TankSession в браузере')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true', help='Вымышленные демонстрационные бои')
    source.add_argument('--data', help='Существующий локальный журнал JSONL')
    parser.add_argument('--account', help='Один ID аккаунта из своего журнала (для --data)')
    parser.add_argument('--goals', default='', help='Локальный JSON с целями')
    parser.add_argument('--port', type=int, default=8770, help='Локальный порт, 0 — свободный')
    parser.add_argument('--no-browser', action='store_true', help='Только вывести адрес')
    parser.add_argument('--allow-write', action='store_true',
                        help='Разрешить локальное сохранение настроек, целей и CSV для --data')
    args = parser.parse_args(argv)
    if args.demo and args.account:
        parser.error('--account используется только вместе с --data')
    if args.data and not args.account:
        parser.error('--data требует --account: история аккаунтов не объединяется')
    path = (os.path.join(ROOT, 'sample_data', 'battles.jsonl') if args.demo else
            os.path.abspath(os.path.expanduser(args.data)))
    goals_path = args.goals or (os.path.join(ROOT, 'sample_data', 'goals.json') if args.demo else '')
    try:
        server = create_ui_server(path, 'demo' if args.demo else args.account,
                                  load_goals(goals_path), demo=args.demo, port=args.port,
                                  allow_write=args.allow_write)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        print('Запуск не выполнен: %s' % error, file=sys.stderr)
        return 1
    mode = 'demo' if args.demo else 'local'
    url = 'http://127.0.0.1:%d/?%s=1' % (server.server_port, mode)
    print('Интерфейс: %s' % url, flush=True)
    print('Это браузерный просмотр. Запуск Gameface в игре проверяется отдельно.', flush=True)
    print('Для остановки нажмите Ctrl+C.', flush=True)
    try:
        if not args.no_browser:
            try:
                webbrowser.open(url, new=2)
            except (OSError, webbrowser.Error):
                print('Откройте адрес вручную.', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
