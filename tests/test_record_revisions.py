# -*- coding: utf-8 -*-
"""Regression contracts for partial results and untrusted JSONL history."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from tanksession_analytics.core import validate_record, normalize_result, MAX_RECORD_INTEGER
from tanksession_analytics.storage import BattleStore, PendingJournal
from tanksession_analytics.recorder import ResultRecorder
from maintain_data import inspect, compact


def snapshot(**updates):
    record = {'schema': 1, 'account_id': 'A', 'arena_id': '99',
              'timestamp': 1720000000, 'vehicle': 'IS-7', 'mode': '1',
              'outcome': 'win', 'damage': None, 'xp': 550}
    record.update(updates)
    return record


def payload(damage):
    return {'arenaUniqueID': 99, 'common': {'winnerTeam': 1, 'bonusType': 1},
            'personal': {42: {'team': 1, 'damageDealt': damage, 'xp': 550}}}


class RecordValidationTests(unittest.TestCase):
    def test_legacy_minimal_and_numeric_strings_preserve_unknowns(self):
        record = validate_record({'arena_id': 99, 'account_id': 7,
                                  'damage': '0', 'timestamp': '1720000000'})
        self.assertEqual(record['schema'], 1)
        self.assertEqual(record['account_id'], '7')
        self.assertEqual(record['damage'], 0)
        self.assertEqual(record['timestamp'], 1720000000)
        self.assertIsNone(record['xp'])
        self.assertIsNone(record['assistance_radio'])
        self.assertEqual(record['outcome'], 'unknown')
        self.assertEqual(record['data_status'], 'incomplete')

    def test_completion_is_derived_and_zero_is_a_known_value(self):
        self.assertEqual(validate_record(snapshot(data_status='complete'))['data_status'],
                         'incomplete')
        self.assertEqual(validate_record(snapshot(damage=0, xp=0))['data_status'], 'complete')
        self.assertEqual(validate_record(snapshot(damage=100, outcome='unknown'))['data_status'],
                         'incomplete')

    def test_malformed_fields_and_future_schemas_are_rejected(self):
        for patch in ({'outcome': []}, {'outcome': 'victory'}, {'vehicle': {}},
                      {'account_id': []}, {'arena_id': []}, {'arena_id': True},
                      {'damage': True}, {'damage': -1}, {'damage': 1.5},
                      {'timestamp': 'yesterday'}, {'schema': 2}, {'schema': True}):
            with self.subTest(patch=patch):
                self.assertIsNone(validate_record(snapshot(**patch)))
        self.assertIsNone(validate_record(None))

    def test_record_numbers_are_limited_to_nonnegative_signed_64_bit(self):
        for field in ('timestamp', 'damage', 'xp', 'assistance_radio', 'assistance_track'):
            with self.subTest(field=field):
                self.assertEqual(validate_record(snapshot(**{field: MAX_RECORD_INTEGER}))[field],
                                 MAX_RECORD_INTEGER)
                self.assertIsNone(validate_record(snapshot(**{field: MAX_RECORD_INTEGER + 1})))
                self.assertIsNone(validate_record(snapshot(**{field: 10 ** 400})))

    def test_normalizer_treats_oversized_measurements_as_unknown(self):
        raw = payload(10 ** 400)
        raw['personal'][42]['xp'] = 10 ** 400
        raw['personal'][42]['damageAssistedRadio'] = 10 ** 400
        raw['personal'][42]['damageAssistedTrack'] = 10 ** 400
        record = normalize_result(raw, {'player_vehicle_id': 42}, observed_at=1720000000)
        for field in ('damage', 'xp', 'assistance_radio', 'assistance_track'):
            self.assertIsNone(record[field])
        self.assertEqual(record['data_status'], 'incomplete')
        self.assertIsNone(normalize_result(payload(100), observed_at=10 ** 400))


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, 'battles.jsonl')
        self.store = BattleStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_partial_complete_repeat_and_restart_keep_one_battle(self):
        partial, complete = snapshot(), snapshot(damage=2500, timestamp=1720000100)
        self.assertEqual(self.store.upsert(partial), 'saved')
        self.assertEqual(self.store.upsert(complete), 'updated')
        self.assertEqual(self.store.upsert(complete), 'duplicate')
        reopened = BattleStore(self.path)
        self.assertEqual(len(reopened.records), 1)
        self.assertEqual(reopened.records[0]['damage'], 2500)
        self.assertEqual(reopened.records[0]['timestamp'], 1720000000)
        self.assertEqual(reopened.records[0]['data_status'], 'complete')
        self.assertEqual(reopened.diagnostics['lines'], 2)
        self.assertEqual(reopened.diagnostics['revisions'], 1)
        self.assertEqual(reopened.upsert(complete), 'duplicate')
        self.assertEqual(reopened.diagnostics, BattleStore(self.path).diagnostics)

    def test_conflict_rejects_entire_revision_without_changing_known_values(self):
        self.store.upsert(snapshot(damage=100, xp=None))
        self.assertEqual(self.store.upsert(snapshot(damage=200, xp=550)), 'conflict')
        self.assertEqual(self.store.records[0]['damage'], 100)
        self.assertIsNone(self.store.records[0]['xp'])
        self.assertEqual(BattleStore(self.path).diagnostics['lines'], 1)

    def test_optional_assistance_can_arrive_after_primary_completion(self):
        self.store.upsert(snapshot(damage=2500))
        self.assertEqual(self.store.upsert(snapshot(damage=2500, assistance_track=0)),
                         'updated')
        self.assertEqual(BattleStore(self.path).records[0]['assistance_track'], 0)
        self.assertIsNone(self.store.records[0]['assistance_radio'])

    def test_legacy_append_does_not_enrich_or_cross_accounts(self):
        self.assertTrue(self.store.append(snapshot()))
        self.assertFalse(self.store.append(snapshot(damage=2500)))
        self.assertIsNone(self.store.records[0]['damage'])
        self.assertEqual(self.store.upsert(snapshot(account_id='B', damage=700)), 'saved')
        self.assertEqual(len(self.store.records), 2)
        self.assertEqual(self.store.upsert(snapshot(account_id='local', damage=999)),
                         'duplicate')
        self.assertIsNone(self.store.get_record({'account_id': 'local', 'arena_id': '99'}))

    def test_legacy_local_record_is_not_attributed_to_a_later_account(self):
        self.store.upsert(snapshot(account_id='local'))
        self.assertEqual(self.store.upsert(snapshot(account_id='A', damage=2500)), 'duplicate')
        self.assertEqual(self.store.records[0]['account_id'], 'local')
        self.assertIsNone(self.store.records[0]['damage'])

    def test_failed_durable_write_does_not_advance_the_snapshot(self):
        self.store.upsert(snapshot())
        before = dict(self.store.diagnostics)
        with mock.patch('tanksession_analytics.storage._durable_append',
                        side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                self.store.upsert(snapshot(damage=2500))
        self.assertIsNone(self.store.records[0]['damage'])
        self.assertEqual(self.store.diagnostics, before)
        self.assertIsNone(BattleStore(self.path).records[0]['damage'])

    def test_bad_record_cannot_be_appended(self):
        with self.assertRaises(ValueError):
            self.store.upsert(snapshot(outcome=[]))
        self.assertEqual(self.store.records, [])
        self.assertFalse(os.path.exists(self.path))

    def test_pending_survives_partial_and_finishes_after_durable_completion(self):
        pending_path = self.path + '.pending.jsonl'
        pending = PendingJournal(pending_path)
        pending.start(99, {'account_id': 'A', 'player_vehicle_id': 42,
                           'vehicle_name': 'IS-7', 'team': 1}, 1720000000)
        recorder = ResultRecorder(self.store, pending, require_account=True)
        status, record = recorder.receive(payload(None), {'account_id': 'A'},
                                           observed_at=1720000020, confirmed_own=True)
        self.assertEqual((status, record['data_status']), ('saved', 'incomplete'))
        self.assertIn('99', pending.pending)
        pending = PendingJournal(pending_path)
        recorder = ResultRecorder(BattleStore(self.path), pending, require_account=True)
        status, record = recorder.receive(payload(2500), {'account_id': 'A'},
                                           observed_at=1720000100, confirmed_own=True)
        self.assertEqual((status, record['data_status'], record['damage']),
                         ('updated', 'complete', 2500))
        self.assertEqual(pending.pending, {})
        self.assertEqual(len(BattleStore(self.path).records), 1)
        self.assertEqual(recorder.receive(payload(2500), {'account_id': 'A'},
                                         confirmed_own=True)[0], 'duplicate')

    def test_conflict_does_not_clear_pending(self):
        pending = PendingJournal(self.path + '.pending.jsonl')
        pending.start(99, {'account_id': 'A', 'player_vehicle_id': 42}, 1720000000)
        self.store.upsert(snapshot(damage=100, xp=None))
        recorder = ResultRecorder(self.store, pending, require_account=True)
        status, record = recorder.receive(payload(200), {'account_id': 'A'},
                                           confirmed_own=True)
        self.assertEqual(status, 'conflict')
        self.assertIsNone(record['xp'])
        self.assertIn('99', pending.pending)


class JournalDiagnosticsTests(unittest.TestCase):
    def test_offline_compaction_keeps_additional_xp_evidence_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            baseline = {'schema': 1, 'account_id': '88', 'arena_id': '9001',
                        'vehicle_id': 'type:257', 'vehicle': 'ussr:R04_T-34',
                        'timestamp': 1700000000, 'xp': 600, 'xp_base': 900,
                        'xp_bonus': None, 'damage': 1000, 'outcome': 'win'}
            store = BattleStore(path)
            store.upsert(baseline)
            store.apply_additional_xp('88', '9001', 'type:257', 600, 450)
            store.upsert(dict(baseline, xp=1050, xp_bonus=150))
            with open(path, 'rb') as stream:
                original = stream.read()
            details = compact(path)
            self.assertEqual(details['records'], 1)
            with open(details['backup'], 'rb') as stream:
                self.assertEqual(stream.read(), original)
            reopened = BattleStore(path)
            self.assertEqual(reopened.records, store.records)
            self.assertEqual(reopened.diagnostics['invalid'], 0)
            self.assertEqual(reopened.upsert(baseline), 'duplicate')
            self.assertEqual(reopened.apply_additional_xp('88', '9001', 'type:257', 600, 450),
                             'duplicate')

    def test_counts_do_not_conflate_revisions_conflicts_and_invalid_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            rows = [snapshot(), snapshot(damage=2500), snapshot(damage=2500),
                    snapshot(damage=1000), snapshot(outcome=[]), snapshot(schema=2),
                    {'arena_id': '100', 'damage': '0'}]
            original = b''.join((json.dumps(r) + '\n').encode('utf-8') for r in rows)
            original += b'{broken json}\n[]\n'
            with open(path, 'wb') as stream:
                stream.write(original)
            expected = {'lines': 9, 'valid_unique': 2, 'revisions': 1,
                        'duplicates': 1, 'conflicts': 1, 'invalid': 2, 'malformed': 2}
            store = BattleStore(path)
            self.assertEqual(store.diagnostics, expected)
            self.assertEqual(inspect(path)['invalid_or_unusable'], 4)
            with open(path, 'rb') as stream:
                self.assertEqual(stream.read(), original)
            details = compact(path)
            self.assertEqual(details['diagnostics_before'], expected)
            with open(details['backup'], 'rb') as stream:
                self.assertEqual(stream.read(), original)
            reopened = BattleStore(path)
            self.assertEqual(len(reopened.records), 2)
            self.assertEqual(reopened.records[0]['damage'], 2500)
            self.assertEqual(reopened.diagnostics['lines'], 2)

    def test_large_bad_line_and_bad_types_do_not_hide_following_valid_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'battles.jsonl')
            with open(path, 'wb') as stream:
                stream.write(b'x' * 600000 + b'\n')
                stream.write(b'{"arena_id":"1","outcome":[]}\n')
                stream.write(b'{"arena_id":"2","damage":0}\n')
            store = BattleStore(path)
            self.assertEqual(store.diagnostics['lines'], 3)
            self.assertEqual(store.diagnostics['malformed'], 1)
            self.assertEqual(store.diagnostics['invalid'], 1)
            self.assertEqual(store.records[0]['arena_id'], '2')


if __name__ == '__main__':
    unittest.main()
