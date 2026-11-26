# -*- coding: utf-8 -*-
"""Account-scoped UI preferences, goals and explicit local exports.

Python 2.7 compatible. The UI never supplies an account ID or a filesystem
path. The game host verifies the current account before calling this service.
Only configuration is replaced; battle and pending journals are never edited.
"""
from __future__ import division
import hashlib
import json
import os
import tempfile
import time

from .core import _as_text, long_type
from .goals import validate_goals
from .recorder import _verified_account

MAX_PROFILE_BYTES = 65536
MAX_EXPORT_ROWS = 100000
MAX_PROFILES = 64
TABS = ('progress', 'dynamics', 'history', 'summary', 'settings')
MUTATIONS = ('save_preferences', 'save_goal', 'delete_goal', 'export_csv')
ACTIONS = ('initialize',) + MUTATIONS
DEFAULT_PREFERENCES = {'vehicle': '', 'window': 10, 'tab': 'progress',
                       'density': 'normal', 'contrast': 'standard'}
EXPORT_FIELDS = ('timestamp', 'vehicle', 'mode', 'map', 'outcome', 'damage', 'xp',
                 'xp_base', 'kills', 'survived', 'shots', 'direct_hits',
                 'penetrations', 'assistance_radio', 'assistance_track',
                 'credits_gross', 'credits_net')
try:
    _text_types = (str, unicode)
except NameError:
    _text_types = (str,)


def validate_preferences(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PREFERENCES):
        raise ValueError('Unsupported preferences')
    result = dict(value)
    vehicle = value['vehicle']
    if (not isinstance(vehicle, _text_types) or len(vehicle) > 128 or
            any(ord(char) < 32 for char in vehicle)):
        raise ValueError('Invalid preference vehicle')
    vehicle.encode('utf-8')
    if (isinstance(value['window'], bool) or
            not isinstance(value['window'], (int, long_type)) or
            value['window'] not in (10, 30, 100)):
        raise ValueError('Invalid preference window')
    if (value['tab'] not in TABS or value['density'] not in ('normal', 'compact')
            or value['contrast'] not in ('standard', 'high')):
        raise ValueError('Invalid preference choice')
    return result


def validate_command(request, clean):
    """Add tightly typed optional commands to a validated snapshot request."""
    if 'page' in request:
        page = request['page']
        if (isinstance(page, bool) or not isinstance(page, (int, long_type)) or
                not 0 <= page <= 1000000):
            raise ValueError('Invalid history page')
        clean['page'] = page
    action = request.get('action')
    if action is not None:
        if not isinstance(action, _text_types) or action not in ACTIONS:
            raise ValueError('Unsupported action')
        clean['action'] = action
    if 'preferences' in request:
        if action != 'save_preferences':
            raise ValueError('Unexpected preferences')
        clean['preferences'] = validate_preferences(request['preferences'])
    elif action == 'save_preferences':
        raise ValueError('Missing preferences')
    if 'goal' in request:
        if action not in ('save_goal', 'delete_goal'):
            raise ValueError('Unexpected goal')
        goal = request['goal']
        expected = {'vehicle', 'window'}
        if action == 'save_goal':
            expected.add('target_avg_damage')
        if not isinstance(goal, dict) or set(goal) != expected:
            raise ValueError('Unsupported goal fields')
        # Public command numbers must be integral JSON numbers, not strings.
        for key in expected - {'vehicle'}:
            if isinstance(goal[key], bool) or not isinstance(goal[key], (int, long_type)):
                raise ValueError('Invalid goal number')
        tested = dict(goal)
        if action == 'delete_goal':
            tested['target_avg_damage'] = 1
        normalized = validate_goals([tested])[0]
        normalized['vehicle'].encode('utf-8')
        if any(ord(char) < 32 for char in normalized['vehicle']):
            raise ValueError('Invalid goal vehicle')
        clean['goal'] = dict((key, normalized[key]) for key in expected)
    elif action in ('save_goal', 'delete_goal'):
        raise ValueError('Missing goal')
    return clean


def _replace(source, destination):
    """Atomic replacement on POSIX and on Windows, including Python 2.7."""
    if hasattr(os, 'replace'):
        os.replace(source, destination)
    elif os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        move = ctypes.windll.kernel32.MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        if not move(_as_text(source), _as_text(destination), 0x1 | 0x8):
            raise ctypes.WinError()
    else:
        os.rename(source, destination)


def _mkdir(path):
    if os.path.islink(path):
        raise IOError('Linked directory is not supported')
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            if not os.path.isdir(path):
                raise


def _write_atomic(path, raw):
    folder = os.path.dirname(path)
    _mkdir(folder)
    if os.path.islink(path):
        raise IOError('Linked configuration is not supported')
    descriptor, temporary = tempfile.mkstemp(prefix='.tsa-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _csv_cell(value):
    if value is None:
        text = ''
    elif isinstance(value, bool):
        text = '1' if value else '0'
    else:
        text = _as_text(value)
        if isinstance(value, _text_types):
            # Spreadsheet applications can interpret a quoted field as a
            # formula too. Names/labels are data, never executable expressions.
            if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                text = "'" + text
    return '"' + text.replace('"', '""') + '"'


class Workspace(object):
    def __init__(self, folder, memory=False):
        self.folder = os.path.abspath(folder)
        self.memory = memory
        self._profiles = {}
        self._completed = {}

    def _key(self, account):
        return hashlib.sha256(_as_text(account).encode('utf-8')).hexdigest()

    def _path(self, account):
        return os.path.join(self.folder, 'profiles', self._key(account) + '.json')

    @staticmethod
    def _validate_profile(profile):
        if (not isinstance(profile, dict) or set(profile) != {'version', 'preferences', 'goals'}
                or isinstance(profile['version'], bool) or profile['version'] != 1):
            raise ValueError('Invalid UI profile')
        preferences = validate_preferences(profile['preferences'])
        goals = profile['goals']
        if goals is not None:
            goals = validate_goals(goals)
            if any('account_id' in goal for goal in goals):
                raise ValueError('Unexpected profile account selector')
        return {'version': 1, 'preferences': preferences, 'goals': goals}

    def _load(self, account):
        key = self._key(account)
        if self.memory:
            return self._validate_profile(self._profiles.get(key, {
                'version': 1, 'preferences': dict(DEFAULT_PREFERENCES), 'goals': None}))
        path = self._path(account)
        if os.path.islink(os.path.dirname(path)) or os.path.islink(path):
            raise IOError('Linked UI profile is not supported')
        if not os.path.exists(path):
            return {'version': 1, 'preferences': dict(DEFAULT_PREFERENCES), 'goals': None}
        with open(path, 'rb') as stream:
            data = stream.read(MAX_PROFILE_BYTES + 1)
        if len(data) > MAX_PROFILE_BYTES:
            raise ValueError('UI profile is too large')
        return self._validate_profile(json.loads(data.decode('utf-8-sig')))

    def _save(self, account, profile):
        clean = self._validate_profile(profile)
        if self.memory:
            self._profiles[self._key(account)] = clean
            return
        path = self._path(account)
        folder = os.path.dirname(path)
        _mkdir(folder)
        if not os.path.exists(path) and len([name for name in os.listdir(folder)
                                           if name.endswith('.json')]) >= MAX_PROFILES:
            raise ValueError('too_many_profiles')
        raw = (json.dumps(clean, ensure_ascii=False, sort_keys=True,
                          allow_nan=False) + '\n').encode('utf-8')
        if len(raw) > MAX_PROFILE_BYTES:
            raise ValueError('UI profile is too large')
        if os.path.isfile(path):
            with open(path, 'rb') as stream:
                previous = stream.read(MAX_PROFILE_BYTES + 1)
            if len(previous) > MAX_PROFILE_BYTES:
                raise ValueError('UI profile is too large')
            _write_atomic(path + '.bak', previous)
        _write_atomic(path, raw)

    @staticmethod
    def _visible_goals(goals, account):
        return [dict((name, goal[name]) for name in ('vehicle', 'window', 'target_avg_damage'))
                for goal in validate_goals(goals or [])
                if 'account_id' not in goal or _verified_account(goal['account_id']) == account]

    def _export(self, records, account, vehicle, observed):
        from .analytics import sort_records
        from .presentation import clean_own_records
        clean, unused = clean_own_records(records, account)
        rows = [row for row in sort_records(clean) if not vehicle or row['vehicle'] == vehicle]
        if not rows:
            return {'status': 'error', 'code': 'no_data'}
        if len(rows) > MAX_EXPORT_ROWS:
            return {'status': 'error', 'code': 'export_too_large'}
        folder = os.path.join(self.folder, 'exports')
        _mkdir(folder)
        # An OS-generated unique suffix prevents replacement of an earlier
        # export made in the same second, even after a process restart.
        descriptor, path = tempfile.mkstemp(prefix='tanksession-' +
                    time.strftime('%Y%m%d-%H%M%S', time.gmtime(observed)) + '-',
                    suffix='.csv', dir=folder)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(b'\xef\xbb\xbf')
                stream.write((';'.join(EXPORT_FIELDS) + '\r\n').encode('utf-8'))
                for row in rows:
                    stream.write((';'.join(_csv_cell(row.get(name)) for name in EXPORT_FIELDS)
                                  + '\r\n').encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return {'status': 'exported', 'code': 'csv_exported',
                'filename': os.path.basename(path), 'rows': len(rows)}

    def snapshot(self, records, account, request, legacy_goals=None, diagnostics=None,
                 source='game', now=None, pending_count=None):
        from .presentation import build_snapshot, validate_request, _confirmed_account, _observed_time
        account = _confirmed_account(account)
        request = validate_request(request)
        observed = _observed_time(now)
        if account is None:
            return build_snapshot([], None, request, source=source, now=observed)
        operation = None
        writable = True
        try:
            profile = self._load(account)
        except (ValueError, IOError, OSError, UnicodeError, TypeError):
            profile = {'version': 1, 'preferences': dict(DEFAULT_PREFERENCES), 'goals': None}
            operation = {'status': 'error', 'code': 'read_failed'}
            writable = False
        if profile['goals'] is None:
            try:
                legacy = legacy_goals() if callable(legacy_goals) else legacy_goals
                goals = self._visible_goals(legacy, account)
            except (ValueError, IOError, OSError, UnicodeError, TypeError):
                goals = []
                operation = {'status': 'error', 'code': 'read_failed'}
                writable = False
        else:
            goals = profile['goals']
        action = request.get('action')
        if action == 'initialize' or (action is None and request['request_id'] == 'initial'):
            request['vehicle'] = profile['preferences']['vehicle']
            request['window'] = profile['preferences']['window']
            if 'page' in request:
                request['page'] = 0
            self._completed.pop(self._key(account), None)
        if action in MUTATIONS and writable:
            completed = self._completed.setdefault(self._key(account), {})
            fingerprint = request['request_id'] + ':' + json.dumps(request, sort_keys=True)
            operation = completed.get(fingerprint)
            if operation is None:
                try:
                    if action == 'export_csv':
                        operation = self._export(records, account, request['vehicle'], observed)
                    else:
                        updated = dict(profile)
                        if action == 'save_preferences':
                            updated['preferences'] = dict(request['preferences'])
                            operation = {'status': 'saved', 'code': 'preferences_saved'}
                        else:
                            target = request['goal']
                            new_goals = [goal for goal in goals
                                         if (goal['vehicle'], goal['window']) !=
                                         (target['vehicle'], target['window'])]
                            if action == 'save_goal':
                                new_goals.append(dict(target))
                            updated['goals'] = validate_goals(new_goals)
                            operation = {'status': 'saved' if action == 'save_goal' else 'deleted',
                                         'code': 'goal_saved' if action == 'save_goal' else 'goal_deleted'}
                        self._save(account, updated)
                        profile = updated
                        goals = goals if profile['goals'] is None else profile['goals']
                except (IOError, OSError, UnicodeError):
                    operation = {'status': 'error', 'code': 'write_failed'}
                except (ValueError, TypeError):
                    operation = {'status': 'error', 'code': 'invalid_goal' if 'goal' in request else 'write_failed'}
                if len(completed) >= 32:
                    completed.clear()
                completed[fingerprint] = operation
        snapshot = build_snapshot(records, account, request=request, goals=goals,
                                  diagnostics=diagnostics, source=source, now=observed,
                                  pending_count=pending_count)
        snapshot['workspace'] = {'version': 1, 'can_edit': writable,
                                 'preferences': dict(profile['preferences']),
                                 'goals': goals, 'operation': operation}
        return snapshot
