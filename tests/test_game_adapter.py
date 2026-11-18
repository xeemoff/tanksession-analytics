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
        debug.LOG_NOTE = lambda message: None
        debug.LOG_ERROR = lambda message: None

        # The actual client uses gui.mods.tanksession_analytics, while local
        # source tests import tanksession_analytics directly. Alias ONLY within
        # the mock test process; do not ship any fake game APIs.
        package = importlib.import_module('tanksession_analytics')
        gui = types.ModuleType('gui')
        gui.__path__ = []
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


if __name__ == '__main__':
    unittest.main()
