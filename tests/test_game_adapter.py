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

    def test_vehicle_type_identity_survives_a_late_hangar_result(self):
        sys.modules['BigWorld'].entities[42].typeDescriptor = types.SimpleNamespace(
            name='ussr:R04_T-34', type=types.SimpleNamespace(compactDescr=257))
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        context = self.game._pending.context(1234)
        self.assertEqual(context['vehicle_id'], 'type:257')
        self.assertEqual(context['player_vehicle_id'], '42')
        self.player.playerVehicleID = None
        self.player.arenaUniqueID = None
        sys.modules['BigWorld'].entities.clear()
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'typeCompDescr': 257, 'team': 1,
                              'damageDealt': 1111, 'xp': 400}}})
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.records[0]['vehicle_id'], 'type:257')
        self.assertEqual(self.game._store.records[0]['vehicle'], 'ussr:R04_T-34')

    def test_conflicting_result_type_does_not_replace_saved_battle_context(self):
        sys.modules['BigWorld'].entities[42].typeDescriptor = types.SimpleNamespace(
            name='ussr:R04_T-34', type=types.SimpleNamespace(compactDescr=257))
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        self.player.playerVehicleID = None
        self.player.arenaUniqueID = None
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1},
            'personal': {42: {'typeCompDescr': 513, 'team': 1,
                              'damageDealt': 9999, 'xp': 400}}})
        self.assertEqual(self.game._store.records, [])
        self.assertEqual(self.game._pending.context(1234)['vehicle_id'], 'type:257')

    def test_verified_metadata_survives_hangar_and_map_uses_full_arena_type(self):
        vehicle_type = types.SimpleNamespace(compactDescr=257, id=(0, 1), level=6,
                                             classTag='mediumTank', tags=frozenset(['mediumTank']))
        sys.modules['BigWorld'].entities[42].typeDescriptor = types.SimpleNamespace(
            name='ussr:R04_T-34', type=vehicle_type)
        arenas = types.ModuleType('ArenaType')
        arenas.g_cache = {65547: types.SimpleNamespace(id=65547, name=u'Проверяемая карта'),
                          11: types.SimpleNamespace(id=11, name=u'Другая геометрия')}
        items = types.ModuleType('items')
        items.vehicles = types.SimpleNamespace(getVehicleType=lambda value: vehicle_type)
        sys.modules.update({'ArenaType': arenas, 'items': items})
        self.game.init()
        self.events.onAccountBecomePlayer.fire()
        self.events.onAvatarReady.fire()
        captured = self.game._pending.context(1234)
        self.assertEqual((captured['vehicle_tier'], captured['vehicle_class'], captured['vehicle_nation']),
                         (6, 'mediumTank', 'ussr'))
        self.player.playerVehicleID = None
        self.player.arenaUniqueID = None
        sys.modules['BigWorld'].entities.clear()
        vehicle_type.level = 7  # A later catalog must not replace the captured tier.
        self.events.onBattleResultsReceived.fire(True, {
            'arenaUniqueID': 1234, 'common': {'winnerTeam': 1, 'arenaTypeID': 65547},
            'personal': {42: {'typeCompDescr': 257, 'team': 1, 'damageDealt': 1111, 'xp': 400}}})
        record = self.game._store.records[0]
        self.assertEqual(record['map'], 'arena:65547')
        self.assertEqual(record['map_label'], u'Проверяемая карта')
        self.assertEqual(record['vehicle_tier'], 6)
        self.assertEqual(record['vehicle_class'], 'mediumTank')
        self.assertEqual(record['vehicle_nation'], 'ussr')



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

    def test_recovery_retry_timer_stops_after_bounded_batch(self):
        self.game._load_cache_opt_in = lambda: True
        callbacks, requests, delays = [], [], []
        current = [1700000000]
        self.game.time = types.SimpleNamespace(time=lambda: current[0])

        def schedule(delay, callback):
            delays.append(delay)
            callbacks.append(callback)
            return len(callbacks)

        sys.modules['BigWorld'].callback = schedule
        self.player.arenaUniqueID = None
        self.player.battleResultsCache = types.SimpleNamespace(
            get=lambda arena, callback: requests.append((arena, callback)))
        self.game.init()
        self.game._recovery.clock = lambda: current[0]
        self.game._pending.start(1234, {'account_id': 88}, current[0])
        self.game._on_account_become_player()
        requests[-1][1](-10, None)
        for index in range(4):
            current[0] += 20
            callbacks[index]()
            requests[-1][1](-10, None)
        self.assertEqual(len(requests), 5)  # initial event plus four checks
        self.assertEqual(delays, [20.0] * 4)
        self.assertEqual(self.game._timer_ids, [])
        self.assertIsNone(self.game._recovery_timer_token)
        self.assertIn('1234', self.game._pending.pending)

    def test_leaving_hangar_cancels_recovery_when_ui_is_disabled(self):
        self.game._load_cache_opt_in = lambda: True
        self.events.onDisconnected = Event()
        self.events.onAccountBecomeNonPlayer = Event()
        callbacks, requests, cancelled = [], [], []

        def schedule(delay, callback):
            callbacks.append(callback)
            return len(callbacks)

        sys.modules['BigWorld'].callback = schedule
        sys.modules['BigWorld'].cancelCallback = cancelled.append
        self.player.arenaUniqueID = None
        self.player.battleResultsCache = types.SimpleNamespace(
            get=lambda arena, callback: requests.append((arena, callback)))
        self.game.init()
        now = int(self.game.time.time())
        self.game._pending.start(1234, {'account_id': 88}, now)
        self.game._on_account_become_player()
        self.assertEqual(len(requests), 1)
        self.events.onDisconnected.fire()
        self.assertEqual(cancelled, [1])
        self.assertFalse(self.game._recovery.has_work())
        callbacks[0]()
        requests[0][1](0, {'arenaUniqueID': 1234,
                            'common': {'winnerTeam': 1},
                            'personal': {42: {'team': 1, 'damageDealt': 83, 'xp': 924}}})
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.game._store.records, [])

    def test_cancelled_timer_cannot_consume_replacement_in_same_login(self):
        self.game._load_cache_opt_in = lambda: True
        callbacks = []

        def schedule(delay, callback):
            callbacks.append(callback)
            return len(callbacks)

        sys.modules['BigWorld'].callback = schedule
        self.game.init()
        self.game._schedule_recovery_checks()
        generation = self.game._login_generation
        self.game._cancel_recovery_timers()
        self.game._schedule_recovery_checks()
        self.assertEqual(self.game._login_generation, generation)
        callbacks[0]()
        self.assertEqual(self.game._timer_ids, [2])
        callbacks[1]()
        self.assertEqual(self.game._timer_ids, [])

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

    def test_ui_snapshot_is_scoped_and_bad_legacy_goals_keep_history_readable(self):
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
        broken = self.game._ui_snapshot('99', None)
        self.assertEqual(broken['summary']['battles'], 1)
        self.assertFalse(broken['workspace']['can_edit'])
        self.assertEqual(broken['workspace']['operation']['code'], 'read_failed')
        self.assertFalse(any('PRIVATE_VALUE' in line for line in self.notes))
        with open(path, 'w') as stream:
            json.dump([], stream)
        self.assertEqual(self.game._ui_snapshot('99', None)['goals'], [])

    def _install_additional_xp_api(self):
        handlers = {}
        class Bus(object):
            def addListener(self, name, handler):
                handlers.setdefault(name, []).append(handler)
            def removeListener(self, name, handler):
                handlers[name].remove(handler)
            def fire(self):
                for handler in list(handlers.get('premiumXPBonusChanged', [])):
                    handler(object())
        service = types.SimpleNamespace(onResultPosted=Event(), offers={9001: (257, 450)},
                                        applied=set())
        service.isAddXPBonusApplied = lambda arena: arena in service.applied
        service.getAdditionalXPValue = lambda arena: service.offers.get(arena, (None, 0))[1]
        service.getVehicleForArena = lambda arena: types.SimpleNamespace(
            intCD=service.offers.get(arena, (None, 0))[0])
        api = types.ModuleType('skeletons.gui.battle_results')
        api.IBattleResultsService = object()
        def instance(interface):
            if interface is api.IBattleResultsService:
                return service
            raise LookupError('Synthetic unavailable interface')
        helpers = types.ModuleType('helpers')
        helpers.dependency = types.SimpleNamespace(instance=instance)
        shared = types.ModuleType('gui.shared')
        shared.g_eventBus = Bus()
        shared.events = types.SimpleNamespace(LobbySimpleEvent=types.SimpleNamespace(
            PREMIUM_XP_BONUS_CHANGED='premiumXPBonusChanged'))
        sys.modules.update({'helpers': helpers, 'skeletons.gui.battle_results': api,
                            'gui.shared': shared})
        return service, shared.g_eventBus, handlers

    @staticmethod
    def _bonus_posted(account=88, arena=9001, progress=None):
        if progress is None:
            progress = {257: {'xp': 600}}
        return types.SimpleNamespace(arenaUniqueID=arena, personal=types.SimpleNamespace(
            avatar=types.SimpleNamespace(accountDBID=account), xpProgress=progress))

    def _bonus_baseline(self, **patch):
        row = {'arena_id': '9001', 'account_id': '88', 'vehicle_id': 'type:257',
               'vehicle': 'ussr:R04_T-34', 'timestamp': 1700000000,
               'xp': 600, 'xp_base': 100, 'xp_bonus': 500, 'damage': 1000,
               'mode': '1', 'outcome': 'win'}
        row.update(patch)
        self.game._store.upsert(row)
        return row

    def _bonus_hangar(self):
        service, bus, handlers = self._install_additional_xp_api()
        self.game.init()
        self.player.arenaUniqueID = None
        self.player.playerVehicleID = None
        self.events.onAccountBecomePlayer.fire()
        return service, bus, handlers

    def test_additional_xp_observation_is_independent_of_cache_and_counts_one_battle(self):
        service, bus, handlers = self._bonus_hangar()
        self.assertIsNone(self.game._recovery)
        baseline = self._bonus_baseline()
        refreshed = []
        self.game._gameface = types.SimpleNamespace(refresh=lambda: refreshed.append(True), stop=lambda: None)
        service.onResultPosted.fire(self._bonus_posted())
        self.assertEqual(len(self.game._additional_xp_candidates), 1)
        bus.fire()  # No success proof yet.
        self.assertEqual(self.game._store.records[0]['xp'], 600)
        service.applied.add(9001)
        service.offers.clear()  # Actual client removes the consumed offer.
        bus.fire()
        bus.fire()
        after = self.game._store.records[0]
        self.assertEqual((after['xp'], after['xp_bonus'], after['xp_base']), (1050, 950, 100))
        self.assertEqual(len(self.game._store.records), 1)
        self.assertEqual(self.game._store.upsert(baseline), 'duplicate')
        self.assertEqual(refreshed, [True])
        self.game._attach_result_service()
        self.assertEqual(len(service.onResultPosted.handlers), 1)
        self.assertEqual(len(handlers['premiumXPBonusChanged']), 1)
        self.game.fini()
        self.assertEqual(service.onResultPosted.handlers, [])
        self.assertEqual(handlers['premiumXPBonusChanged'], [])

    def test_additional_xp_needs_own_single_exact_vehicle_result_and_matching_offer(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline()
        for invalid in (self._bonus_posted(account=99), self._bonus_posted(arena=9002),
                        self._bonus_posted(progress={257: {'xp': 600}, 513: {'xp': 10}}),
                        self._bonus_posted(progress={513: {'xp': 600}})):
            service.onResultPosted.fire(invalid)
        self.assertEqual(self.game._additional_xp_candidates, {})
        service.applied.add(9001)
        bus.fire()
        self.assertEqual(self.game._store.records[0]['xp'], 600)

    def test_unobserved_old_bonus_and_replay_cannot_revise_history(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline()
        service.applied.add(9001)
        service.onResultPosted.fire(self._bonus_posted())
        bus.fire()
        self.assertEqual(self.game._additional_xp_candidates, {})
        self.assertEqual(self.game._store.records[0]['xp'], 600)
        service.applied.clear()
        service.onResultPosted.fire(self._bonus_posted())
        service.applied.add(9001)
        sys.modules['BattleReplay'].isPlaying = lambda: True
        bus.fire()
        self.assertEqual(self.game._store.records[0]['xp'], 600)

    def test_bonus_confirmation_does_not_apply_to_latest_or_other_account_battle(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline()
        self._bonus_baseline(arena_id='9002', xp=200, xp_bonus=100)
        service.onResultPosted.fire(self._bonus_posted())
        service.applied.add(9002)
        bus.fire()
        self.assertEqual([row['xp'] for row in self.game._store.records], [600, 200])
        self.player.databaseID = 99
        service.applied.add(9001)
        bus.fire()
        self.assertEqual(self.game._store.records[0]['xp'], 600)
        self.events.onAccountBecomePlayer.fire()
        self.assertEqual(self.game._additional_xp_candidates, {})

    def test_conflicting_offer_stays_blocked_until_next_login(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline()
        service.onResultPosted.fire(self._bonus_posted())
        service.offers[9001] = (257, 451)
        service.onResultPosted.fire(self._bonus_posted())
        service.onResultPosted.fire(self._bonus_posted())
        service.applied.add(9001)
        bus.fire()
        self.assertIsNone(self.game._additional_xp_candidates[('88', '9001')])
        self.assertEqual(self.game._store.records[0]['xp'], 600)

    def test_bonus_event_before_late_cache_fill_is_applied_once_after_fill(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline(xp=None, xp_bonus=None, vehicle_id=None)
        service.onResultPosted.fire(self._bonus_posted())
        service.applied.add(9001)
        bus.fire()
        self.assertIsNone(self.game._store.records[0]['xp'])
        self.assertEqual(len(self.game._additional_xp_candidates), 1)
        self._bonus_baseline()
        self.game._on_cache_record()
        self.assertEqual(self.game._store.records[0]['xp'], 1050)
        self.assertEqual(self.game._additional_xp_candidates, {})
        self.game._on_cache_record()
        self.assertEqual(self.game._store.diagnostics['lines'], 3)

    def test_next_login_reattaches_after_client_clears_service_events(self):
        service, bus, handlers = self._bonus_hangar()
        service.onResultPosted.handlers[:] = []  # BattleResultsService.clear.
        self.events.onAccountBecomePlayer.fire()
        self.assertEqual(len(service.onResultPosted.handlers), 1)
        self.assertEqual(len(handlers['premiumXPBonusChanged']), 1)
        self._bonus_baseline()
        service.onResultPosted.fire(self._bonus_posted())
        service.applied.add(9001)
        bus.fire()
        self.assertEqual(self.game._store.records[0]['xp'], 1050)

    def test_optional_display_failure_cannot_break_bonus_event_or_journal(self):
        service, bus, _ = self._bonus_hangar()
        self._bonus_baseline()
        service.onResultPosted.fire(self._bonus_posted())
        def fail():
            raise RuntimeError('Synthetic private UI payload')
        self.game._gameface = types.SimpleNamespace(refresh=fail, stop=lambda: None)
        service.applied.add(9001)
        bus.fire()
        self.assertEqual(self.game._store.records[0]['xp'], 1050)
        self.assertEqual(self.game._additional_xp_candidates, {})
        self.assertFalse(any('private UI payload' in note for note in self.notes))

    def test_old_history_label_projection_is_exact_bounded_and_read_only(self):
        self.game.init()
        self._bonus_baseline()
        self._bonus_baseline(arena_id='9002')
        calls = []
        def get_type(value):
            calls.append(value)
            return types.SimpleNamespace(compactDescr=value, id=(0, value >> 8),
                shortUserString=u'Т-34', level=6, classTag='mediumTank', tags=['mediumTank'])
        items = types.ModuleType('items')
        items.vehicles = types.SimpleNamespace(getVehicleType=get_type)
        sys.modules['items'] = items
        before = self.game._store.diagnostics['lines']
        labelled = self.game._labelled_ui_records('88')
        self.assertEqual([row['vehicle_label'] for row in labelled], [u'Т-34', u'Т-34'])
        self.assertEqual([row['vehicle_id'] for row in labelled], ['type:257', 'type:257'])
        self.assertEqual(calls, [257])
        self.game._labelled_ui_records('88')
        self.assertEqual(calls, [257])
        self.assertEqual(self.game._store.diagnostics['lines'], before)
        self.assertTrue(all(row['vehicle_label'] is None for row in self.game._store.records))
        self.game._ui_vehicle_labels.clear()
        for index in range(130):
            self._bonus_baseline(arena_id=str(10000 + index), vehicle_id='type:%d' % ((index + 1) * 256 + 1))
        calls[:] = []
        self.game._labelled_ui_records('88')
        self.assertEqual(len(calls), 128)


if __name__ == '__main__':
    unittest.main()
