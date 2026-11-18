# -*- coding: utf-8 -*-
"""Opt-in adapter around an *unverified* result-cache API.

This module contains no game imports, threads, timers, or monkeypatches.
It assumes cache.get(arena_uid, callback(error_code, result)) from an old
community example. The live 2026 client signature MUST be checked first.
"""
import time

try:
    long_type = long
except NameError:
    long_type = int


class CacheRecovery(object):
    def __init__(self, pending, recorder, log=None, cooldown=15, max_requests=5):
        self.pending = pending
        self.recorder = recorder
        self.log = log or (lambda message: None)
        self.cooldown = cooldown
        self.max_requests = max_requests
        self.in_flight = {}
        self.attempted = {}
        self.active = True

    def stop(self):
        self.active = False
        self.in_flight.clear()

    def poll(self, cache, account_id, now=None):
        """Bounded best-effort requests, only for current-account pending IDs."""
        if not self.active or cache is None or not callable(getattr(cache, 'get', None)):
            return 0
        now = time.time() if now is None else now
        count = 0
        for entry in self.pending.eligible(account_id, now=now):
            arena = entry['arena_id']
            if arena in self.in_flight:
                if now - self.in_flight[arena] < 60:
                    continue
                self.in_flight.pop(arena, None)  # lost callback, allow retry
            if now - self.attempted.get(arena, -1e100) < self.cooldown:
                continue
            try:
                arena_uid = long_type(arena)
            except (ValueError, TypeError, OverflowError):
                continue
            self.attempted[arena] = now
            self.in_flight[arena] = now
            try:
                # Default arguments bind the correct arena per callback.
                cache.get(arena_uid, lambda error, result, aid=arena:
                          self._callback(aid, error, result))
                count += 1
            except Exception:
                self.in_flight.pop(arena, None)
                self.log('Result cache request unsupported / failed for ' + arena)
            if count >= self.max_requests:
                break
        return count

    def _callback(self, arena, error, result):
        self.in_flight.pop(arena, None)
        if not self.active:
            return
        try:
            if int(error) < 0 or not isinstance(result, dict):
                return  # transient/unavailable; retry on a later garage event
            status, record = self.recorder.receive(
                result, expected_arena=arena, confirmed_own=True)
            if status == 'saved':
                self.log('Recovered battle: ' + arena)
            elif status == 'mismatch':
                self.log('Cache result ID mismatch; ignored: ' + arena)
        except Exception:
            # Recovery must never break game events or leak raw payloads.
            self.log('Cache result rejected for ' + arena)
