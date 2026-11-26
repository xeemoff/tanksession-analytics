# -*- coding: utf-8 -*-
"""Simulated game API smoke tests, not real Lesta compatibility tests."""
import importlib
import json
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



    def test_hangar_identity_is_retained_for_battle_avatar(self):
        self.player.databaseID = None
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.assertIsNone(self.game._account_id)
        # Account DB ID arrives only after the account login event, in hangar.
        self.player.databaseID = 88
        self.game._on_hangar_space_create()
        self.assertEqual(self.game._account_id, '88')
        # In battle the Avatar has no databaseID, unlike the hangar Account.
        self.player.databaseID = None
        self.events.onAvatarReady.fire()
        self.assertEqual(self.game._pending.context(1234)['account_id'], '88')
        self.player.arenaUniqueID = None
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'team': 1, 'damageDealt': 800, 'xp': 250}},
        })
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.records[0]['account_id'], '88')
        self.assertTrue(any('confirmed in hangar' in line for line in self.notes))

    def test_client_utility_supplies_account_when_player_attribute_is_missing(self):
        shared = types.ModuleType('gui.shared')
        utils = types.ModuleType('gui.shared.utils')
        utils.getPlayerDatabaseID = lambda: 77
        sys.modules['gui.shared'] = shared
        sys.modules['gui.shared.utils'] = utils
        self.player.databaseID = None
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        self.assertEqual(self.game._pending.context(1234)['account_id'], '77')
        self.player.arenaUniqueID = None
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'team': 1, 'damageDealt': 1111, 'xp': 400}},
        })
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.records[0]['account_id'], '77')

    def test_legacy_dossier_fallback_without_utility(self):
        helpers = types.ModuleType('helpers')
        dossier = types.SimpleNamespace(getPlayerDBID=lambda: 66)
        cache = types.SimpleNamespace(items=types.SimpleNamespace(
            getAccountDossier=lambda: dossier))
        helpers.dependency = types.SimpleNamespace(instance=lambda _: cache)
        skeletons = types.ModuleType('skeletons')
        skeletons.__path__ = []
        skeletons_gui = types.ModuleType('skeletons.gui')
        skeletons_gui.__path__ = []
        skeletons_shared = types.ModuleType('skeletons.gui.shared')
        skeletons_shared.__path__ = []
        skeletons_shared.IItemsCache = object
        sys.modules.update({'helpers': helpers, 'skeletons': skeletons,
                            'skeletons.gui': skeletons_gui,
                            'skeletons.gui.shared': skeletons_shared})
        self.player.databaseID = None
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        self.assertEqual(self.game._pending.context(1234)['account_id'], '66')
        self.player.arenaUniqueID = None
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'team': 1, 'damageDealt': 350, 'xp': 180}},
        })
        self.assertEqual(self.game._store.records[0]['account_id'], '66')

    def test_disagreeing_client_identity_sources_pause_collection(self):
        shared = types.ModuleType('gui.shared')
        utils = types.ModuleType('gui.shared.utils')
        utils.getPlayerDatabaseID = lambda: 99
        sys.modules['gui.shared'] = shared
        sys.modules['gui.shared.utils'] = utils
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.assertIsNone(self.game._account_id)
        self.events.onAvatarReady.fire()
        self.assertNotIn('account_id', self.game._pending.context(1234))
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'team': 1, 'damageDealt': 1111, 'xp': 400}},
        })
        self.assertEqual(self.game._store.records, [])
        self.assertTrue(any('identity sources disagree' in x for x in self.notes))
        self.assertFalse(any('99' in x for x in self.notes))

    def test_absent_account_stays_absent_instead_of_using_entity_id(self):
        shared = types.ModuleType('gui.shared')
        utils = types.ModuleType('gui.shared.utils')
        utils.getPlayerDatabaseID = lambda: None
        sys.modules['gui.shared'] = shared
        sys.modules['gui.shared.utils'] = utils
        self.player.databaseID = None
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        self.assertNotIn('account_id', self.game._pending.context(1234))
        self.assertIsNone(self.game._context().get('account_id'))

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
        self.player.arenaUniqueID = None
        self.player.playerVehicleID = None
        self.game._try_recover()
        self.assertEqual(len(requests), 1)
        self.player.databaseID = 99
        self.game._on_account_become_player()
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
                   'personal': {42: {'team': 1, 'damageDealt': 1111, 'xp': 400}}}
        requests[0][1](0, payload)
        self.assertEqual(self.game._store.records, [])
        self.assertIn('1234', self.game._pending.pending)

    def test_lobby_posted_recovers_only_own_pending_loss(self):
        self.game._load_cache_opt_in = lambda: True
        requests = []
        self.player.battleResultsCache = types.SimpleNamespace(
            get=lambda arena, callback: requests.append((arena, callback)))
        self.game.init()
        self.game._on_account_become_player()
        self.game._on_avatar_ready()
        self.player.arenaUniqueID = None
        self.player.playerVehicleID = None
        def posted(account, arena):
            return types.SimpleNamespace(arenaUniqueID=arena,
                personal=types.SimpleNamespace(avatar=types.SimpleNamespace(accountDBID=account)))
        self.game._on_result_posted(posted(99, 1234))
        self.game._on_result_posted(posted(88, 9999))
        self.assertEqual(requests, [])
        self.game._on_result_posted(posted(88, 1234))
        self.assertEqual(len(requests), 1)
        payload = {'arenaUniqueID': 1234, 'common': {'winnerTeam': 2},
                   'personal': {'avatar': {'accountDBID': 88, 'team': 1},
                                777: {'damageDealt': 0, 'xp': 400}}}
        requests[0][1](2, payload)
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.records[0]['outcome'], 'loss')
        self.assertNotIn('1234', self.game._pending.pending)
        self.game._on_result_posted(posted(88, 1234))
        self.assertEqual(len(requests), 1)
        self.assertTrue(any('Recovered battle: complete' in line for line in self.notes))

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

    def _install_optional_ui(self, broken=False):
        hangar = types.SimpleNamespace(onSpaceCreate=Event())
        helpers = types.ModuleType('helpers')
        helpers.dependency = types.SimpleNamespace(instance=lambda unused: hangar)
        sys.modules['helpers'] = helpers
        for name in ('skeletons', 'skeletons.gui', 'skeletons.gui.shared',
                     'skeletons.gui.shared.utils'):
            module = types.ModuleType(name)
            module.__path__ = []
            sys.modules[name] = module
        sys.modules['skeletons.gui.shared.utils'].IHangarSpace = object
        self.events.onAccountBecomeNonPlayer = Event()
        self.events.onDisconnected = Event()
        module = types.ModuleType('tanksession_analytics.gameface')

        class UI(object):
            def __init__(self, context, snapshot, log):
                if broken:
                    raise RuntimeError('private optional loader error')
                self.context, self.snapshot = context, snapshot
                self.closes = self.stops = self.hangars = self.refreshes = 0

            def start(self):
                return True

            def close(self):
                self.closes += 1

            def stop(self):
                self.stops += 1

            def on_hangar(self):
                self.hangars += 1

            def refresh(self):
                self.refreshes += 1

        module.GamefaceController = UI
        sys.modules['tanksession_analytics.gameface'] = module
        return hangar

    def test_gameface_opt_in_requires_boolean_true_and_is_off_by_default(self):
        self.assertFalse(self.game._load_ui_opt_in())
        path = os.path.join(self.folder.name, 'settings.json')
        for value in (False, 'true', 1, None, True):
            with open(path, 'w') as stream:
                json.dump({'experimental_gameface_ui': value}, stream)
            self.assertEqual(self.game._load_ui_opt_in(), value is True)

    def test_windows_utf8_bom_settings_enable_ui_without_changing_file(self):
        self._install_optional_ui()
        path = os.path.join(self.folder.name, 'settings.json')
        settings = {'experimental_gameface_ui': True,
                    'experimental_cache_recovery': False, 'label': u'Настройки'}
        raw = json.dumps(settings, ensure_ascii=False).encode('utf-8-sig')
        with open(path, 'wb') as stream:
            stream.write(raw)
        self.game.init()
        self.assertIsNotNone(self.game._gameface)
        self.assertEqual(self.game._read_local_settings(), settings)
        with open(path, 'rb') as stream:
            self.assertEqual(stream.read(), raw)

    def test_bom_settings_still_reject_wrong_types_invalid_bytes_and_oversize(self):
        path = os.path.join(self.folder.name, 'settings.json')
        cases = (b'\xef\xbb\xbf[true]', b'\xef\xbb\xbf{"experimental_gameface_ui":"true"}',
                 b'\xef\xbb\xbf{"experimental_gameface_ui":true}\xff',
                 b'\xef\xbb\xbf{"experimental_gameface_ui":true}' + b' ' * 4096)
        for raw in cases:
            with open(path, 'wb') as stream:
                stream.write(raw)
            self.assertFalse(self.game._load_ui_opt_in())

    def test_windows_utf8_bom_goals_keep_unicode_and_validation(self):
        path = os.path.join(self.folder.name, 'goals.json')
        goals = [{'account_id': '88', 'vehicle': u'ИС-7',
                  'target_avg_damage': 2000, 'window': 10}]
        with open(path, 'wb') as stream:
            stream.write(json.dumps(goals, ensure_ascii=False).encode('utf-8-sig'))
        self.assertEqual(self.game._ui_goals(), goals)
        for raw in (b'\xef\xbb\xbf{}', b'\xef\xbb\xbf[]' + b' ' * 65536,
                    b'\xef\xbb\xbf["PRIVATE_INVALID_GOAL"]'):
            with open(path, 'wb') as stream:
                stream.write(raw)
            with self.assertRaises(ValueError):
                self.game._ui_goals()
        self.assertFalse(any('PRIVATE_INVALID_GOAL' in line for line in self.notes))

    def test_disabled_ui_does_not_construct_loader_adapter(self):
        self._install_optional_ui(broken=True)
        self.game.init()
        self.assertTrue(self.game._initialized)
        self.assertIsNone(self.game._gameface)
        self.assertFalse(any('Gameface startup failed' in line for line in self.errors))

    def test_optional_ui_startup_failure_keeps_recording_available(self):
        self._install_optional_ui(broken=True)
        self.game._load_ui_opt_in = lambda: True
        self.game.init()
        self.assertTrue(self.game._initialized)
        self.assertIsNotNone(self.game._recorder)
        self.assertIsNone(self.game._gameface)
        self.assertTrue(any('Optional Gameface startup failed' in line for line in self.errors))
        self.assertFalse(any('private' in line for line in self.errors))

    def test_missing_hangar_capability_keeps_ui_closed(self):
        self.game._load_ui_opt_in = lambda: True
        self.game.init()
        self.assertTrue(self.game._initialized)
        self.assertIsNone(self.game._gameface)
        self.assertTrue(any('hangar capability unavailable' in line for line in self.notes))

    def test_ui_account_requires_observed_hangar_and_fresh_non_replay_entity(self):
        self.game.init()
        self.player.arenaUniqueID = None
        self.game._on_account_become_player()
        self.assertIsNone(self.game._ui_account())
        self.game._on_hangar_space_create()
        self.assertEqual(self.game._ui_account(), '88')
        self.player.databaseID = None
        self.assertIsNone(self.game._ui_account())
        self.player.databaseID = 88
        self.player.arenaUniqueID = 1234
        self.assertIsNone(self.game._ui_account())
        self.player.arenaUniqueID = None
        sys.modules['BattleReplay'].isPlaying = lambda: True
        self.assertIsNone(self.game._ui_account())

    def test_ui_lifecycle_closes_on_account_avatar_disconnect_and_unload(self):
        hangar = self._install_optional_ui()
        self.game._load_ui_opt_in = lambda: True
        self.game.init()
        ui = self.game._gameface
        self.player.arenaUniqueID = None
        hangar.onSpaceCreate.fire()
        self.assertEqual(ui.context(), '88')
        self.events.onAccountBecomePlayer.fire()
        self.assertIsNone(ui.context())
        hangar.onSpaceCreate.fire()
        self.events.onAvatarReady.fire()
        hangar.onSpaceCreate.fire()
        self.events.onAccountBecomeNonPlayer.fire()
        hangar.onSpaceCreate.fire()
        self.events.onDisconnected.fire()
        self.assertEqual(ui.closes, 4)
        self.game.fini()
        self.assertEqual(ui.stops, 1)
        self.assertEqual(hangar.onSpaceCreate.handlers, [])
        self.assertEqual(self.events.onAccountBecomeNonPlayer.handlers, [])
        self.assertEqual(self.events.onDisconnected.handlers, [])

    def test_ui_snapshot_is_scoped_to_fresh_account_and_invalid_goals_error(self):
        self.game.init()
        self.player.arenaUniqueID = None
        self.game._on_hangar_space_create()
        self.game._store.append({'arena_id': '1', 'account_id': '88',
                                 'timestamp': 1700000000, 'outcome': 'win'})
        self.game._store.append({'arena_id': '2', 'account_id': '99',
                                 'timestamp': 1700000001, 'outcome': 'loss'})
        snapshot = self.game._ui_snapshot('88', None)
        self.assertEqual(snapshot['summary']['battles'], 1)
        self.assertEqual(snapshot['summary']['wins'], 1)
        self.assertNotIn('account_id', json.dumps(snapshot))
        self.player.databaseID = 99
        self.assertEqual(self.game._ui_snapshot('88', None)['status'], 'account_unavailable')
        path = os.path.join(self.folder.name, 'goals.json')
        with open(path, 'w') as stream:
            stream.write('invalid goals with PRIVATE_VALUE')
        with self.assertRaises(ValueError):
            self.game._ui_snapshot('99', None)
        self.assertFalse(any('PRIVATE_VALUE' in line for line in self.notes))
        with open(path, 'w') as stream:
            json.dump([], stream)
        self.assertEqual(self.game._ui_snapshot('99', None)['goals'], [])


if __name__ == '__main__':
    unittest.main()
