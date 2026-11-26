# -*- coding: utf-8 -*-
"""Opt-in adapter around an *unverified* result-cache API.

This module contains no game imports, threads, timers, or monkeypatches.
The signature cache.get(arena_uid, callback(error_code, result)) is
consistent with a reference client branch. Actual MT support remains opt-in.
"""
import time

from .recorder import _verified_account

try:
    long_type = long
except NameError:
    long_type = int


class CacheRecovery(object):
    def __init__(self, pending, recorder, log=None, cooldown=15, max_requests=5,
                 account_provider=None, on_record=None, serialize=False):
        self.pending = pending
        self.recorder = recorder
        self.log = log or (lambda message: None)
        self.cooldown = cooldown
        self.max_requests = max_requests
        self.account_provider = account_provider
        self.on_record = on_record
        self.serialize = serialize
        self._posted_attempted = set()
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
        self._posted_attempted.clear()

    def poll(self, cache, account_id, now=None, arena_id=None, posted=False):
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
        # The native cache may serialize its own requests. Do not compete
        # with a still-running request issued by this adapter.
        if self.serialize and any(now - started < 60
                                  for started in self.in_flight.values()):
            return 0
        entries = self.pending.eligible(account, now=now)
        if arena_id is not None:
            entries = [entry for entry in entries
                       if str(entry['arena_id']) == str(arena_id)]
        # Prefer untried entries, newest first; then least recently attempted.
        entries = sorted(reversed(entries),
                         key=lambda entry: self.attempted.get(entry['arena_id'], -1e100))
        for entry in entries:
            if count >= self.max_requests:
                break
            arena = entry['arena_id']
            if arena in self.in_flight:
                if now - self.in_flight[arena] < 60:
                    continue
                self.in_flight.pop(arena, None)  # lost callback, allow retry
                self._request_tokens.pop(arena, None)
                self.log('Result cache request timed out')
            # The lobby service has just obtained the result. Permit one
            # early retry on this explicit signal, not on every UI click.
            early = posted and arena not in self._posted_attempted
            if not early and now - self.attempted.get(arena, -1e100) < self.cooldown:
                continue
            try:
                arena_uid = long_type(arena)
            except (ValueError, TypeError, OverflowError):
                continue
            self.attempted[arena] = now
            if posted:
                self._posted_attempted.add(arena)
            self.in_flight[arena] = now
            token = object()
            self._request_tokens[arena] = token
            # A failed/unsupported API call still consumes this event's budget.
            count += 1
            self.log('Result cache request started')
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
            if self.account_provider is not None:
                if _verified_account(self.account_provider()) != account:
                    self.log('Cache result ignored: account no longer confirmed')
                    return
                if _verified_account(self.pending.context(arena).get('account_id')) != account:
                    self.log('Cache result ignored: no matching pending battle')
                    return
            code = int(error)
            if code not in (0, 1, 2):
                reason = {-3: 'non_player', -5: 'cooldown', -10: 'not_available'}.get(code, 'other')
                self.log('Result cache response unavailable: ' + reason)
                return
            if not isinstance(result, dict):
                self.log('Result cache response has no result')
                return
            personal = result.get('personal')
            avatar = personal.get('avatar') if isinstance(personal, dict) else None
            if isinstance(avatar, dict) and 'accountDBID' in avatar:
                if _verified_account(avatar['accountDBID']) != account:
                    self.log('Cache result ignored: personal account mismatch')
                    return
            self.log('Result cache response received')
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
            elif status in ('skipped', 'identity_missing', 'account_mismatch'):
                self.log('Cache result skipped: ' + status)
            elif status == 'duplicate':
                self.log('Duplicate cache result; existing record unchanged')
            if status in ('saved', 'updated') and self.on_record is not None:
                self.on_record()
        except Exception:
            # Recovery must never break game events or leak raw payloads.
            self.log('Cache result rejected')
