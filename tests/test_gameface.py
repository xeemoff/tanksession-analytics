# -*- coding: utf-8 -*-
"""Protocol/lifecycle simulations; not a compatibility test in the MT client."""
import json
import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))

from tanksession_analytics.gameface import (
    GamefaceController, MAX_PAYLOAD_CHARS, MAX_REQUEST_BYTES, NativeRuntime,
    decode_request)


def request(identifier='ui-1', **changes):
    value = {'protocol': 1, 'request_id': identifier, 'vehicle': '', 'window': 10}
    value.update(changes)
    return {'payload': json.dumps(value, ensure_ascii=False)}


class FakeWindow(object):
    def __init__(self, payload, on_request, on_close, on_ready, runtime):
        self.payloads = [json.loads(payload)]
        self.on_request, self.on_close, self.on_ready = on_request, on_close, on_ready
        self.runtime = runtime
        self.loaded = self.closed = False
        self.destroyed = 0

    def load(self):
        if self.runtime.load_error:
            raise RuntimeError('private client path must not appear in logs')
        if self.runtime.auto_ready:
            self.loaded = self.on_ready()

    def ready(self):
        return self.loaded

    def alive(self):
        return not self.closed

    def publish(self, payload):
        self.payloads.append(json.loads(payload))

    def close(self):
        self.closed = True
        self.destroyed += 1


class FakeRuntime(object):
    def __init__(self):
        self.available = True
        self.immediate_ready = True
        self.auto_ready = True
        self.load_error = False
        self.create_error = False
        self.layout = 9001
        self.timers = {}
        self.cancelled = []
        self.next_id = 0
        self.window = None
        self.toggle = self.escape = None
        self.mods_registered = False

    def prepare(self, callback):
        if not self.available:
            raise ImportError('private module path')
        self.ready_callback = callback
        if self.immediate_ready:
            callback()

    def layout_id(self):
        return self.layout

    def bind_keys(self, toggle, close):
        self.toggle, self.escape = toggle, close

    def unbind_keys(self):
        self.toggle = self.escape = None

    def register_mods_list(self, callback):
        self.mods_registered = True

    def unregister_mods_list(self):
        self.mods_registered = False

    def schedule(self, delay, callback):
        self.next_id += 1
        self.timers[self.next_id] = (delay, callback)
        return self.next_id

    def cancel(self, timer):
        self.cancelled.append(timer)
        self.timers.pop(timer, None)

    def run(self, timer):
        self.timers.pop(timer)[1]()

    def create(self, layout, payload, on_request, on_close, on_ready):
        if self.create_error:
            raise RuntimeError('private native client state')
        self.window = FakeWindow(payload, on_request, on_close, on_ready, self)
        return self.window


class ProtocolTests(unittest.TestCase):
    def test_unicode_and_utf8_requests(self):
        command = request(vehicle=u'ИС-7')
        self.assertEqual(decode_request(command)['vehicle'], u'ИС-7')
        command['payload'] = command['payload'].encode('utf-8')
        self.assertEqual(decode_request(command)['vehicle'], u'ИС-7')

    def test_boundaries_invalid_json_and_identity_fields(self):
        cases = [None, {}, {'payload': []}, {'payload': '{'},
                 {'payload': 'null'}, {'payload': '[]'},
                 {'payload': ' ' * (MAX_REQUEST_BYTES + 1)},
                 {'payload': u'я' * (MAX_REQUEST_BYTES // 2 + 1)},
                 {'payload': b'\xff'},
                 {'payload': '{"protocol":1,"protocol":1,"request_id":"x"}'},
                 {'payload': '{"protocol":NaN,"request_id":"x"}'},
                 request(account_id='other'), request(protocol=True),
                 request(window=20), request(identifier='bad id')]
        for command in cases:
            with self.assertRaises((ValueError, UnicodeError)):
                decode_request(command)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.account = '88'
        self.now = 100.0
        self.runtime = FakeRuntime()
        self.logs = []
        self.calls = []
        self.provider_hook = None

        def snapshot(account, value):
            self.calls.append((account, dict(value)))
            if self.provider_hook is not None:
                self.provider_hook()
            return {'protocol': 1, 'source': 'game',
                    'request_id': value['request_id'],
                    'selection': {'vehicle': value['vehicle'], 'window': value['window']},
                    'summary': {'battles': len(self.calls)}}

        self.controller = GamefaceController(
            lambda: self.account, snapshot, self.logs.append,
            runtime=self.runtime, clock=lambda: self.now)

    def tearDown(self):
        self.controller.stop()

    def open(self):
        self.assertTrue(self.controller.start())
        self.assertTrue(self.controller.open())
        return self.runtime.window

    def test_missing_loader_disables_only_optional_ui(self):
        self.runtime.available = False
        self.assertFalse(self.controller.start())
        self.assertFalse(self.controller.open())
        self.assertIsNone(self.runtime.toggle)
        self.assertEqual(len(self.logs), 1)
        self.assertNotIn('private', self.logs[0])

    def test_missing_or_invalid_layout_fails_closed(self):
        for layout in (-1, None, True, '9001'):
            self.runtime.layout = layout
            self.assertFalse(self.controller.start())
            self.assertFalse(self.controller.open())
            self.assertIsNone(self.runtime.toggle)

    def test_missing_account_never_reads_journal(self):
        self.account = None
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.open())
        self.assertEqual(self.calls, [])

    def test_single_window_and_latest_request_receives_reply(self):
        window = self.open()
        self.assertTrue(self.controller.open())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(window.payloads[0]['request_id'], 'initial')
        window.on_request(request('ui-1', vehicle=u'ИС-7'))
        timer = self.controller._request_timer
        window.on_request(request('ui-2', window=30))
        self.assertEqual(self.controller._request_timer, timer)
        self.runtime.run(timer)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][0], '88')
        self.assertEqual(window.payloads[-1]['request_id'], 'ui-2')
        self.assertEqual(window.payloads[-1]['selection']['window'], 30)

    def test_refresh_preserves_queued_request_and_current_id(self):
        window = self.open()
        window.on_request(request('ui-2', window=100))
        self.controller.refresh()
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(window.payloads[-1]['request_id'], 'ui-2')
        self.assertEqual(window.payloads[-1]['selection']['window'], 100)
        self.controller.refresh()
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(window.payloads[-1]['request_id'], 'ui-2')

    def test_mutations_are_not_coalesced_or_replayed_by_refresh(self):
        window = self.open()
        window.on_request(request('view-1', window=30))
        self.runtime.run(self.controller._request_timer)
        self.controller.refresh()
        window.on_request(request('command-2', action='export_csv', window=30))
        window.on_request(request('command-3', action='save_goal', window=30,
                                 goal={'vehicle': 'Tank', 'window': 10, 'target_avg_damage': 1000}))
        self.controller.refresh()
        self.runtime.run(self.controller._request_timer)
        self.runtime.run(self.controller._request_timer)
        self.assertEqual([value.get('action') for account, value in self.calls],
                         [None, None, 'export_csv', 'save_goal'])
        self.assertEqual(window.payloads[-1]['request_id'], 'command-3')
        self.controller.refresh()
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(window.payloads[-1]['request_id'], 'command-3')
        self.assertNotIn('action', self.calls[-1][1])
        self.assertNotIn('goal', self.calls[-1][1])

    def test_reentrant_refresh_uses_completed_command_id_without_repeating_write(self):
        window = self.open()
        window.on_request(request('export-1', action='export_csv'))
        self.provider_hook = self.controller.refresh
        self.runtime.run(self.controller._request_timer)
        self.provider_hook = None
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(self.calls[-2][1]['action'], 'export_csv')
        self.assertNotIn('action', self.calls[-1][1])
        self.assertEqual(window.payloads[-1]['request_id'], 'export-1')

    def test_invalid_request_does_not_read_data_or_log_payload(self):
        window = self.open()
        for unused in range(3):
            window.on_request(request(account_id='SECRET_ACCOUNT'))
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.controller._request_timer)
        errors = [line for line in self.logs if 'rejected' in line]
        self.assertEqual(len(errors), 1)
        self.assertNotIn('SECRET_ACCOUNT', errors[0])

    def test_account_change_closes_before_processing_request(self):
        window = self.open()
        self.account = '99'
        window.on_request(request())
        self.assertTrue(window.closed)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.controller._account)

    def test_account_change_while_snapshot_built_cannot_publish(self):
        window = self.open()
        window.on_request(request())
        self.provider_hook = lambda: setattr(self, 'account', '99')
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(len(window.payloads), 1)
        self.assertTrue(window.closed)

    def test_account_change_during_initial_snapshot_cannot_create_window(self):
        self.provider_hook = lambda: setattr(self, 'account', '99')
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.open())
        self.assertIsNone(self.runtime.window)

    def test_stale_callbacks_cannot_close_or_publish_into_new_window(self):
        old = self.open()
        old.on_request(request('old'))
        stale_delivery = self.runtime.timers[self.controller._request_timer][1]
        stale_watch = self.runtime.timers[self.controller._watch_timer][1]
        self.controller.close()
        self.assertTrue(self.controller.open())
        current = self.runtime.window
        old.on_request(request('stale'))
        old.on_close()
        stale_delivery()
        stale_watch()
        self.assertFalse(current.closed)
        self.assertEqual(len(current.payloads), 1)

    def test_watchdog_checks_identity_without_rebuilding_snapshot(self):
        window = self.open()
        self.runtime.run(self.controller._watch_timer)
        self.assertEqual(len(self.calls), 1)
        self.account = None
        self.runtime.run(self.controller._watch_timer)
        self.assertTrue(window.closed)
        self.assertEqual(self.runtime.timers, {})

    def test_failed_load_releases_window_and_timers(self):
        self.runtime.load_error = True
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.open())
        self.assertTrue(self.runtime.window.closed)
        self.assertEqual(self.runtime.timers, {})
        self.assertNotIn('private', '\n'.join(self.logs))

    def test_unready_native_window_times_out(self):
        self.runtime.auto_ready = False
        window = self.open()
        self.now += 16.0
        self.runtime.run(self.controller._watch_timer)
        self.assertTrue(window.closed)

    def test_escape_cleanup_and_stop_are_idempotent(self):
        window = self.open()
        window.on_request(request())
        self.runtime.escape()
        self.assertTrue(window.closed)
        self.assertEqual(window.destroyed, 1)
        self.assertEqual(self.runtime.timers, {})
        self.controller.stop()
        self.controller.stop()
        self.assertIsNone(self.runtime.toggle)
        self.assertIsNone(self.runtime.escape)
        self.assertFalse(self.runtime.mods_registered)

    def test_late_loader_ready_after_stop_does_not_subscribe(self):
        self.runtime.immediate_ready = False
        self.assertTrue(self.controller.start())
        self.controller.stop()
        self.runtime.ready_callback()
        self.assertIsNone(self.runtime.toggle)
        self.assertFalse(self.controller.open())

    def test_previous_activation_cannot_complete_a_new_start(self):
        self.runtime.immediate_ready = False
        self.assertTrue(self.controller.start())
        stale = self.runtime.ready_callback
        self.controller.stop()
        self.assertTrue(self.controller.start())
        stale()
        self.assertIsNone(self.runtime.toggle)
        self.runtime.ready_callback()
        self.assertIsNotNone(self.runtime.toggle)

    def test_provider_error_replaces_data_with_sanitized_error_envelope(self):
        window = self.open()

        def invalid_configuration():
            raise ValueError('PRIVATE_GOAL')

        self.provider_hook = invalid_configuration
        window.on_request(request('ui-2'))
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(window.payloads[-1], {
            'protocol': 1, 'source': 'game', 'status': 'error',
            'request_id': 'ui-2', 'error': 'data_unavailable'})
        self.assertFalse(window.closed)
        self.assertNotIn('PRIVATE_GOAL', '\n'.join(self.logs))
        self.provider_hook = None
        window.on_request(request('ui-3'))
        self.runtime.run(self.controller._request_timer)
        self.assertEqual(window.payloads[-1]['request_id'], 'ui-3')
        self.assertIn('summary', window.payloads[-1])

    def test_snapshot_size_is_bounded_before_native_publication(self):
        self.controller._snapshot_provider = lambda account, value: {
            'protocol': 1, 'source': 'game', 'request_id': value['request_id'],
            'history': 'a' * MAX_PAYLOAD_CHARS}
        window = self.open()
        self.assertEqual(window.payloads[0]['error'], 'data_unavailable')
        self.assertNotIn('history', window.payloads[0])


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


class Attributes(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class NativeSurfaceTests(unittest.TestCase):
    """Exercise our Wulf calls against narrow fakes, without shipping them."""

    def setUp(self):
        self.saved = {}
        self.key_event = Event()
        self.timers = {}
        self.next_timer = 0
        self.logs = []
        self.account = '88'
        self.created = []
        self.destroy_raises = False
        self.center_raises = False
        self.center_result = True
        owner = self

        def module(name, **values):
            self.saved[name] = sys.modules.get(name)
            instance = types.ModuleType(name)
            instance.__dict__.update(values)
            sys.modules[name] = instance
            return instance

        class Model(object):
            def __init__(self, properties, commands):
                self.values, self.commands = [], []
                self.expected_properties, self.expected_commands = properties, commands
                self._initialize()

            def _initialize(self):
                pass

            def _addStringProperty(self, name, value):
                self.values.append(value)

            def _addCommand(self, name):
                event = Event()
                self.commands.append(event)
                return event

            def _setString(self, index, value):
                self.values[index] = value

            def transaction(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class View(object):
            def __init__(self, settings):
                self.settings = settings

        class Window(object):
            def __init__(self, flags, content, layer, name, parent):
                self.flags, self.content, self.layer = flags, content, layer
                self.name, self.parent = name, parent
                self.proxy = object()
                self.windowStatus = 0
                self.focus = None
                self.center_calls = 0
                owner.created.append(self)

            def load(self):
                self.windowStatus = 1
                self._onReady()

            def show(self, focus):
                self.focus = focus

            def center(self):
                self.center_calls += 1
                if owner.center_raises:
                    raise RuntimeError('PRIVATE_POSITION_ERROR')
                return owner.center_result

            def destroy(self):
                if owner.destroy_raises:
                    raise RuntimeError('PRIVATE_NATIVE_ERROR')
                self.windowStatus = 3
                self.proxy = None

        def schedule(delay, callback):
            self.next_timer += 1
            self.timers[self.next_timer] = callback
            return self.next_timer

        parent = Attributes(proxy=object(), windowStatus=1)
        self.parent = parent
        module('openwg_gameface', on_ready=lambda callback: callback(),
               res_id_by_key=lambda key: 9001)
        module('frameworks', __path__=[])
        module('frameworks.wulf', ViewModel=Model, ViewSettings=Attributes,
               ViewFlags=Attributes(VIEW=1), WindowFlags=Attributes(WINDOW=2),
               WindowLayer=Attributes(TOP_WINDOW=10),
               WindowStatus=Attributes(LOADED=1, DESTROYING=2, DESTROYED=3))
        module('gui', __path__=[], InputHandler=Attributes(
            g_instance=Attributes(onKeyDown=self.key_event)))
        module('gui.impl', __path__=[])
        module('gui.impl.pub', ViewImpl=View, WindowImpl=Window)
        module('Keys', KEY_F8=8, KEY_ESCAPE=27)
        module('helpers', dependency=Attributes(instance=lambda key: Attributes(
            windowsManager=Attributes(getMainWindow=lambda: parent))))
        module('skeletons', __path__=[])
        module('skeletons.gui', __path__=[])
        module('skeletons.gui.impl', IGuiLoader=object)
        module('BigWorld', callback=schedule,
               cancelCallback=lambda timer: self.timers.pop(timer, None))
        self.controller = GamefaceController(
            lambda: self.account,
            lambda account, value: {'protocol': 1, 'source': 'game',
                                    'request_id': value['request_id']},
            self.logs.append)

    def tearDown(self):
        self.controller.stop()
        for name, previous in self.saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def key(self, value, repeated=False, down=True):
        self.key_event.fire(Attributes(
            key=value, isKeyDown=lambda: down,
            isRepeatedEvent=lambda: repeated))

    def test_native_window_model_transaction_and_command_cleanup(self):
        self.assertTrue(self.controller.start())
        self.key(8)
        window = self.created[-1]
        model = window.content.viewModel
        self.assertTrue(window.focus)
        self.assertEqual(window.parent, self.parent)
        self.assertEqual(len(model.values), model.expected_properties)
        self.assertEqual(len(model.commands), model.expected_commands)
        model.onRequest.fire(request('ui-1'))
        self.timers.pop(self.controller._request_timer)()
        self.assertEqual(json.loads(model.values[0])['request_id'], 'ui-1')
        model.onClose.fire({})
        self.assertEqual(window.windowStatus, 3)
        self.assertEqual(json.loads(model.values[0])['request_id'], 'closed')
        self.assertTrue(all(not command.handlers for command in model.commands))
        self.assertEqual(self.timers, {})
        self.controller.stop()
        self.assertEqual(self.key_event.handlers, [])

    def test_escape_independent_of_js_and_key_repeat_is_ignored(self):
        self.assertTrue(self.controller.start())
        self.key(8, repeated=True)
        self.key(8, down=False)
        self.assertEqual(self.created, [])
        self.key(8)
        self.key(8, repeated=True)
        window = self.created[-1]
        self.assertEqual(window.windowStatus, 1)
        self.key(27)
        self.assertEqual(window.windowStatus, 3)

    def test_native_destroy_failure_still_clears_personal_model_and_commands(self):
        self.assertTrue(self.controller.start())
        self.assertTrue(self.controller.open())
        model = self.created[-1].content.viewModel
        self.destroy_raises = True
        self.controller.close()
        self.assertEqual(json.loads(model.values[0]), {
            'protocol': 1, 'source': 'game', 'status': 'error',
            'request_id': 'closed', 'error': 'data_unavailable'})
        self.assertTrue(all(not command.handlers for command in model.commands))
        self.assertNotIn('PRIVATE_NATIVE_ERROR', '\n'.join(self.logs))

    def test_center_after_first_request_only_and_again_on_reopen(self):
        self.assertTrue(self.controller.start())
        self.key(8)
        window = self.created[-1]
        self.assertEqual(window.center_calls, 0)
        for identifier in ('ui-1', 'ui-2'):
            window.content.viewModel.onRequest.fire(request(identifier))
            self.timers.pop(self.controller._request_timer)()
            self.assertEqual(window.center_calls, 1)
            self.assertEqual(window.windowStatus, 1)
        self.controller.close()
        self.key(8)
        replacement = self.created[-1]
        replacement.content.viewModel.onRequest.fire(request('ui-1'))
        self.timers.pop(self.controller._request_timer)()
        self.assertEqual(replacement.center_calls, 1)

    def test_failed_center_is_nonfatal_and_not_retried(self):
        self.center_raises = True
        self.assertTrue(self.controller.start())
        self.key(8)
        window = self.created[-1]
        for identifier in ('ui-1', 'ui-2'):
            window.content.viewModel.onRequest.fire(request(identifier))
            self.timers.pop(self.controller._request_timer)()
            self.assertEqual(json.loads(window.content.viewModel.values[0])['request_id'], identifier)
        self.assertEqual(window.windowStatus, 1)
        self.assertEqual(window.center_calls, 1)
        self.assertTrue(any('window centering unavailable' in line for line in self.logs))
        self.assertNotIn('PRIVATE_POSITION_ERROR', '\n'.join(self.logs))

    def test_unloaded_parent_does_not_create_or_show_window(self):
        self.parent.proxy = None
        self.assertTrue(self.controller.start())
        self.assertFalse(self.controller.open())
        self.assertEqual(self.created, [])


if __name__ == '__main__':
    unittest.main()
