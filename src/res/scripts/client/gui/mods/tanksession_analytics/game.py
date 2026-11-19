# -*- coding: utf-8 -*-
"""Defensive, UNVERIFIED integration for the Lesta game client.

Only hooks own battle-result events and optional account/hangar events.
No network requests, game-mechanic patches or raw-result dumps.
The cache API is experimental and opt-in; see docs/integration.md.
"""
import json
import os
import time

import BigWorld
import BattleReplay
from PlayerEvents import g_playerEvents
from debug_utils import LOG_NOTE, LOG_ERROR

from gui.mods.tanksession_analytics.core import summarize
from gui.mods.tanksession_analytics.storage import BattleStore, PendingJournal, default_path
from gui.mods.tanksession_analytics.recorder import ResultRecorder, _verified_account
from gui.mods.tanksession_analytics.recovery import CacheRecovery

_PREFIX = '[TankSession] '
_store = None
_pending = None
_recorder = None
_recovery = None
_hangar_space = None
_initialized = False
_account_id = None
_hooks = []
_timer_ids = []
_login_generation = 0
_notices = set()


def _log(message):
    LOG_NOTE(_PREFIX + str(message))


def _error(message):
    LOG_ERROR(_PREFIX + str(message))


def _notice_once(key, message):
    """Explain a paused capability once per episode, without log flooding."""
    if key not in _notices:
        _notices.add(key)
        _log(message)


def _context():
    context = {}
    try:
        player = BigWorld.player()
        if player is None:
            # No active client entity: never reuse an old cached account.
            return context
        if _account_id is not None:
            context['account_id'] = _account_id
        account_id = getattr(player, 'databaseID', None)
        if account_id:
            context['account_id'] = account_id
        vehicle_id = getattr(player, 'playerVehicleID', None)
        if vehicle_id is not None:
            context['player_vehicle_id'] = vehicle_id
        context['team'] = getattr(player, 'team', None)
        if vehicle_id is not None:
            try:
                entity = BigWorld.entities.get(vehicle_id)
                desc = getattr(entity, 'typeDescriptor', None)
                if desc is not None:
                    context['vehicle_name'] = getattr(desc, 'name', None)
            except Exception:
                pass
    except Exception:
        _log('Player context is not accessible in this client state')
    return context


def _arena_id_from_player():
    try:
        player = BigWorld.player()
        if player is None:
            return None
        identifier = getattr(player, 'arenaUniqueID', None)
        if identifier is None:
            identifier = getattr(getattr(player, 'arena', None), 'arenaUniqueID', None)
        return identifier
    except Exception:
        return None


def _is_replay():
    try:
        playing = bool(BattleReplay.isPlaying())
        _notices.discard('replay_status')
        return playing
    except Exception:
        # Do not collect if replay status cannot be determined.
        _notice_once('replay_status',
                     'Collection paused: replay status unavailable')
        return True


def _on_avatar_ready(*args, **kwargs):
    if _pending is None or _is_replay():
        return
    arena = _arena_id_from_player()
    if arena is None:
        _log('Arena ID unavailable; cannot stage this battle')
        return
    try:
        if _pending.start(arena, _context(), int(time.time())):
            _log('Staged own battle for delayed-result recovery')
    except Exception as error:
        _error('Unable to stage battle: ' + type(error).__name__)


def _on_battle_results(is_player_vehicle, results):
    if not is_player_vehicle or _is_replay():
        return
    try:
        if _recorder is None:
            return
        status, record = _recorder.receive(results, current_context=_context(),
                                            confirmed_own=True)
        if status == 'saved':
            _log('Saved battle: ' + record.get('data_status', 'incomplete'))
        elif status == 'updated':
            _log('Updated battle: ' + record.get('data_status', 'incomplete'))
        elif status == 'conflict':
            _log('Battle result conflict: existing record kept unchanged')
        elif status == 'duplicate':
            _log('Duplicate battle result; existing record unchanged')
        elif status == 'skipped':
            _log('Skipped incomplete/ambiguous battle result')
        elif status in ('identity_missing', 'account_mismatch'):
            _log('Skipped battle due to account identity: ' + status)
    except Exception as error:
        _error('Battle capture failed: ' + type(error).__name__)


def _try_recover():
    if _recovery is None or not _initialized or _is_replay():
        return
    try:
        player = BigWorld.player()
        if player is None:
            return
        account_id = _verified_account(getattr(player, 'databaseID', None) or _account_id)
        cache = getattr(player, 'battleResultsCache', None)
        _recovery.poll(cache, account_id)
        if cache is None or not callable(getattr(cache, 'get', None)):
            _notice_once('result_cache',
                         'Optional cache recovery unavailable: result cache API missing')
        else:
            _notices.discard('result_cache')
    except Exception:
        _log('Optional cache recovery unavailable in this client state')


def _delayed_recovery(generation):
    if _initialized and generation == _login_generation:
        del _timer_ids[:]
        _try_recover()


def _cancel_recovery_timers():
    for timer in _timer_ids:
        try:
            BigWorld.cancelCallback(timer)
        except Exception:
            pass
    del _timer_ids[:]


def _on_account_become_player(*args, **kwargs):
    global _account_id, _login_generation
    # A new login event must invalidate the previous account, even if the
    # current client's databaseID is temporarily unavailable.
    _account_id = None
    _login_generation += 1
    _cancel_recovery_timers()
    try:
        player = BigWorld.player()
        identifier = getattr(player, 'databaseID', None)
        if identifier:
            _account_id = identifier
    except Exception:
        pass
    if _verified_account(_account_id) is None:
        _notice_once('account_identity', 'Account identity unavailable in current client state')
    else:
        _notices.discard('account_identity')
    if _recovery is not None:
        _recovery.reset_session(_account_id)
    _try_recover()
    if _recovery is not None:
        try:
            generation = _login_generation
            _timer_ids.append(BigWorld.callback(
                20.0, lambda current=generation: _delayed_recovery(current)))
        except Exception:
            pass


def _on_hangar_space_create(*args, **kwargs):
    _try_recover()
    try:
        from gui import SystemMessages
        if _store is None:
            return
        account = _verified_account(_context().get('account_id'))
        if account is None:
            message = u'TankSession: аккаунт ещё не определён; статистика не показана.'
        else:
            own = [record for record in _store.records
                   if isinstance(record, dict) and
                   _verified_account(record.get('account_id')) == account]
            stats = summarize(own)
            message = u'TankSession: боёв текущего аккаунта: %d' % stats['battles']
            if stats['win_rate'] is not None:
                message += u', победы: %.1f%%' % stats['win_rate']
        SystemMessages.pushMessage(
            text=message,
            type=SystemMessages.SM_TYPE.InformationHeader,
            messageData={'header': 'TankSession Analytics'})
    except Exception:
        _log('Hangar notification unavailable for this game build')


def _load_cache_opt_in():
    """Off by default; reads one small local settings file, no game assets."""
    path = os.path.join(os.path.dirname(default_path()), 'settings.json')
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 4096:
            return False
        with open(path, 'rb') as stream:
            settings = json.loads(stream.read().decode('utf-8'))
        return isinstance(settings, dict) and settings.get('experimental_cache_recovery') is True
    except (IOError, OSError, ValueError, UnicodeError):
        return False


def _attach_event(name, callback, required=False):
    try:
        getattr(g_playerEvents, name).__iadd__(callback)
        _hooks.append((name, callback))
        return True
    except Exception:
        if required:
            raise
        _log('Optional event unavailable: ' + name)
        return False


def _detach_events():
    while _hooks:
        name, callback = _hooks.pop()
        try:
            getattr(g_playerEvents, name).__isub__(callback)
        except Exception:
            pass


def init():
    global _initialized, _store, _pending, _recorder, _recovery, _hangar_space
    if _initialized:
        return
    _notices.clear()
    stage = 'locating game root'
    try:
        path = default_path()
        stage = 'reading battle journal'
        _store = BattleStore(path)
        stage = 'reading pending journal'
        _pending = PendingJournal(path + '.pending.jsonl')
        _recorder = ResultRecorder(_store, _pending, require_account=True)
        stage = 'loading local settings'
        if _load_cache_opt_in():
            _recovery = CacheRecovery(_pending, _recorder, log=_log)
            _log('EXPERIMENTAL cache recovery enabled (unverified API)')
        stage = 'subscribing required battle-result event'
        _attach_event('onBattleResultsReceived', _on_battle_results, required=True)
        _attach_event('onAvatarReady', _on_avatar_ready)
        _attach_event('onAccountBecomePlayer', _on_account_become_player)
        _initialized = True
        _log('Started; local data path: ' + _store.path)
        try:
            from helpers import dependency
            from skeletons.gui.shared.utils import IHangarSpace
            _hangar_space = dependency.instance(IHangarSpace)
            _hangar_space.onSpaceCreate += _on_hangar_space_create
        except Exception:
            _log('Hangar notification hook unavailable')
    except Exception as error:
        _error('Startup failed: %s (%s)' % (stage, type(error).__name__))
        fini()


def fini():
    global _initialized, _store, _pending, _recorder, _recovery, _hangar_space, _account_id
    global _login_generation
    _login_generation += 1
    if _recovery is not None:
        _recovery.stop()
    _cancel_recovery_timers()
    _detach_events()
    if _hangar_space is not None:
        try:
            _hangar_space.onSpaceCreate -= _on_hangar_space_create
        except Exception:
            pass
    _hangar_space = None
    _recovery = None
    _recorder = None
    _pending = None
    _store = None
    _account_id = None
    _notices.clear()
    was_initialized = _initialized
    _initialized = False
    if was_initialized:
        _log('Stopped')
