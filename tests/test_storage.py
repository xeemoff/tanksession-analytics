import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.storage import BattleStore


class StorageTests(unittest.TestCase):
    def test_persistence_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'subfolder', 'battles.jsonl')
            store = BattleStore(path)
            record = {'account_id': 'player', 'arena_id': '123', 'vehicle': 'Tank', 'damage': 500}
            self.assertTrue(store.append(record))
            self.assertFalse(store.append(record))
            self.assertEqual(len(BattleStore(path).records), 1)
            # Same arena ID for another account is distinct.
            other = dict(record, account_id='other')
            self.assertTrue(store.append(other))
            self.assertEqual(len(BattleStore(path).records), 2)

    def test_ignores_truncated_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            with open(path, 'wb') as stream:
                stream.write(b'{"account_id":"local","arena_id":"1","damage":123}\n')
                stream.write(b'{"oops":')
            records = BattleStore(path).records
            self.assertEqual(len(records), 1)

    def test_rejects_missing_id(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BattleStore(os.path.join(folder, 'battles.jsonl'))
            with self.assertRaises(ValueError):
                store.append({'damage': 100})


if __name__ == '__main__':
    unittest.main()

class InterruptedWriteTests(unittest.TestCase):
    def test_new_record_after_truncated_line_stays_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            with open(path, 'wb') as stream:
                stream.write(b'{"account_id":"local","arena_id":"1","damage":123}\n')
                stream.write(b'{"incomplete":')
            store = BattleStore(path)
            self.assertTrue(store.append({'account_id': 'local', 'arena_id': '2', 'damage': 456}))
            self.assertEqual(len(BattleStore(path).records), 2)

class StorageV02Tests(unittest.TestCase):
    def test_key_rejects_blank_arena_and_merges_duplicate_file_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            with open(path, 'wb') as stream:
                stream.write(b'{"account_id":"X","arena_id":"12","damage":100}\n')
                stream.write(b'{"account_id":"X","arena_id":"12","damage":400}\n')
                stream.write(b'{"arena_id":" "}\n')
            store = BattleStore(path)
            self.assertEqual(len(store.records), 1)
            self.assertEqual(store.records[0]['damage'], 100)
            for record in ({'arena_id': '   '}, {'arena_id': 0}, {'arena_id': '0'}):
                with self.assertRaises(ValueError):
                    store.append(record)

    def test_durable_reopen_preserves_utf8_and_large_arena_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            arena = '9223372036854775807'
            first = BattleStore(path)
            first.append({'arena_id': arena, 'account_id': 4, 'vehicle': 'Объект 277'})
            again = BattleStore(path)
            self.assertEqual(again.records[0]['vehicle'], 'Объект 277')
            self.assertFalse(again.append({'arena_id': arena, 'account_id': 4}))

    def test_invalid_jsonl_does_not_poison_following_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            with open(path, 'wb') as stream:
                stream.write(b'{"arena_id":"1"}\n{broken json}\n')
            store = BattleStore(path)
            store.append({'arena_id': '2'})
            self.assertEqual(len(BattleStore(path).records), 2)
