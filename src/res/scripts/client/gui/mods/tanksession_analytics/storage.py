# -*- coding: utf-8 -*-
"""Durable, local-only append-only JSONL storage (Python 2.7 compatible)."""
import json
import os

from .core import _arena_id, _as_text, _non_negative_int, validate_record, record_is_complete

_MAX_LINE_BYTES = 262144


def _diagnostics():
    return dict((name, 0) for name in ('lines', 'malformed', 'invalid',
                                     'valid_unique', 'duplicates', 'revisions', 'conflicts'))


def _increment(diagnostics, name):
    if diagnostics is not None:
        diagnostics[name] += 1


def discover_game_root(cwd=None, app_directory=None):
    """Find a verified game root; never write to an unrelated working folder.

    The game commonly starts from its root. Some launchers run its executable
    from win32/win64, so ResMgr.appDirectory() is an additional candidate.
    A paths.xml marker is required; no arbitrary CWD fallback is accepted.
    """
    candidates = [os.path.abspath(cwd if cwd is not None else os.getcwd())]
    if app_directory:
        candidate = os.path.abspath(app_directory)
        if os.path.isfile(candidate):
            candidate = os.path.dirname(candidate)
        candidates.append(candidate)
        if os.path.basename(candidate).lower() in ('win32', 'win64'):
            candidates.append(os.path.dirname(candidate))
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, 'paths.xml')):
            return candidate
    raise IOError('Unable to locate game root (paths.xml missing)')


def default_path(game_root=None):
    if game_root is None:
        try:
            import ResMgr
            app_directory = ResMgr.appDirectory()
        except (ImportError, AttributeError, RuntimeError):
            app_directory = None
        game_root = discover_game_root(app_directory=app_directory)
    return os.path.join(os.path.abspath(game_root), 'mods', 'configs',
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


def _read_jsonl(path, diagnostics=None):
    if not os.path.isfile(path):
        return
    with open(path, 'rb') as stream:
        while True:
            # Bound memory even for a damaged file with an enormous last line.
            raw_line = stream.readline(_MAX_LINE_BYTES + 1)
            if not raw_line:
                break
            _increment(diagnostics, 'lines')
            if len(raw_line) > _MAX_LINE_BYTES:
                while raw_line and not raw_line.endswith(b'\n'):
                    raw_line = stream.readline(_MAX_LINE_BYTES + 1)
                _increment(diagnostics, 'malformed')
                continue
            try:
                item = json.loads(raw_line.decode('utf-8'))
            except (UnicodeDecodeError, ValueError, TypeError, RuntimeError):
                _increment(diagnostics, 'malformed')
                continue
            if isinstance(item, dict):
                yield item
            else:
                _increment(diagnostics, 'malformed')


class BattleStore(object):
    """One logical battle per key, with append-only, fill-missing revisions.

    A later snapshot may fill missing values, never change a known metric.
    Any conflicting known field rejects the whole proposed revision. The first
    observation timestamp is retained; receiving the same result later is not
    a conflict. Diagnostics describe physical journal lines, not write attempts.
    """
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.records = []
        self.seen = set()
        self.by_arena = {}
        self._index = {}
        self.diagnostics = _diagnostics()
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
        self._index = {}
        self.diagnostics = _diagnostics()
        for raw_record in _read_jsonl(self.path, self.diagnostics):
            record = validate_record(raw_record)
            if record is None:
                self.diagnostics['invalid'] += 1
                continue
            key = self._key(record)
            if key in self._index:
                position = self._index[key]
                status, merged = self._merge(self.records[position], record)
                if status == 'updated':
                    self.records[position] = merged
                    self.diagnostics['revisions'] += 1
                elif status == 'conflict':
                    self.diagnostics['conflicts'] += 1
                else:
                    self.diagnostics['duplicates'] += 1
                continue
            if self._already_seen(key):
                # Legacy local records suppress duplicates, but are never
                # enriched from an account whose identity cannot be proved.
                self.diagnostics['duplicates'] += 1
                continue
            self._index[key] = len(self.records)
            self.records.append(record)
            self._remember(key)
        self.diagnostics['valid_unique'] = len(self.records)

    def append(self, record):
        """Legacy API: True only for a newly added battle; no enrichment."""
        record = validate_record(record)
        if record is None:
            raise ValueError('Invalid battle record')
        key = self._key(record)
        if self._already_seen(key):
            return False
        return self.upsert(record) == 'saved'

    def upsert(self, record):
        """Durably save/fill missing data; return a status without double-counting."""
        record = validate_record(record)
        if record is None:
            raise ValueError('Invalid battle record')
        key = self._key(record)
        if key in self._index:
            position = self._index[key]
            status, merged = self._merge(self.records[position], record)
            if status != 'updated':
                return status
            _durable_append(self.path, merged)
            self.records[position] = merged
            self.diagnostics['lines'] += 1
            self.diagnostics['revisions'] += 1
            return status
        if self._already_seen(key):
            return 'duplicate'
        _durable_append(self.path, record)
        self._index[key] = len(self.records)
        self.records.append(record)
        self._remember(key)
        self.diagnostics['lines'] += 1
        self.diagnostics['valid_unique'] += 1
        return 'saved'

    def get_record(self, record):
        """Copy the exact account+arena snapshot; legacy aliases return None."""
        key = self._key(record)
        position = self._index.get(key)
        return dict(self.records[position]) if position is not None else None

    @staticmethod
    def _merge(previous, incoming):
        merged = dict(previous)
        changed = False
        for name in ('vehicle', 'mode', 'outcome', 'damage', 'xp',
                     'assistance_radio', 'assistance_track'):
            old, new = previous.get(name), incoming.get(name)
            old_missing = old is None or old == 'unknown'
            new_missing = new is None or new == 'unknown'
            if new_missing:
                continue
            if old_missing:
                merged[name] = new
                changed = True
            elif old != new:
                return 'conflict', previous
        if previous.get('timestamp') is None and incoming.get('timestamp') is not None:
            merged['timestamp'] = incoming['timestamp']
            changed = True
        merged['data_status'] = 'complete' if record_is_complete(merged) else 'incomplete'
        return ('updated', merged) if changed else ('duplicate', previous)

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
