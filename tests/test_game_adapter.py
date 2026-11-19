# -*- coding: utf-8 -*-
"""Simulated game API smoke tests, not real Lesta compatibility tests."""
import importlib
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))


class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self

    def __isub__(self, callback):
        self.handlers.remove(callback)
        return self

    def fire(self, *args):
        for callback in list(self.handlers):
            callback(*args)


class FakePlayer(object):
    databaseID = 88
    playerVehicleID = 42
    team = 1
    arenaUniqueID = 1234
    battleResultsCache = None


class GameAdapterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = dict(sys.modules)
        self.player = FakePlayer()
        self.notes = []
        self.errors = []
        self.messages = []
        self.events = types.SimpleNamespace(
            onBattleResultsReceived=Event(), onAvatarReady=Event(),
            onAccountBecomePlayer=Event())

        bigworld = types.ModuleType('BigWorld')
        bigworld.player = lambda: self.player
        bigworld.entities = {42: types.SimpleNamespace(
            typeDescriptor=types.SimpleNamespace(name='ИС-7'))}
        bigworld.callback = lambda delay, callback: 1
        bigworld.cancelCallback = lambda ident: None
        replay = types.ModuleType('BattleReplay')
        replay.isPlaying = lambda: False
        events = types.ModuleType('PlayerEvents')
        events.g_playerEvents = self.events
        debug = types.ModuleType('debug_utils')
        debug.LOG_NOTE = self.notes.append
        debug.LOG_ERROR = self.errors.append

        # The actual client uses gui.mods.tanksession_analytics, while local
        # source tests import tanksession_analytics directly. Alias ONLY within
        # the mock test process; do not ship any fake game APIs.
        package = importlib.import_module('tanksession_analytics')
        gui = types.ModuleType('gui')
        gui.__path__ = []
        gui.SystemMessages = types.SimpleNamespace(
            SM_TYPE=types.SimpleNamespace(InformationHeader='information'),
            pushMessage=lambda **message: self.messages.append(message))
        mods = types.ModuleType('gui.mods')
        mods.__path__ = []
        sys.modules.update({
            'BigWorld': bigworld, 'BattleReplay': replay,
            'PlayerEvents': events, 'debug_utils': debug,
            'gui': gui, 'gui.mods': mods,
            'gui.mods.tanksession_analytics': package,
        })
        for part in ('core', 'storage', 'recorder', 'recovery'):
            impl = importlib.import_module('tanksession_analytics.' + part)
            sys.modules['gui.mods.tanksession_analytics.' + part] = impl
        self.game = importlib.import_module('tanksession_analytics.game')
        self.game.default_path = lambda: os.path.join(self.folder.name, 'battles.jsonl')
        self.game._load_cache_opt_in = lambda: False

    def tearDown(self):
        self.game.fini()
        sys.modules.clear()
        sys.modules.update(self.saved)
        self.folder.cleanup()

    def test_init_once_capture_once_and_unload(self):
        self.game.init()
        self.game.init()
        self.assertEqual(len(self.events.onBattleResultsReceived.handlers), 1)
        self.assertEqual(len(self.events.onAvatarReady.handlers), 1)
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        self.assertIn('1234', self.game._pending.pending)

        # Now simulate the player being in garage without a battle entity.
        self.player.playerVehicleID = None
        self.player.arenaUniqueID = None
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
                   'personal': {42: {'team': 1, 'damageDealt': 1111, 'xp': 400}}}
        self.events.onBattleResultsReceived.fire(True, payload)
        self.events.onBattleResultsReceived.fire(True, payload)
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.records[0]['vehicle'], 'ИС-7')
        self.assertEqual(self.game._store.records[0]['account_id'], '88')
        self.game.fini()
        self.assertEqual(len(self.events.onBattleResultsReceived.handlers), 0)
        self.assertEqual(len(self.events.onAvatarReady.handlers), 0)
        self.assertEqual(len(self.events.onAccountBecomePlayer.handlers), 0)

    def test_login_event_invalidates_old_account(self):
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.assertEqual(self.game._account_id, 88)
        self.player.databaseID = None
        self.events.onAccountBecomePlayer.fire()
        self.assertIsNone(self.game._account_id)
        self.assertNotIn('account_id', self.game._context())

    def test_no_active_player_never_reuses_cached_account(self):
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.assertEqual(self.game._account_id, 88)
        original = sys.modules['BigWorld'].player
        sys.modules['BigWorld'].player = lambda: None
        try:
            self.assertEqual(self.game._context(), {})
        finally:
            sys.modules['BigWorld'].player = original

    def test_missing_optional_hooks_do_not_stop_basic_result_capture(self):
        del self.events.onAvatarReady
        del self.events.onAccountBecomePlayer
        self.game.init()
        self.assertTrue(self.game._initialized)
        self.assertEqual(len(self.events.onBattleResultsReceived.handlers), 1)

    def test_missing_required_hook_fails_closed(self):
        del self.events.onBattleResultsReceived
        self.game.init()
        self.assertFalse(self.game._initialized)
        self.assertIsNone(self.game._recorder)
        self.assertEqual(self.game._hooks, [])
        self.assertTrue(any('subscribing required battle-result event' in item
                            for item in self.errors))

    def test_hangar_summary_only_includes_current_account(self):
        self.game.init()
        self.game._store.append({'arena_id': '1', 'account_id': '88',
                                 'timestamp': 1700000000, 'outcome': 'win'})
        self.game._store.append({'arena_id': '2', 'account_id': '99',
                                 'timestamp': 1700000001, 'outcome': 'loss'})
        self.game._on_hangar_space_create()
        message = self.messages[-1]['text']
        self.assertIn('боёв текущего аккаунта: 1', message)
        self.assertIn('100.0%', message)
        self.assertNotIn('50.0%', message)

    def test_hangar_summary_explains_unknown_account(self):
        self.game.init()
        self.player.databaseID = None
        self.game._on_account_become_player()
        self.game._on_hangar_space_create()
        self.assertIn('аккаунт ещё не определён', self.messages[-1]['text'])
        self.assertNotIn('победы:', self.messages[-1]['text'])

    def test_replay_capability_failure_is_explained_without_log_flooding(self):
        self.game.init()

        def unavailable():
            raise AttributeError('unsupported client API')

        sys.modules['BattleReplay'].isPlaying = unavailable
        self.assertTrue(self.game._is_replay())
        self.assertTrue(self.game._is_replay())
        notices = lambda: [item for item in self.notes
                           if 'Collection paused: replay status unavailable' in item]
        self.assertEqual(len(notices()), 1)
        sys.modules['BattleReplay'].isPlaying = lambda: False
        self.assertFalse(self.game._is_replay())
        sys.modules['BattleReplay'].isPlaying = unavailable
        self.assertTrue(self.game._is_replay())
        self.assertEqual(len(notices()), 2)

    def test_startup_reports_root_failure_without_exception_payload(self):
        def unavailable():
            raise IOError('C:/Users/private-user/game')

        self.game.default_path = unavailable
        self.game.init()
        self.assertFalse(self.game._initialized)
        self.assertTrue(any('Startup failed: locating game root' in item
                            for item in self.errors))
        self.assertFalse(any('private-user' in item for item in self.errors))

    def test_new_login_invalidates_pending_cache_callbacks(self):
        self.game._load_cache_opt_in = lambda: True
        requests = []
        self.player.battleResultsCache = types.SimpleNamespace(
            get=lambda arena, callback: requests.append((arena, callback)))
        self.game.init()
        self.game._on_account_become_player()
        self.game._on_avatar_ready()
        self.game._try_recover()
        self.assertEqual(len(requests), 1)
        self.player.databaseID = 99
        self.game._on_account_become_player()
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
                   'personal': {42: {'team': 1, 'damageDealt': 1111, 'xp': 400}}}
        requests[0][1](0, payload)
        self.assertEqual(self.game._store.records, [])
        self.assertIn('1234', self.game._pending.pending)

    def test_delayed_recovery_timer_belongs_to_one_login(self):
        self.game._load_cache_opt_in = lambda: True
        callbacks, cancelled = [], []

        def schedule(delay, callback):
            callbacks.append(callback)
            return len(callbacks)

        sys.modules['BigWorld'].callback = schedule
        sys.modules['BigWorld'].cancelCallback = cancelled.append
        self.game.init()
        self.game._on_account_become_player()
        self.game._on_account_become_player()
        self.assertEqual(cancelled, [1])
        self.assertEqual(self.game._timer_ids, [2])
        # Cancellation may race with callback delivery: the generation guard
        # must preserve the replacement timer and avoid running stale work.
        callbacks[0]()
        self.assertEqual(self.game._timer_ids, [2])
        callbacks[1]()
        self.assertEqual(self.game._timer_ids, [])
        self.game.fini()
        self.assertEqual(cancelled, [1])


if __name__ == '__main__':
    unittest.main()
