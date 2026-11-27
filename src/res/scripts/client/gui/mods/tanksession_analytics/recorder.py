# -*- coding: utf-8 -*-
"""The game-event / cache-result seam, testable without running the client."""
from .core import (_arena_id, _as_text, _get_first, normalize_result,
                   record_is_complete, validate_record)


def _verified_account(value):
    if value is None or isinstance(value, bool):
        return None
    account = _as_text(value).strip()
    return account if account and account not in ('0', 'local', 'unknown') else None


class ResultRecorder(object):
    def __init__(self, store, pending=None, require_account=False, metadata_provider=None):
        self.store = store
        self.pending = pending
        # Test/offline records may use 'local'; the live game adapter must not.
        self.require_account = require_account
        self.metadata_provider = metadata_provider

    def receive(self, payload, current_context=None, observed_at=None,
                expected_arena=None, confirmed_own=False):
        """Return (status, record-or-None); identity errors fail closed in live mode.

        All sources (event and opt-in cache) use this same deduplication path.
        For cache recovery the expected arena ID must match the returned ID.
        """
        if not isinstance(payload, dict):
            return 'skipped', None
        arena = _arena_id(_get_first(payload, ('arenaUniqueID', 'arenaId')))
        if arena is None:
            arena = _arena_id(_get_first(payload.get('common'), ('arenaUniqueID', 'arenaId')))
        if expected_arena is not None and arena != _arena_id(expected_arena):
            return 'mismatch', None

        context = dict(current_context) if isinstance(current_context, dict) else {}
        saved = self.pending.context(arena) if self.pending is not None else {}
        current_account = _verified_account(context.get('account_id'))
        saved_account = _verified_account(saved.get('account_id'))
        # Never attach a late result to a new, different signed-in account.
        # Keep the pending entry for diagnosis/recovery on the correct account.
        if current_account and saved_account and current_account != saved_account:
            return 'account_mismatch', None
        # A battle-start snapshot is more authoritative after return to garage.
        context.update(saved)
        if self.require_account and not _verified_account(context.get('account_id')):
            return 'identity_missing', None
        if confirmed_own:
            context['confirmed_own_result'] = True
        result = normalize_result(payload, context=context, observed_at=observed_at)
        if result is None:
            return 'skipped', None
        if self.metadata_provider is not None:
            # Catalog enrichment is optional and reads only the already
            # identified own record. Its failure cannot discard a battle.
            try:
                additions = self.metadata_provider(dict(result))
                if isinstance(additions, dict):
                    enriched = dict(result)
                    for name in ('map_label', 'vehicle_tier', 'vehicle_class', 'vehicle_nation'):
                        if enriched.get(name) is None and additions.get(name) is not None:
                            enriched[name] = additions[name]
                    checked = validate_record(enriched)
                    if checked is not None:
                        result = checked
            except Exception:
                pass
        status = self.store.upsert(result)
        # Return what is actually persisted, including fields from an earlier
        # partial result. A legacy local-vs-known duplicate has no exact-account
        # snapshot and must not complete another account's pending entry.
        stored = self.store.get_record(result)
        if (self.pending is not None and status != 'conflict' and
                record_is_complete(stored)):
            self.pending.finish(stored['arena_id'])
        return status, stored
