# -*- coding: utf-8 -*-
"""Contract tests with simulated events / cache; NOT live client tests."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.storage import BattleStore, PendingJournal
from tanksession_analytics.recorder import ResultRecorder
from tanksession_analytics.recovery import CacheRecovery


def result(arena, damage=1234):
    return {'arenaUniqueID': arena, 'common': {'winnerTeam': 1, 'bonusType': 1},
            'personal': {42: {'team': 1, 'damageDealt': damage, 'xp': 550}}}


class FakeResultCache(object):
    def __init__(self):
        self.requests = []

    def get(self, arena_uid, callback):
        self.requests.append((arena_uid, callback))

    def reply(self, error, payload, index=-1):
        self.requests[index][1](error, payload)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = self.temp.name
        self.store = BattleStore(os.path.join(folder, 'battles.jsonl'))
        self.pending = PendingJournal(os.path.join(folder, 'pending.jsonl'))
        self.recorder = ResultRecorder(self.store, self.pending)

    def tearDown(self):
        self.temp.cleanup()

    def test_live_capture_without_verified_identity_is_rejected(self):
        live = ResultRecorder(self.store, self.pending, require_account=True)
        status, record = live.receive(result(997), confirmed_own=True)
        self.assertEqual((status, record), ('identity_missing', None))
        self.assertEqual(self.store.records, [])
        status, record = live.receive(result(998),
                                      current_context={'account_id': 88},
                                      confirmed_own=True)
        self.assertEqual(status, 'saved')
        self.assertEqual(record['account_id'], '88')

    def test_late_result_cannot_cross_account_boundary(self):
        self.pending.start(990, {'account_id': 88, 'player_vehicle_id': 42,
                                 'vehicle_name': 'ИС-7'}, 1720000000)
        live = ResultRecorder(self.store, self.pending, require_account=True)
        status, record = live.receive(result(990),
                                      current_context={'account_id': 99},
                                      confirmed_own=True)
        self.assertEqual((status, record), ('account_mismatch', None))
        self.assertIn('990', self.pending.pending)
        self.assertEqual(self.store.records, [])
        # Switching back to the right account permits safe completion.
        self.assertEqual(live.receive(result(990),
                                      current_context={'account_id': 88},
                                      confirmed_own=True)[0], 'saved')

    def test_delayed_result_uses_saved_vehicle_context(self):
        self.pending.start(800, {'account_id': 5, 'player_vehicle_id': 42,
                                 'vehicle_name': 'ИС-7', 'team': 1}, 1720000000)
        self.assertEqual(len(self.store.records), 0)
        # Simulate receiving the post-battle event *in the garage* with no
        # tank entity left. Pending context must still name our vehicle.
        status, record = self.recorder.receive(result(800), {'account_id': 5},
                                                observed_at=1720000200,
                                                confirmed_own=True)
        self.assertEqual(status, 'saved')
        self.assertEqual(record['vehicle'], 'ИС-7')
        self.assertEqual(record['damage'], 1234)
        self.assertFalse(self.pending.pending)
        self.assertEqual(self.recorder.receive(result(800), confirmed_own=True)[0],
                         'duplicate')
        self.assertEqual(len(BattleStore(self.store.path).records), 1)

    def test_cache_recovery_after_leaving_battle(self):
        self.pending.start('9223372036854775807',
                           {'account_id': '5', 'player_vehicle_id': 42,
                            'vehicle_name': 'T-34-85', 'team': 1}, 1720000000)
        # No immediate result event; simulate availability via cache instead.
        cache = FakeResultCache()
        recovery = CacheRecovery(self.pending, self.recorder)
        self.assertEqual(recovery.poll(cache, '5', now=1720000020), 1)
        self.assertEqual(cache.requests[0][0], 9223372036854775807)
        cache.reply(0, result('9223372036854775807', 2500))
        self.assertEqual(self.store.records[0]['vehicle'], 'T-34-85')
        self.assertEqual(self.store.records[0]['damage'], 2500)
        self.assertEqual(recovery.poll(cache, '5', now=1720000080), 0)
        self.assertEqual(self.pending.pending, {})

    def test_result_from_wrong_arena_is_never_saved(self):
        self.pending.start(900, {'account_id': 1, 'team': 1}, 1720000000)
        recovery = CacheRecovery(self.pending, self.recorder)
        cache = FakeResultCache()
        recovery.poll(cache, 1, now=1720000010)
        cache.reply(0, result(901))
        self.assertEqual(len(self.store.records), 0)
        self.assertIn('900', self.pending.pending)

    def test_account_isolation_and_expiration(self):
        self.pending.start(901, {'account_id': 'A'}, 1720000000)
        self.pending.start(902, {'account_id': 'B'}, 1720000000)
        cache = FakeResultCache()
        recovery = CacheRecovery(self.pending, self.recorder)
        self.assertEqual(recovery.poll(cache, 'B', now=1720000010), 1)
        self.assertEqual(cache.requests[0][0], 902)
        self.assertEqual(recovery.poll(cache, 'A', now=1720000000 + 9 * 86400), 0)
        self.assertEqual(recovery.poll(cache, None, now=1720000030), 0)

    def test_error_then_throttled_retry(self):
        self.pending.start(903, {'account_id': 3}, 1720000000)
        cache = FakeResultCache()
        recovery = CacheRecovery(self.pending, self.recorder, cooldown=15)
        self.assertEqual(recovery.poll(cache, 3, now=1720000001), 1)
        cache.reply(-3, None)
        self.assertEqual(recovery.poll(cache, 3, now=1720000005), 0)
        self.assertEqual(recovery.poll(cache, 3, now=1720000017), 1)
        cache.reply(0, result(903))
        self.assertEqual(len(self.store.records), 1)

    def test_lost_callback_can_be_retried(self):
        self.pending.start(904, {'account_id': 3}, 1720000000)
        cache = FakeResultCache()
        recovery = CacheRecovery(self.pending, self.recorder, cooldown=15)
        self.assertEqual(recovery.poll(cache, 3, now=1720000001), 1)
        self.assertEqual(recovery.poll(cache, 3, now=1720000030), 0)
        self.assertEqual(recovery.poll(cache, 3, now=1720000062), 1)
        recovery.stop()
        cache.reply(0, result(904))
        self.assertEqual(len(self.store.records), 0)

    def test_pending_survives_restart_and_truncated_line(self):
        self.pending.start(905, {'account_id': 3, 'vehicle_name': 'ИС-7'},
                           1720000000)
        with open(self.pending.path, 'ab') as stream:
            stream.write(b'{"unclosed":')
        reopened = PendingJournal(self.pending.path)
        self.assertEqual(reopened.context(905)['vehicle_name'], 'ИС-7')
        self.assertTrue(reopened.finish(905))
        self.assertFalse(PendingJournal(self.pending.path).pending)

    def test_duplicate_start_does_not_change_snapshot(self):
        self.pending.start(906, {'account_id': 3, 'vehicle_name': 'A'}, 1720000000)
        self.assertFalse(self.pending.start(906, {'vehicle_name': 'B'}, 1720000020))
        self.assertEqual(self.pending.context(906)['vehicle_name'], 'A')

    def test_unmatched_cache_identifier_is_rejected(self):
        self.assertEqual(self.recorder.receive(result(1), expected_arena=2,
                                               confirmed_own=True)[0], 'mismatch')
        self.assertEqual(len(self.store.records), 0)


if __name__ == '__main__':
    unittest.main()
