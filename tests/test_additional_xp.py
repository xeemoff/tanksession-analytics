# -*- coding: utf-8 -*-
"""A confirmed per-battle bonus is explicit, idempotent and crash recoverable."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))
from tanksession_analytics import storage
from tanksession_analytics.core import MAX_RECORD_INTEGER, validate_record
from tanksession_analytics.storage import BattleStore


def row(**updates):
    value = {'schema': 1, 'account_id': '88', 'arena_id': '9001',
             'vehicle_id': 'type:257', 'vehicle': 'ussr:R04_T-34',
             'timestamp': 1700000000, 'mode': '1', 'outcome': 'win',
             'damage': 1000, 'xp': 600, 'xp_base': 100, 'xp_bonus': 500}
    value.update(updates)
    return value


class AdditionalXPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='tanksession-extra-xp-')
        self.path = os.path.join(self.folder, 'battles.jsonl')
        self.store = BattleStore(self.path)
        self.store.upsert(row())

    def tearDown(self):
        shutil.rmtree(self.folder)

    def apply(self, **updates):
        values = {'account_id': '88', 'arena_id': '9001', 'vehicle_id': 'type:257',
                  'expected_xp': 600, 'extra_xp': 450}
        values.update(updates)
        return self.store.apply_additional_xp(**values)

    def test_confirmed_bonus_changes_only_xp_and_known_bonus_once(self):
        before = dict(self.store.records[0])
        self.assertEqual(self.apply(), 'updated')
        after = self.store.records[0]
        self.assertEqual(after, dict(before, xp=1050, xp_bonus=950))
        self.assertEqual(self.apply(), 'duplicate')
        self.assertEqual(len(self.store.records), 1)
        self.assertEqual(self.store.diagnostics['lines'], 2)
        reopened = BattleStore(self.path)
        self.assertEqual(reopened.records, self.store.records)
        self.assertEqual(reopened.diagnostics['revisions'], 1)
        self.assertEqual(reopened.apply_additional_xp('88', '9001', 'type:257', 600, 450),
                         'duplicate')

    def test_original_and_current_repeat_without_losing_late_missing_fields(self):
        self.apply()
        self.assertEqual(self.store.upsert(row()), 'duplicate')
        self.assertEqual(self.store.upsert(row(xp=1050, xp_bonus=950)), 'duplicate')
        self.assertEqual(self.store.upsert(row(kills=2)), 'updated')
        reopened = BattleStore(self.path)
        self.assertEqual((reopened.records[0]['xp'], reopened.records[0]['xp_bonus'],
                          reopened.records[0]['kills']), (1050, 950, 2))
        self.assertEqual(reopened.upsert(row()), 'duplicate')
        self.assertEqual(len(reopened.records), 1)

    def test_ordinary_conflicts_stay_atomic_before_and_after_bonus(self):
        self.assertEqual(self.store.upsert(row(xp=601)), 'conflict')
        self.apply()
        for changed in (row(xp=601), row(xp=1051), row(damage=1001),
                        row(vehicle_id='type:513'), row(xp_bonus=501),
                        row(xp=1050, xp_bonus=500)):
            self.assertEqual(self.store.upsert(changed), 'conflict')
        self.assertEqual(self.store.diagnostics['lines'], 2)
        self.assertEqual(self.store.records[0]['xp'], 1050)

    def test_bonus_requires_existing_exact_account_arena_type_and_xp(self):
        for changes, expected in (({'account_id': '99'}, 'missing'),
                                  ({'arena_id': '9002'}, 'missing'),
                                  ({'vehicle_id': 'type:513'}, 'conflict'),
                                  ({'vehicle_id': 'name:ussr:R04_T-34'}, 'invalid'),
                                  ({'expected_xp': 601}, 'conflict'),
                                  ({'account_id': 'local'}, 'invalid'),
                                  ({'account_id': True}, 'invalid')):
            self.assertEqual(self.apply(**changes), expected)
        self.assertEqual(self.store.diagnostics['lines'], 1)
        self.assertEqual(self.store.records[0]['xp'], 600)
        self.apply()
        self.assertEqual(self.apply(extra_xp=451), 'conflict')
        self.assertEqual(self.apply(vehicle_id='type:513'), 'conflict')

    def test_invalid_or_overflowing_bonus_never_changes_record(self):
        for extra in (None, False, 0, -1, 0.5, float('nan'), float('inf'),
                      MAX_RECORD_INTEGER, MAX_RECORD_INTEGER + 1):
            self.assertEqual(self.apply(extra_xp=extra), 'invalid')
        self.assertEqual(self.store.records[0]['xp'], 600)
        self.assertEqual(self.store.diagnostics['lines'], 1)

    def test_unknown_economy_stays_unknown(self):
        self.store.upsert(row(arena_id='9002', xp_base=None, xp_bonus=None))
        self.assertEqual(self.apply(arena_id='9002'), 'updated')
        after = BattleStore(self.path).get_record({'account_id': '88', 'arena_id': '9002'})
        self.assertEqual(after['xp'], 1050)
        self.assertIsNone(after['xp_base'])
        self.assertIsNone(after['xp_bonus'])

    def test_missing_baseline_waits_for_normal_result_fill(self):
        self.store.upsert(row(arena_id='9002', xp=None, xp_bonus=None, vehicle_id=None))
        self.assertEqual(self.apply(arena_id='9002'), 'missing')
        self.assertEqual(self.store.upsert(row(arena_id='9002')), 'updated')
        self.assertEqual(self.apply(arena_id='9002'), 'updated')
        self.assertEqual(BattleStore(self.path).records[1]['xp'], 1050)

    def test_partial_bonus_without_total_cannot_guess_pre_or_post_award_meaning(self):
        self.store.upsert(row(arena_id='9002', xp_bonus=None))
        self.apply(arena_id='9002')
        self.assertEqual(self.store.upsert(row(arena_id='9002', xp=None, xp_bonus=150)),
                         'conflict')
        self.assertIsNone(self.store.records[1]['xp_bonus'])
        self.assertEqual(self.store.upsert(row(arena_id='9002', xp=1050, xp_bonus=950)),
                         'updated')
        self.assertEqual(BattleStore(self.path).records[1]['xp_bonus'], 950)

    def test_write_failure_keeps_baseline_and_allows_one_retry(self):
        original = storage._durable_append
        def fail(path, item):
            raise IOError('synthetic write failure')
        storage._durable_append = fail
        try:
            with self.assertRaises(IOError):
                self.apply()
        finally:
            storage._durable_append = original
        self.assertEqual(self.store.records[0]['xp'], 600)
        self.assertEqual(BattleStore(self.path).records[0]['xp'], 600)
        self.assertEqual(self.apply(), 'updated')
        self.assertEqual(self.apply(), 'duplicate')

    def test_truncated_revision_and_following_retry_preserve_one_battle(self):
        with open(self.path, 'ab') as stream:
            stream.write(b'{"event":"additional_xp",')
        self.store = BattleStore(self.path)
        self.assertEqual(self.store.records[0]['xp'], 600)
        self.apply()
        reopened = BattleStore(self.path)
        self.assertEqual(len(reopened.records), 1)
        self.assertEqual(reopened.records[0]['xp'], 1050)
        self.assertEqual(reopened.diagnostics['malformed'], 1)

    def test_invalid_or_orphan_event_is_never_another_battle(self):
        event = {'schema': 1, 'event': 'additional_xp', 'source': 'battle_results_service',
                 'account_id': '88', 'arena_id': '9001', 'vehicle_id': 'type:257',
                 'xp_before': 600, 'xp_delta': 450}
        self.assertIsNone(validate_record(event))
        for patch in ({'source': 'sessionStats'}, {'schema': 1.0}, {'arena_id': '9002'}):
            storage._durable_append(self.path, dict(event, **patch))
        reopened = BattleStore(self.path)
        self.assertEqual(reopened.diagnostics['invalid'], 3)
        self.assertEqual(len(reopened.records), 1)
        self.assertEqual(reopened.records[0]['xp'], 600)

    def test_compacted_journal_retains_proof_and_original_response_dedup(self):
        self.apply()
        self.store.upsert(row(kills=2))
        path = os.path.join(self.folder, 'compacted.jsonl')
        lines = self.store.compacted_records()
        self.assertEqual(len(lines), 2)
        for item in lines:
            storage._durable_append(path, item)
        reopened = BattleStore(path)
        self.assertEqual(reopened.records, self.store.records)
        self.assertEqual(reopened.upsert(row()), 'duplicate')
        self.assertEqual(reopened.apply_additional_xp('88', '9001', 'type:257', 600, 450),
                         'duplicate')

    def test_compaction_preserves_late_positive_bonus_after_negative_baseline(self):
        baseline = row(arena_id='9002', xp_base=900, xp_bonus=None)
        self.store.upsert(baseline)
        self.apply(arena_id='9002')
        # Base XP can exceed received XP before the extra award. The unknown
        # original bonus must not be reconstructed as a negative measurement.
        self.assertEqual(self.store.upsert(dict(baseline, xp=1050, xp_bonus=150)), 'updated')
        path = os.path.join(self.folder, 'late-bonus.jsonl')
        for item in self.store.compacted_records():
            storage._durable_append(path, item)
        reopened = BattleStore(path)
        self.assertEqual(reopened.records, self.store.records)
        self.assertEqual(reopened.diagnostics['invalid'], 0)
        self.assertEqual(reopened.upsert(baseline), 'duplicate')
        self.assertEqual(reopened.records[1]['xp_bonus'], 150)


if __name__ == '__main__':
    unittest.main()
