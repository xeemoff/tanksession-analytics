# -*- coding: utf-8 -*-
"""The game-event / cache-result seam, testable without running the client."""
from .core import _arena_id, _get_first, normalize_result


class ResultRecorder(object):
    def __init__(self, store, pending=None):
        self.store = store
        self.pending = pending

    def receive(self, payload, current_context=None, observed_at=None,
                expected_arena=None, confirmed_own=False):
        """Return ('saved'|'duplicate'|'skipped'|'mismatch', record-or-None).

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
        if self.pending is not None:
            # The snapshot taken *inside* the battle is more authoritative
            # than whatever player entity exists later in the garage.
            context.update(self.pending.context(arena))
        if confirmed_own:
            context['confirmed_own_result'] = True
        result = normalize_result(payload, context=context, observed_at=observed_at)
        if result is None:
            return 'skipped', None
        status = 'saved' if self.store.append(result) else 'duplicate'
        if self.pending is not None:
            self.pending.finish(result['arena_id'])
        return status, result
