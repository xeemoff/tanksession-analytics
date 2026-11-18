# -*- coding: utf-8 -*-
"""Durable, local-only append-only JSONL storage (Python 2.7 compatible)."""
import json
import os

from .core import _arena_id, _as_text, _non_negative_int


def default_path():
    return os.path.join(os.getcwd(), 'mods', 'configs',
                        'tanksession_analytics', 'battles.jsonl')


def _durable_append(path, item):
    """Write one JSON object; separate it from an interrupted last line.

    A flush and fsync happen BEFORE in-memory state is advanced. We do not
    claim transactional consistency for multiple processes writing at once.
    """
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError:
            if not os.path.isdir(folder):
                raise
    line = (json.dumps(item, ensure_ascii=False, sort_keys=True,
                       allow_nan=False) + '\n').encode('utf-8')
    with open(path, 'ab+') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() > 0:
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b'\n':
                stream.write(b'\n')
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def _read_jsonl(path):
    if not os.path.isfile(path):
        return
    with open(path, 'rb') as stream:
        for raw_line in stream:
            if len(raw_line) > 262144:  # corrupted/hostile lines need not load
                continue
            try:
                item = json.loads(raw_line.decode('utf-8'))
            except (UnicodeDecodeError, ValueError, TypeError):
                continue
            if isinstance(item, dict):
                yield item


class BattleStore(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.records = []
        self.seen = set()
        self.by_arena = {}
        self.reload()

    @staticmethod
    def _key(record):
        if not isinstance(record, dict):
            return None
        arena = _arena_id(record.get('arena_id'))
        if arena is None:
            return None
        account = _as_text(record.get('account_id') or 'local').strip()
        if not account:
            account = 'local'
        return account, arena

    def reload(self):
        self.records = []
        self.seen = set()
        self.by_arena = {}
        for record in _read_jsonl(self.path):
            key = self._key(record)
            if key is None or self._already_seen(key):
                continue
            self.records.append(record)
            self._remember(key)

    def append(self, record):
        key = self._key(record)
        if key is None:
            raise ValueError('A battle needs a valid arena_id')
        if self._already_seen(key):
            return False
        _durable_append(self.path, record)
        self.records.append(record)
        self._remember(key)
        return True

    def _already_seen(self, key):
        account, arena = key
        accounts = self.by_arena.get(arena, set())
        # A legacy event with unknown account must not create a second entry
        # for the same arena. Known, distinct accounts remain separate.
        return key in self.seen or ('local' in accounts) or (account == 'local' and bool(accounts))

    def _remember(self, key):
        self.seen.add(key)
        self.by_arena.setdefault(key[1], set()).add(key[0])


class PendingJournal(object):
    """Crash-recoverable START/DONE log for battles seen in the client.

    Only limited *own* battle context is saved; no raw results or other users'
    data. No access to the game API and no polling in this class.
    """
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.pending = {}
        self.reload()

    def reload(self):
        self.pending = {}
        for item in _read_jsonl(self.path):
            arena = _arena_id(item.get('arena_id'))
            if arena is None:
                continue
            if item.get('event') == 'start' and isinstance(item.get('context'), dict):
                self.pending[arena] = item
            elif item.get('event') == 'done':
                self.pending.pop(arena, None)

    def start(self, arena_id, context, timestamp):
        arena = _arena_id(arena_id)
        if arena is None:
            return False
        if arena in self.pending:
            return False
        context = context if isinstance(context, dict) else {}
        safe = {}
        for name in ('account_id', 'player_vehicle_id', 'vehicle_name', 'team'):
            value = context.get(name)
            if value is not None:
                safe[name] = _as_text(value)
        item = {'event': 'start', 'arena_id': arena, 'timestamp': int(timestamp),
                'context': safe}
        _durable_append(self.path, item)
        self.pending[arena] = item
        return True

    def finish(self, arena_id):
        arena = _arena_id(arena_id)
        if arena not in self.pending:
            return False
        _durable_append(self.path, {'event': 'done', 'arena_id': arena})
        self.pending.pop(arena, None)
        return True

    def context(self, arena_id):
        item = self.pending.get(_arena_id(arena_id))
        return dict(item.get('context', {})) if item else {}

    def eligible(self, account_id=None, now=None, max_age=7 * 86400, limit=32):
        """Return recent, own-account battles in stable order.

        When account identity is unknown, recovery is disabled to avoid
        reading another account's cached result by accident.
        """
        if account_id is None:
            return []
        account = _as_text(account_id)
        entries = []
        for item in self.pending.values():
            recorded = item.get('context', {}).get('account_id')
            if recorded is None or _as_text(recorded) != account:
                continue
            stamp = _non_negative_int(item.get('timestamp'))
            if stamp is None:
                continue
            if now is not None and (stamp > now + 300 or stamp < now - max_age):
                continue
            entries.append(item)
        entries.sort(key=lambda x: (_non_negative_int(x.get('timestamp')), x['arena_id']))
        return entries[-limit:]
