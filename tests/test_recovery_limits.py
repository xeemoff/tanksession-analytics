# -*- coding: utf-8 -*-
"""Regression tests for bounded cache work and stale asynchronous callbacks."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))

from tanksession_analytics.recovery import CacheRecovery


class Pending(object):
    def __init__(self, accounts):
        self.accounts = accounts

    def eligible(self, account, now=None):
        return [{'arena_id': arena} for arena, owner in self.accounts
                if str(owner) == str(account)]


class Recorder(object):
    def __init__(self):
        self.calls = []

    def receive(self, payload, **kwargs):
        self.calls.append((payload, kwargs))
        return 'saved', {'arena_id': str(payload['arenaUniqueID']),
                         'data_status': 'complete'}


class Cache(object):
    def __init__(self, raises=False):
        self.requests = []
        self.raises = raises

    def get(self, arena, callback):
        self.requests.append((arena, callback))
        if self.raises:
            raise RuntimeError('API unavailable')

    def reply(self, index, error=0):
        arena, callback = self.requests[index]
        callback(error, {'arenaUniqueID': arena})


class RecoveryLimitTests(unittest.TestCase):
    def test_immediate_failures_consume_attempt_budget(self):
        pending = Pending([(str(i), 'A') for i in range(1, 33)])
        recovery = CacheRecovery(pending, Recorder(), max_requests=5)
        cache = Cache(raises=True)
        self.assertEqual(recovery.poll(cache, 'A', now=100), 5)
        self.assertEqual(len(cache.requests), 5)
        self.assertFalse(recovery.in_flight)
        self.assertFalse(recovery._request_tokens)

    def test_posted_signal_retries_only_matching_pending_once(self):
        pending = Pending([('1', 'A'), ('2', 'A'), ('3', 'B')])
        recorder, cache, logs = Recorder(), Cache(), []
        recovery = CacheRecovery(pending, recorder, log=logs.append,
                                 max_requests=1, serialize=True)
        self.assertEqual(recovery.poll(cache, 'A', now=100), 1)
        self.assertEqual(cache.requests[0][0], 2)
        cache.reply(0, error=-5)
        self.assertTrue(any('cooldown' in line for line in logs))
        self.assertEqual(recovery.poll(cache, 'A', now=101, arena_id=2, posted=True), 1)
        self.assertEqual(recovery.poll(cache, 'A', now=102, arena_id=1, posted=True), 0)
        cache.reply(1, error=-10)
        self.assertEqual(recovery.poll(cache, 'A', now=103, arena_id=2, posted=True), 0)
        self.assertEqual(recovery.poll(cache, 'A', now=103, arena_id=3, posted=True), 0)
        self.assertFalse(recorder.calls)

    def test_deferred_posted_signal_drains_once_after_busy_request(self):
        pending = Pending([('1', 'A'), ('2', 'A'), ('3', 'B')])
        cache = Cache()
        recovery = CacheRecovery(pending, Recorder(), max_requests=1, serialize=True)
        recovery.poll(cache, 'A', now=100)
        self.assertEqual(cache.requests[0][0], 2)
        for arena in (1, 1, 3):
            self.assertEqual(recovery.poll(cache, 'A', now=101,
                                           arena_id=arena, posted=True), 0)
        self.assertTrue(recovery.has_deferred())
        self.assertEqual(recovery.drain_deferred(cache, 'A', now=102), 0)
        cache.reply(0, error=-10)
        self.assertEqual(recovery.drain_deferred(cache, 'A', now=103), 1)
        self.assertEqual([item[0] for item in cache.requests], [2, 1])
        self.assertFalse(recovery.has_deferred())

    def test_deferred_signal_already_resolved_is_not_requested(self):
        pending = Pending([('1', 'A')])
        cache = Cache()
        recovery = CacheRecovery(pending, Recorder(), max_requests=1, serialize=True)
        recovery.poll(cache, 'A', now=100)
        recovery.poll(cache, 'A', now=101, arena_id=1, posted=True)
        self.assertTrue(recovery.has_deferred())
        cache.reply(0)
        pending.accounts = []
        self.assertEqual(recovery.drain_deferred(cache, 'A', now=102), 0)
        self.assertFalse(recovery.has_deferred())
        self.assertEqual(len(cache.requests), 1)

    def test_deferred_drain_after_timeout_rejects_old_callback(self):
        recorder, cache = Recorder(), Cache()
        recovery = CacheRecovery(Pending([('1', 'A'), ('2', 'A')]), recorder,
                                 max_requests=1, serialize=True)
        recovery.poll(cache, 'A', now=100)
        recovery.poll(cache, 'A', now=101, arena_id=1, posted=True)
        self.assertEqual(recovery.drain_deferred(cache, 'A', now=160), 1)
        cache.reply(0)
        self.assertFalse(recorder.calls)
        cache.reply(1)
        self.assertEqual(len(recorder.calls), 1)

    def test_deferred_work_does_not_cross_login_or_stop(self):
        recovery = CacheRecovery(Pending([('1', 'A')]), Recorder(),
                                 max_requests=1, serialize=True)
        cache = Cache()
        recovery.poll(cache, 'A', now=100)
        recovery.poll(cache, 'A', now=101, arena_id=1, posted=True)
        recovery.reset_session('A')
        self.assertFalse(recovery.has_deferred())
        recovery.poll(cache, 'A', now=102)
        recovery.poll(cache, 'A', now=103, arena_id=1, posted=True)
        self.assertTrue(recovery.has_deferred())
        recovery.stop()
        self.assertFalse(recovery.has_deferred())

    def test_zero_budget_makes_no_request(self):
        recovery = CacheRecovery(Pending([('1', 'A')]), Recorder(), max_requests=0)
        cache = Cache()
        self.assertEqual(recovery.poll(cache, 'A', now=100), 0)
        self.assertFalse(cache.requests)

    def test_immediate_failure_obeys_retry_cooldown(self):
        recovery = CacheRecovery(Pending([('1', 'A')]), Recorder(), cooldown=15)
        cache = Cache(raises=True)
        self.assertEqual(recovery.poll(cache, 'A', now=100), 1)
        self.assertEqual(recovery.poll(cache, 'A', now=114), 0)
        self.assertEqual(recovery.poll(cache, 'A', now=115), 1)
        self.assertEqual(len(cache.requests), 2)

    def test_timed_out_callback_cannot_consume_replacement(self):
        recorder = Recorder()
        recovery = CacheRecovery(Pending([('1', 'A')]), recorder)
        cache = Cache()
        self.assertEqual(recovery.poll(cache, 'A', now=100), 1)
        self.assertEqual(recovery.poll(cache, 'A', now=161), 1)
        cache.reply(0)
        self.assertEqual(recorder.calls, [])
        self.assertIn('1', recovery.in_flight)
        cache.reply(1)
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0][1]['current_context'], {'account_id': 'A'})
        self.assertFalse(recovery.in_flight)
        # Repeated delivery of this callback also cannot record it twice.
        cache.reply(1)
        self.assertEqual(len(recorder.calls), 1)

    def test_account_switch_invalidates_old_callbacks(self):
        recorder = Recorder()
        recovery = CacheRecovery(Pending([('1', 'A'), ('2', 'B')]), recorder)
        cache = Cache()
        recovery.poll(cache, 'A', now=100)
        recovery.poll(cache, 'B', now=101)
        cache.reply(0)
        self.assertEqual(recorder.calls, [])
        self.assertIn('2', recovery.in_flight)
        cache.reply(1)
        self.assertEqual(recorder.calls[0][1]['current_context'], {'account_id': 'B'})

    def test_same_account_login_invalidates_old_callbacks(self):
        recorder = Recorder()
        recovery = CacheRecovery(Pending([('1', 'A')]), recorder)
        cache = Cache()
        recovery.poll(cache, 'A', now=100)
        recovery.reset_session('A')
        recovery.poll(cache, 'A', now=101)
        cache.reply(0)
        self.assertFalse(recorder.calls)
        self.assertIn('1', recovery.in_flight)
        cache.reply(1)
        self.assertEqual(len(recorder.calls), 1)

    def test_unknown_account_and_stop_invalidate_callbacks(self):
        recorder = Recorder()
        recovery = CacheRecovery(Pending([('1', 'A')]), recorder)
        cache = Cache()
        recovery.poll(cache, 'A', now=100)
        self.assertEqual(recovery.poll(cache, None, now=101), 0)
        cache.reply(0)
        self.assertFalse(recorder.calls)
        recovery.poll(cache, 'A', now=102)
        recovery.stop()
        cache.reply(1)
        self.assertFalse(recorder.calls)
        self.assertEqual(recovery.poll(cache, 'A', now=200), 0)


if __name__ == '__main__':
    unittest.main()
