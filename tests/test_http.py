"""Real loopback requests against the same server used by the CLI/launcher."""
import csv
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from dashboard import CachedJournal, create_server, render


def record(arena, account='A', **fields):
    row = {'arena_id': str(arena), 'account_id': account, 'timestamp': 1700000000 + arena,
           'vehicle': 'IS-7', 'outcome': 'win', 'damage': 2500, 'xp': 500}
    row.update(fields)
    return row


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'battles.jsonl'
        self.server = create_server(str(self.path), port=0, demo=False)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def get(self, path='/', host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            headers = {'Host': host} if host else {}
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def write(self, *items):
        self.path.write_text(''.join(json.dumps(row) + '\n' for row in items), encoding='utf-8')

    def test_missing_journal_recovers_when_first_battle_arrives(self):
        status, headers, data = self.get()
        self.assertEqual(status, 200)
        self.assertIn('Журнал ещё не найден', data.decode())
        self.assertEqual(self.get('/export.csv')[0], 503)
        self.write(record(1))
        status, headers, data = self.get()
        self.assertEqual(status, 200)
        self.assertIn('Журнал прочитан', data.decode())
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])

    def test_schema_errors_are_counted_and_do_not_break_http(self):
        self.write(record(1), record(2, outcome=[]), dict(record(3), schema=999))
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write('{truncated\n')
        status, _, data = self.get()
        self.assertEqual(status, 200)
        self.assertIn('отклонённых строк: 3', data.decode())
        self.assertEqual(len(self.server.journal.records()), 1)

    def test_oversized_integer_cannot_crash_http_statistics(self):
        self.write(record(1), record(2, damage=10 ** 400))
        status, _, data = self.get()
        self.assertEqual(status, 200)
        self.assertIn('отклонённых строк: 1', data.decode())
        self.assertEqual(len(self.server.journal.records()), 1)

    def test_csv_filters_account_and_preserves_formula_protection(self):
        self.write(record(1, 'A'), record(2, 'B', vehicle='=SUM(1,2)'))
        status, headers, data = self.get('/export.csv?account=B')
        self.assertEqual(status, 200)
        self.assertIn('attachment;', headers['Content-Disposition'])
        rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['account_id'], 'B')
        self.assertEqual(rows[0]['vehicle'], "'=SUM(1,2)")

    def test_host_and_unknown_route_are_rejected(self):
        self.assertEqual(self.get(host='attacker.example')[0], 400)
        self.assertEqual(self.get('/not-a-route')[0], 404)

    def test_canonical_and_legacy_vehicle_queries_share_only_the_selected_accounts_evidence(self):
        self.write(record(1, 'A', vehicle='Old caption', vehicle_id='type:257'),
                   record(2, 'A', vehicle='Old caption'),
                   record(3, 'A', vehicle='New caption', vehicle_id='type:257'),
                   record(4, 'B', vehicle='Old caption'))
        original = self.path.read_bytes()
        for selector in ('type:257', 'Old caption'):
            query = urlencode({'account': 'A', 'vehicle': selector})
            status, _, body = self.get('/?' + query)
            self.assertEqual(status, 200)
            self.assertIn('<option value="type:257" selected>Old caption</option>', body.decode('utf-8'))
            status, _, body = self.get('/export.csv?' + query)
            self.assertEqual(status, 200)
            rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
            self.assertEqual([row['arena_id'] for row in rows], ['1', '2', '3'])
            self.assertTrue(all(row['vehicle_id'] == 'type:257' for row in rows))
        status, _, body = self.get('/export.csv?' + urlencode({'account': 'B', 'vehicle': 'type:257'}))
        self.assertEqual(status, 200)
        self.assertEqual(list(csv.DictReader(io.StringIO(body.decode('utf-8-sig')))), [])
        self.assertEqual(self.path.read_bytes(), original)

    def test_partial_result_is_updated_without_double_counting(self):
        self.write(record(1, damage=None))
        self.get()
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record(1)) + '\n')
        status, _, data = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(len(self.server.journal.records()), 1)
        self.assertEqual(self.server.journal.records()[0]['damage'], 2500)
        self.assertIn('дополнений: 1', data.decode())


class CacheFailureTests(unittest.TestCase):
    def test_permission_error_clears_stale_data_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'battles.jsonl'
            path.write_text(json.dumps(record(1)) + '\n', encoding='utf-8')
            cache = CachedJournal(str(path))
            self.assertEqual(len(cache.records()), 1)
            # Metadata is unchanged: only the ability to open the file was lost.
            with patch('builtins.open', side_effect=PermissionError):
                self.assertEqual(cache.records(), [])
                self.assertEqual(cache.state, 'unreadable')
            self.assertEqual(len(cache.records()), 1)
            self.assertEqual(cache.state, 'ready')

    def test_direct_render_validates_bad_field_types(self):
        page = render([record(1), record(2, outcome=[])])
        self.assertIn('отклонённых строк: 1', page)


if __name__ == '__main__':
    unittest.main()
