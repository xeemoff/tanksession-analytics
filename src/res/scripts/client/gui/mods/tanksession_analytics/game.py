# -*- coding: utf-8 -*-
"""Defensive, UNVERIFIED integration for the Lesta game client.

Only hooks own battle-result events and optional account/hangar events.
No network requests, game-mechanic patches or raw-result dumps.
The cache and Gameface APIs are experimental and opt-in; see docs/integration.md.
"""
import json
import os
import time

import BigWorld
import BattleReplay
from PlayerEvents import g_playerEvents
from debug_utils import LOG_NOTE, LOG_ERROR

from gui.mods.tanksession_analytics.core import summarize, result_rejection_reason
from gui.mods.tanksession_analytics.storage import BattleStore, PendingJournal, default_path
from gui.mods.tanksession_analytics.recorder import ResultRecorder, _verified_account
from gui.mods.tanksession_analytics.recovery import CacheRecovery
from gui.mods.tanksession_analytics.vehicles import (identity_from_internal_name,
                                                   identity_from_type_descr,
                                                   metadata_from_vehicle_type)

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
_recovery_timer_token = None
_login_generation = 0
_notices = set()
_gameface = None
_ui_workspace = None
_in_hangar = False
_result_service_event = None


def _log(message):
    LOG_NOTE(_PREFIX + str(message))


def _error(message):
    LOG_ERROR(_PREFIX + str(message))


def _notice_once(key, message):
    """Explain a paused capability once per episode, without log flooding."""
    if key not in _notices:
        _notices.add(key)
        _log(message)


def _live_account_identity(player):
    """Return (verified account ID, conflict), never a temporary entity ID.

    Alternate client accessors are probes: availability in a particular
    Mir Tankov release must be established by an actual in-game test.
    """
    if player is None:
        return None, False
    candidates = []
    try:
        direct = _verified_account(getattr(player, 'databaseID', None))
        if direct is not None:
            candidates.append(direct)
    except Exception:
        pass
    try:
        from gui.shared.utils import getPlayerDatabaseID
        helper = _verified_account(getPlayerDatabaseID())
        if helper is not None:
            candidates.append(helper)
    except Exception:
        pass
    if not candidates:
        try:
            from helpers import dependency
            from skeletons.gui.shared import IItemsCache
            dossier = dependency.instance(IItemsCache).items.getAccountDossier()
            fallback = _verified_account(dossier.getPlayerDBID())
            if fallback is not None:
                candidates.append(fallback)
        except Exception:
            pass
    if len(set(candidates)) > 1:
        _notice_once('account_conflict',
                     'Account identity sources disagree; collection paused')
        return None, True
    return (candidates[0] if candidates else None), False


def _context():
    context = {}
    try:
        player = BigWorld.player()
        if player is None:
            # No active client entity: never reuse an old cached account.
            return context
        live, conflict = _live_account_identity(player)
        cached = _verified_account(_account_id)
        if not conflict and live is not None and cached is not None and live != cached:
            _notice_once('account_conflict',
                         'Account identity changed unexpectedly; collection paused')
            conflict = True
        if not conflict:
            account = live or cached
            if account is not None:
                context['account_id'] = account
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
                    vehicle_type = getattr(desc, 'type', None)
                    context['vehicle_id'] = (identity_from_type_descr(
                        getattr(vehicle_type, 'compactDescr', None)) or
                        identity_from_internal_name(context['vehicle_name']))
                    metadata = metadata_from_vehicle_type(vehicle_type)
                    if metadata.get('vehicle_id') == context.get('vehicle_id'):
                        context.update(metadata)
            except Exception:
                pass
    except Exception:
        _log('Player context is not accessible in this client state')
    return context


def _result_metadata(record):
    """Optional local catalog reads for the own result, never guessed tables.

    ArenaType.g_cache is keyed by the full gameplay+geometry arena type ID.
    Its name is already localized by the client. VehicleType is resolved by
    its immutable type descriptor; no live hangar selection is consulted.
    """
    metadata = {}
    identity = record.get('vehicle_id')
    if identity and identity.startswith('type:'):
        try:
            from items import vehicles
            values = metadata_from_vehicle_type(vehicles.getVehicleType(int(identity[5:])))
            if values.get('vehicle_id') == identity:
                metadata.update(values)
        except Exception:
            pass
    map_id = record.get('map')
    if map_id and map_id.startswith('arena:'):
        try:
            import ArenaType
            arena_id = int(map_id[6:])
            arena = ArenaType.g_cache.get(arena_id)
            if arena is not None and getattr(arena, 'id', None) == arena_id:
                label = getattr(arena, 'name', None)
                if isinstance(label, bytes):
                    label = label.decode('utf-8')
                if (label and len(label) <= 128 and
                        not any(ord(char) < 32 or ord(char) == 127 for char in label)):
                    metadata['map_label'] = label
        except Exception:
            pass
    return metadata


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
    _leave_hangar()
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
            reason = result_rejection_reason(results, dict(_context(),
                                                            confirmed_own_result=True))
            _log('Skipped incomplete/ambiguous battle result: ' + reason)
        elif status in ('identity_missing', 'account_mismatch'):
            _log('Skipped battle due to account identity: ' + status)
        if status in ('saved', 'updated') and _gameface is not None:
            _gameface.refresh()
    except Exception as error:
        _error('Battle capture failed: ' + type(error).__name__)


def _recovery_account():
    # Never query the cache on an Avatar or with only a stale login ID.
    if not _initialized or _is_replay():
        return None
    player = BigWorld.player()
    if (player is None or getattr(player, 'arenaUniqueID', None) not in (None, 0)
            or getattr(player, 'arena', None) is not None):
        return None
    account, conflict = _live_account_identity(player)
    if conflict or account is None:
        return None
    cached = _verified_account(_account_id)
    return account if cached in (None, account) else None


def _refresh_recovered():
    if _gameface is not None:
        _gameface.refresh()


def _on_result_posted(reusable, *args, **kwargs):
    """A lobby result is ready; only query a previously staged own battle."""
    if _recovery is None:
        return
    try:
        account = _recovery_account()
        arena = getattr(reusable, 'arenaUniqueID', None)
        avatar = getattr(getattr(reusable, 'personal', None), 'avatar', None)
        if (account is None or arena is None or
                _verified_account(getattr(avatar, 'accountDBID', None)) != account):
            return
        if _verified_account(_pending.context(arena).get('account_id')) != account:
            return
        _log('Own pending result posted in lobby')
        _try_recover(arena_id=arena, posted=True)
        _schedule_recovery_checks()
    except Exception:
        _notice_once('result_posted', 'Lobby result hook unavailable in this client state')


def _attach_result_service():
    global _result_service_event
    if _recovery is None or _result_service_event is not None:
        return
    try:
        from helpers import dependency
        from skeletons.gui.battle_results import IBattleResultsService
        service = dependency.instance(IBattleResultsService)
        event = service.onResultPosted
        event += _on_result_posted
        _result_service_event = event
        _log('Lobby result hook attached')
    except Exception:
        _notice_once('result_service', 'Optional lobby result hook unavailable')


def _try_recover(arena_id=None, posted=False):
    if _recovery is None or not _initialized or _is_replay():
        return
    try:
        account_id = _recovery_account()
        if account_id is None:
            return
        player = BigWorld.player()
        cache = getattr(player, 'battleResultsCache', None)
        _recovery.poll(cache, account_id, arena_id=arena_id, posted=posted)
        if cache is None or not callable(getattr(cache, 'get', None)):
            _notice_once('result_cache',
                         'Optional cache recovery unavailable: result cache API missing')
        else:
            _notices.discard('result_cache')
    except Exception:
        _log('Optional cache recovery unavailable in this client state')


def _delayed_recovery(generation, token, remaining):
    global _recovery_timer_token
    if (_initialized and generation == _login_generation and
            token is _recovery_timer_token):
        del _timer_ids[:]
        _recovery_timer_token = None
        _try_recover()
        # Four checks per login/hangar/ready episode, never an endless loop.
        # This also releases a serialized queue after a lost callback timeout.
        try:
            account = _recovery_account()
            if (remaining > 1 and account is not None and _pending is not None and
                    _pending.eligible(account, now=time.time())):
                _schedule_recovery_checks(remaining - 1)
        except Exception:
            pass


def _schedule_recovery_checks(remaining=4):
    global _recovery_timer_token
    if (_recovery is None or not _initialized or _timer_ids or remaining <= 0):
        return
    token = object()
    _recovery_timer_token = token
    try:
        generation = _login_generation
        _timer_ids.append(BigWorld.callback(
            20.0, lambda current=generation, request=token, left=remaining:
            _delayed_recovery(current, request, left)))
    except Exception:
        _recovery_timer_token = None


def _cancel_recovery_timers():
    global _recovery_timer_token
    _recovery_timer_token = None
    for timer in _timer_ids:
        try:
            BigWorld.cancelCallback(timer)
        except Exception:
            pass
    del _timer_ids[:]


def _on_account_become_player(*args, **kwargs):
    global _account_id, _login_generation
    _leave_hangar()
    # A new login event must invalidate the previous account, even if the
    # current client's databaseID is temporarily unavailable.
    _account_id = None
    _login_generation += 1
    _cancel_recovery_timers()
    try:
        player = BigWorld.player()
        identifier, conflict = _live_account_identity(player)
        if not conflict and identifier is not None:
            direct = getattr(player, 'databaseID', None)
            _account_id = direct if _verified_account(direct) == identifier else identifier
    except Exception:
        pass
    if _verified_account(_account_id) is None:
        _notice_once('account_identity', 'Account identity unavailable in current client state')
    else:
        _notices.discard('account_identity')
    if _recovery is not None:
        _recovery.reset_session(_account_id)
    _try_recover()
    _schedule_recovery_checks()


def _on_hangar_space_create(*args, **kwargs):
    global _in_hangar, _account_id
    _in_hangar = bool(_initialized)
    # Login hooks may fire before the account database ID is ready. A later
    # hangar event has a confirmed Account entity; remember its DB ID so the
    # battle Avatar can retain ownership even if it lacks databaseID itself.
    try:
        fresh_account, conflict = _live_account_identity(BigWorld.player())
        if not conflict and fresh_account is not None:
            if _verified_account(_account_id) != fresh_account:
                _account_id = fresh_account
                _log('Own account identity confirmed in hangar')
    except Exception:
        pass
    if _gameface is not None:
        _gameface.on_hangar()
    _attach_result_service()
    _try_recover()
    _schedule_recovery_checks()
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


def _read_local_settings():
    """Read bounded local opt-ins; no imported loader when the UI is disabled."""
    path = os.path.join(os.path.dirname(default_path()), 'settings.json')
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 4096:
            return {}
        with open(path, 'rb') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return {}
        # Windows editors and PowerShell 5.1 may prefix UTF-8 files with BOM.
        settings = json.loads(raw.decode('utf-8-sig'))
        return settings if isinstance(settings, dict) else {}
    except (IOError, OSError, ValueError, UnicodeError):
        return {}


def _load_cache_opt_in():
    return _read_local_settings().get('experimental_cache_recovery') is True


def _load_ui_opt_in():
    return _read_local_settings().get('experimental_gameface_ui') is True


def _leave_hangar(*args, **kwargs):
    global _in_hangar
    _in_hangar = False
    _cancel_recovery_timers()
    if _recovery is not None:
        _recovery.reset_session()
    if _gameface is not None:
        _gameface.close()


def _ui_account():
    """A current Account entity in the hangar, never a cached login identity."""
    if not _initialized or not _in_hangar or _is_replay():
        return None
    try:
        player = BigWorld.player()
        if player is None:
            return None
        # An Avatar may appear before onAvatarReady. Fail closed in that gap.
        if (getattr(player, 'arenaUniqueID', None) not in (None, 0) or
                getattr(player, 'arena', None) is not None):
            return None
        account, conflict = _live_account_identity(player)
        return None if conflict else account
    except Exception:
        return None


def _ui_goals():
    from .goals import validate_goals
    path = os.path.join(os.path.dirname(default_path()), 'goals.json')
    try:
        if not os.path.isfile(path):
            return []
        with open(path, 'rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Goals file too large')
        goals = validate_goals(json.loads(raw.decode('utf-8-sig')))
        _notices.discard('ui_goals')
        return goals
    except (IOError, OSError, ValueError, UnicodeError):
        _notice_once('ui_goals', 'Gameface: goals file unavailable or invalid')
        raise ValueError('Goals unavailable')


def _ui_snapshot(account, request):
    global _ui_workspace
    from .presentation import build_snapshot
    from .workspace import Workspace
    # The controller rechecks identity immediately before delivering this
    # snapshot, including if a provider caused a re-entrant client event.
    if account != _ui_account() or _store is None:
        return build_snapshot([], None, request=request, source='game')
    # Account-wide unresolved entries include partial records and old
    # expectations. Do not claim they are completed or definitely recoverable.
    pending_count = None
    if _pending is not None:
        pending_count = sum(1 for item in _pending.pending.values()
                            if _verified_account(item.get('context', {}).get('account_id')) == account)
    folder = os.path.dirname(_store.path)
    if _ui_workspace is None or _ui_workspace.folder != folder:
        _ui_workspace = Workspace(folder)
    return _ui_workspace.snapshot(list(_store.records), account, request=request,
                                  legacy_goals=_ui_goals, pending_count=pending_count,
                                  diagnostics=dict(_store.diagnostics), source='game')


def _start_gameface():
    global _gameface
    try:
        if not _load_ui_opt_in():
            return
        # An observed hangar event is required; guessing the current space
        # from cached account data can expose a window during a battle.
        if _hangar_space is None:
            _log('Gameface: hangar capability unavailable; UI disabled')
            return
        from .gameface import GamefaceController
        _gameface = GamefaceController(_ui_account, _ui_snapshot, _log)
        if not _gameface.start():
            _gameface = None
            return
    except Exception as error:
        _error('Optional Gameface startup failed: ' + type(error).__name__)
        if _gameface is not None:
            _gameface.stop()
        _gameface = None


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
        _recorder = ResultRecorder(_store, _pending, require_account=True,
                                   metadata_provider=_result_metadata)
        stage = 'loading local settings'
        if _load_cache_opt_in():
            _recovery = CacheRecovery(_pending, _recorder, log=_log,
                                      max_requests=1, serialize=True,
                                      account_provider=_recovery_account,
                                      on_record=_refresh_recovered)
            _log('EXPERIMENTAL cache recovery enabled (unverified API)')
        stage = 'subscribing required battle-result event'
        _attach_event('onBattleResultsReceived', _on_battle_results, required=True)
        _attach_event('onAvatarReady', _on_avatar_ready)
        _attach_event('onAccountBecomePlayer', _on_account_become_player)
        # Cancel delayed cache work even when the optional UI is disabled.
        _attach_event('onAccountBecomeNonPlayer', _leave_hangar)
        _attach_event('onDisconnected', _leave_hangar)
        _initialized = True
        _log('Started; local data path: ' + _store.path)
        try:
            from helpers import dependency
            from skeletons.gui.shared.utils import IHangarSpace
            _hangar_space = dependency.instance(IHangarSpace)
            _hangar_space.onSpaceCreate += _on_hangar_space_create
        except Exception:
            _hangar_space = None
            _log('Hangar notification hook unavailable')
        _attach_result_service()
        _start_gameface()
    except Exception as error:
        _error('Startup failed: %s (%s)' % (stage, type(error).__name__))
        fini()


def fini():
    global _initialized, _store, _pending, _recorder, _recovery, _hangar_space, _account_id
    global _login_generation
    global _gameface, _in_hangar, _result_service_event, _ui_workspace
    _in_hangar = False
    if _gameface is not None:
        _gameface.stop()
    _gameface = None
    _ui_workspace = None
    _login_generation += 1
    if _recovery is not None:
        _recovery.stop()
    _cancel_recovery_timers()
    _detach_events()
    if _result_service_event is not None:
        try:
            _result_service_event -= _on_result_posted
        except Exception:
            pass
        _result_service_event = None
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
