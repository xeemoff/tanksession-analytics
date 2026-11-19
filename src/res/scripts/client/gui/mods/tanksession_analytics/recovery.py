# -*- coding: utf-8 -*-
"""Opt-in adapter around an *unverified* result-cache API.

This module contains no game imports, threads, timers, or monkeypatches.
It assumes cache.get(arena_uid, callback(error_code, result)) from an old
community example. The live 2026 client signature MUST be checked first.
"""
import time

from .recorder import _verified_account

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
        self._request_tokens = {}
        self._account_id = None
        self.active = True

    def stop(self):
        self.active = False
        self.in_flight.clear()
        self._request_tokens.clear()

    def reset_session(self, account_id=None):
        """Invalidate callbacks even when a new login reuses the same account.

        Request tokens are deliberately local to one attempt. An old callback
        must not consume a replacement request after its timeout or login.
        """
        self._account_id = _verified_account(account_id)
        self.in_flight.clear()
        self._request_tokens.clear()
        self.attempted.clear()

    def poll(self, cache, account_id, now=None):
        """Return attempted requests, including calls that raise immediately."""
        if not self.active:
            return 0
        account = _verified_account(account_id)
        if account != self._account_id:
            self.reset_session(account)
        if account is None or cache is None or not callable(getattr(cache, 'get', None)):
            return 0
        now = time.time() if now is None else now
        count = 0
        for entry in self.pending.eligible(account, now=now):
            if count >= self.max_requests:
                break
            arena = entry['arena_id']
            if arena in self.in_flight:
                if now - self.in_flight[arena] < 60:
                    continue
                self.in_flight.pop(arena, None)  # lost callback, allow retry
                self._request_tokens.pop(arena, None)
            if now - self.attempted.get(arena, -1e100) < self.cooldown:
                continue
            try:
                arena_uid = long_type(arena)
            except (ValueError, TypeError, OverflowError):
                continue
            self.attempted[arena] = now
            self.in_flight[arena] = now
            token = object()
            self._request_tokens[arena] = token
            # A failed/unsupported API call still consumes this event's budget.
            count += 1
            try:
                # Bind arena, account and attempt; callbacks may arrive late.
                cache.get(arena_uid, lambda error, result, aid=arena,
                          request=token, owner=account:
                          self._callback(aid, error, result, request, owner))
            except Exception:
                if self._request_tokens.get(arena) is token:
                    self.in_flight.pop(arena, None)
                    self._request_tokens.pop(arena, None)
                self.log('Result cache request unsupported / failed')
        return count

    def _callback(self, arena, error, result, token, account):
        if (not self.active or account != self._account_id or
                self._request_tokens.get(arena) is not token):
            return
        self._request_tokens.pop(arena, None)
        self.in_flight.pop(arena, None)
        try:
            if int(error) < 0 or not isinstance(result, dict):
                return  # transient/unavailable; retry on a later garage event
            status, record = self.recorder.receive(
                result, current_context={'account_id': account},
                expected_arena=arena, confirmed_own=True)
            if status == 'saved':
                self.log('Recovered battle: ' + record.get('data_status', 'incomplete'))
            elif status == 'updated':
                self.log('Updated battle: cache ' + record.get('data_status', 'incomplete'))
            elif status == 'conflict':
                self.log('Battle result conflict: cache result kept unchanged')
            elif status == 'mismatch':
                self.log('Cache result ID mismatch; ignored')
        except Exception:
            # Recovery must never break game events or leak raw payloads.
            self.log('Cache result rejected')
