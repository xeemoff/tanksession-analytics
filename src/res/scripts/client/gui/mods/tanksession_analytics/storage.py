# -*- coding: utf-8 -*-
"""Durable, local-only append-only JSONL storage (Python 2.7 compatible)."""
import json
import os

from .core import (_arena_id, _as_text, _non_negative_int, validate_record,
                   record_is_complete, MAX_RECORD_INTEGER, long_type)
from .vehicles import (normalize_vehicle_id, revision_identity,
                       normalize_vehicle_metadata, normalize_vehicle_label,
                       VEHICLE_METADATA_FIELDS)

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
    a conflict. A separately validated, explicit additional-XP event can raise
    XP once, retaining its before/delta evidence in the append-only journal.
    Diagnostics describe physical journal lines, not write attempts.
    """
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.records = []
        self.seen = set()
        self.by_arena = {}
        self._index = {}
        self._xp_adjustments = {}
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
        self._xp_adjustments = {}
        self.diagnostics = _diagnostics()
        for raw_record in _read_jsonl(self.path, self.diagnostics):
            if raw_record.get('event') == 'additional_xp':
                status, key, merged = self._prepare_additional_xp(raw_record)
                if status == 'updated':
                    self.records[self._index[key]] = merged
                    self._xp_adjustments[key] = self._canonical_xp_event(raw_record, key)
                    self.diagnostics['revisions'] += 1
                elif status == 'duplicate':
                    self.diagnostics['duplicates'] += 1
                elif status == 'conflict':
                    self.diagnostics['conflicts'] += 1
                else:
                    self.diagnostics['invalid'] += 1
                continue
            record = validate_record(raw_record)
            if record is None:
                self.diagnostics['invalid'] += 1
                continue
            key = self._key(record)
            if key in self._index:
                position = self._index[key]
                status, merged = self._merge_observation(key, record)
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
            status, merged = self._merge_observation(key, record)
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

    def apply_additional_xp(self, account_id, arena_id, vehicle_id, expected_xp, extra_xp):
        """Persist one confirmed service bonus; never use account aggregates.

        The live adapter must observe the arena-specific offer before applying
        it and the client's successful-applied flag afterwards. This boundary
        requires an exact existing own account/arena/type and unchanged XP.
        Ordinary ``upsert`` still rejects every conflicting known metric.
        """
        event = {'schema': 1, 'event': 'additional_xp',
                 'source': 'battle_results_service',
                 'account_id': account_id, 'arena_id': arena_id,
                 'vehicle_id': vehicle_id, 'xp_before': expected_xp,
                 'xp_delta': extra_xp}
        status, key, merged = self._prepare_additional_xp(event)
        if status != 'updated':
            return status
        event = self._canonical_xp_event(event, key)
        _durable_append(self.path, event)
        self.records[self._index[key]] = merged
        self._xp_adjustments[key] = event
        self.diagnostics['lines'] += 1
        self.diagnostics['revisions'] += 1
        return status

    @staticmethod
    def _canonical_xp_event(event, key):
        return {'schema': 1, 'event': 'additional_xp',
                'source': 'battle_results_service',
                'account_id': key[0], 'arena_id': key[1],
                'vehicle_id': normalize_vehicle_id(event['vehicle_id']),
                'xp_before': _non_negative_int(event['xp_before']),
                'xp_delta': _non_negative_int(event['xp_delta'])}

    def _prepare_additional_xp(self, event):
        """Pure reducer shared by a live durable append and journal replay."""
        key = self._key(event)
        identity = normalize_vehicle_id(event.get('vehicle_id'))
        before = _non_negative_int(event.get('xp_before'))
        delta = _non_negative_int(event.get('xp_delta'))
        if (event.get('schema') != 1 or isinstance(event.get('schema'), bool) or
                not isinstance(event.get('schema'), (int, long_type)) or
                event.get('event') != 'additional_xp' or
                event.get('source') != 'battle_results_service' or key is None or
                (_non_negative_int(key[0]) or 0) <= 0 or
                isinstance(event.get('account_id'), bool) or
                identity is None or not identity.startswith('type:') or
                before is None or delta is None or delta <= 0 or
                before > MAX_RECORD_INTEGER - delta):
            return 'invalid', key, None
        old_event = self._xp_adjustments.get(key)
        if old_event is not None:
            same = (old_event['vehicle_id'] == identity and
                    old_event['xp_before'] == before and old_event['xp_delta'] == delta)
            return ('duplicate' if same else 'conflict'), key, None
        position = self._index.get(key)
        if position is None:
            return 'missing', key, None
        previous = self.records[position]
        previous_identity = previous.get('vehicle_id')
        if ((previous_identity is not None and previous_identity.startswith('type:') and
             previous_identity != identity) or
                (previous.get('xp') is not None and previous['xp'] != before)):
            return 'conflict', key, None
        if (previous_identity is None or not previous_identity.startswith('type:') or
                previous.get('xp') is None):
            return 'missing', key, None
        merged = dict(previous)
        merged['xp'] = before + delta
        if previous.get('xp_bonus') is not None:
            if previous['xp_bonus'] > MAX_RECORD_INTEGER - delta:
                return 'invalid', key, None
            merged['xp_bonus'] = previous['xp_bonus'] + delta
        checked = validate_record(merged)
        return ('updated', key, checked) if checked is not None else ('invalid', key, None)

    def _with_applied_xp(self, key, incoming):
        # The result cache may repeat the original per-battle result after the
        # explicitly observed bonus. Translate only that exact known baseline,
        # once; any other XP value remains a normal conflicting known metric.
        event = self._xp_adjustments.get(key)
        if event is None:
            return incoming
        if incoming.get('xp') is None and incoming.get('xp_bonus') is not None:
            # Without received XP this partial bonus has no pre/post-award
            # meaning. It cannot fill a missing current bonus by guessing.
            return None
        if incoming.get('xp') != event['xp_before']:
            return incoming
        if (incoming.get('xp_bonus') is not None and
                incoming['xp_bonus'] > MAX_RECORD_INTEGER - event['xp_delta']):
            return None
        result = dict(incoming)
        result['xp'] += event['xp_delta']
        if result.get('xp_bonus') is not None:
            result['xp_bonus'] += event['xp_delta']
        return result

    def _merge_observation(self, key, incoming):
        previous = self.records[self._index[key]]
        incoming = self._with_applied_xp(key, incoming)
        return ('conflict', previous) if incoming is None else self._merge(previous, incoming)

    def compacted_records(self):
        """Minimal journal lines retaining bonus provenance and stale dedup.

        An offline compactor must not discard the original XP baseline, or a
        later original cache response could become a false conflict (and the
        applied bonus would no longer be provable after restart).
        """
        rows = []
        for record in self.records:
            key = self._key(record)
            event = self._xp_adjustments.get(key)
            baseline = dict(record)
            late_bonus = False
            if event is not None:
                baseline['xp'] = event['xp_before']
                if baseline.get('xp_bonus') is not None:
                    if baseline['xp_bonus'] < event['xp_delta']:
                        # The first result may have total XP below base XP
                        # (penalties), leaving bonus unknown. A later positive
                        # post-bonus value need not have a nonnegative inverse.
                        baseline['xp_bonus'] = None
                        late_bonus = True
                    else:
                        baseline['xp_bonus'] -= event['xp_delta']
            rows.append(baseline)
            if event is not None:
                rows.append(dict(event))
                if late_bonus:
                    rows.append(dict(record))
        return rows

    @staticmethod
    def _merge(previous, incoming):
        merged = dict(previous)
        changed = False
        try:
            vehicle_id, labels_linked = revision_identity(previous, incoming)
        except ValueError:
            return 'conflict', previous
        if vehicle_id is not None and vehicle_id != previous.get('vehicle_id'):
            merged['vehicle_id'] = vehicle_id
            changed = True
        for name in ('vehicle', 'mode', 'outcome', 'damage', 'xp',
                     'assistance_radio', 'assistance_track', 'map', 'kills',
                     'survived', 'shots', 'direct_hits', 'penetrations',
                     'xp_base', 'xp_bonus', 'credits_gross', 'credits_net',
                     'map_label', 'vehicle_label', 'vehicle_tier', 'vehicle_class', 'vehicle_nation'):
            old, new = previous.get(name), incoming.get(name)
            old_missing = old is None or old == 'unknown'
            new_missing = new is None or new == 'unknown'
            if new_missing:
                continue
            if old_missing:
                merged[name] = new
                changed = True
            elif old != new:
                if name in ('vehicle', 'vehicle_label') and labels_linked:
                    # A type identity can survive localization/renaming. Keep
                    # the first display label and every known numeric value.
                    continue
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
        vehicle_id = normalize_vehicle_id(context.get('vehicle_id'))
        if vehicle_id is not None:
            safe['vehicle_id'] = vehicle_id
            metadata = normalize_vehicle_metadata(context, vehicle_id)
            for name in VEHICLE_METADATA_FIELDS:
                if metadata[name] is not None:
                    safe[name] = metadata[name]
            label = normalize_vehicle_label(context.get('vehicle_label'))
            if label is not None:
                safe['vehicle_label'] = label
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
