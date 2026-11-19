# -*- coding: utf-8 -*-
"""Optional, UNVERIFIED hangar window using the external OpenWG Gameface API.

Nothing here imports the game or the loader until start(). The controller can
be tested without native binaries; those tests do not establish compatibility
with a particular Lesta client. No client resources or loader code are bundled.
"""
import json
import sys
import time
import weakref

from .presentation import validate_request
from .recorder import _verified_account

try:
    _text_types = (str, unicode)
    _unicode_type = unicode
    _integer_types = (int, long)
except NameError:
    _text_types = (str,)
    _unicode_type = str
    _integer_types = (int,)

LAYOUT_KEY = 'mods/tanksession/Analytics/layoutID'
MOD_ID = 'ru.tanksession.analytics'
MAX_REQUEST_BYTES = 16384
MAX_PAYLOAD_CHARS = 512 * 1024
REQUEST_DELAY = 0.15
CONTEXT_CHECK_DELAY = 0.5
LOAD_TIMEOUT = 15.0


def _reject_constant(value):
    raise ValueError('Non-finite JSON number')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def decode_request(arguments):
    """Decode a single small command. Never accept identity from JavaScript."""
    getter = getattr(arguments, 'get', None)
    if not callable(getter):
        raise ValueError('Missing command arguments')
    payload = getter('payload')
    if isinstance(payload, bytes) and not isinstance(payload, _unicode_type):
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError('Request too large')
        payload = payload.decode('utf-8')
    if not isinstance(payload, _text_types) or len(payload) > MAX_REQUEST_BYTES:
        raise ValueError('Missing or oversized payload')
    if len(payload.encode('utf-8')) > MAX_REQUEST_BYTES:
        raise ValueError('Request too large')
    request = json.loads(payload, parse_constant=_reject_constant,
                         object_pairs_hook=_unique_object)
    if not isinstance(request, dict):
        raise ValueError('Request must be an object')
    return validate_request(request)


class NativeRuntime(object):
    """The small game-specific surface, kept separate from lifecycle policy."""

    def __init__(self):
        self.loader = None
        self.key_event = None
        self.key_handler = None
        self.mods_list = None

    def prepare(self, callback):
        import openwg_gameface
        if (not callable(getattr(openwg_gameface, 'on_ready', None)) or
                not callable(getattr(openwg_gameface, 'res_id_by_key', None))):
            raise RuntimeError('Unsupported Gameface loader API')
        self.loader = openwg_gameface
        # On MT the external loader can register resources and request a client
        # restart. TankSession neither patches its implementation nor restarts.
        openwg_gameface.on_ready(callback)

    def layout_id(self):
        return self.loader.res_id_by_key(LAYOUT_KEY)

    def bind_keys(self, toggle, close):
        from gui import InputHandler
        import Keys

        def handle(event):
            try:
                if not event.isKeyDown() or event.isRepeatedEvent():
                    return
                if event.key == Keys.KEY_F8:
                    toggle()
                elif event.key == Keys.KEY_ESCAPE:
                    close()
            except Exception:
                # An optional UI must never break the shared input dispatcher.
                return

        self.key_event = InputHandler.g_instance.onKeyDown
        self.key_handler = handle
        self.key_event += handle

    def unbind_keys(self):
        event, handler = self.key_event, self.key_handler
        self.key_event = self.key_handler = None
        if event is not None and handler is not None:
            event -= handler

    def register_mods_list(self, callback):
        # Never import/install another optional mod: some versions have import
        # side effects. Reuse a compatible API only if it is already loaded.
        if self.mods_list is not None:
            return
        module = sys.modules.get('gui.modsListApi')
        api = getattr(module, 'g_modsListApi', None)
        if (not callable(getattr(api, 'addModification', None)) or
                not callable(getattr(api, 'removeModification', None))):
            return
        api.addModification(id=MOD_ID, name='TankSession Analytics',
                            description=u'Статистика текущего аккаунта',
                            icon='', enabled=True, login=False, lobby=True,
                            callback=callback)
        self.mods_list = api

    def unregister_mods_list(self):
        api, self.mods_list = self.mods_list, None
        if api is not None:
            api.removeModification(MOD_ID)

    def schedule(self, delay, callback):
        import BigWorld
        return BigWorld.callback(delay, callback)

    def cancel(self, timer):
        import BigWorld
        BigWorld.cancelCallback(timer)

    def create(self, layout, payload, on_request, on_close, on_ready):
        from frameworks.wulf import (ViewModel, ViewSettings, ViewFlags,
                                     WindowFlags, WindowLayer, WindowStatus)
        from gui.impl.pub import ViewImpl, WindowImpl
        from helpers import dependency
        from skeletons.gui.impl import IGuiLoader

        parent = dependency.instance(IGuiLoader).windowsManager.getMainWindow()
        if (parent is None or parent.proxy is None or
                parent.windowStatus != WindowStatus.LOADED):
            raise RuntimeError('Main window not ready')

        class SnapshotModel(ViewModel):
            def __init__(self):
                self.onRequest = self.onClose = None
                super(SnapshotModel, self).__init__(properties=1, commands=2)

            def _initialize(self):
                super(SnapshotModel, self)._initialize()
                self._addStringProperty('payload', payload)
                self.onRequest = self._addCommand('onRequest')
                self.onClose = self._addCommand('onClose')
                self.onRequest += on_request
                self.onClose += on_close

            def setPayload(self, value):
                self._setString(0, value)

            def unbind(self):
                for name, handler in (('onRequest', on_request),
                                      ('onClose', on_close)):
                    command = getattr(self, name, None)
                    if command is not None:
                        try:
                            command.__isub__(handler)
                        except Exception:
                            pass
                        setattr(self, name, None)

        class SnapshotView(ViewImpl):
            def __init__(self, model):
                self._snapshot_model = model
                super(SnapshotView, self).__init__(ViewSettings(
                    layoutID=layout, flags=ViewFlags.VIEW, model=model))

            @property
            def viewModel(self):
                return self._snapshot_model

        class SnapshotWindow(WindowImpl):
            def __init__(self, content):
                self.snapshot_ready = False
                super(SnapshotWindow, self).__init__(
                    WindowFlags.WINDOW, content=content,
                    layer=WindowLayer.TOP_WINDOW,
                    name=str('TankSessionAnalytics'), parent=parent)

            def _onReady(self):
                try:
                    if on_ready():
                        self.snapshot_ready = True
                        self.show(True)
                except Exception:
                    on_close()

        model = SnapshotModel()
        try:
            window = SnapshotWindow(SnapshotView(model))
        except Exception:
            model.unbind()
            raise
        return NativeWindow(window, model, WindowStatus)


class NativeWindow(object):
    def __init__(self, window, model, statuses):
        self.window, self.model, self.statuses = window, model, statuses

    def load(self):
        self.window.load()

    def ready(self):
        return self.window.snapshot_ready

    def alive(self):
        status = self.window.windowStatus
        if status in (self.statuses.DESTROYING, self.statuses.DESTROYED):
            return False
        return not self.ready() or self.window.proxy is not None

    def publish(self, payload):
        with self.model.transaction() as model:
            model.setPayload(payload)

    def close(self):
        # Clear personal data before destruction too: a native failure must not
        # leave a populated, disconnected window from the previous account.
        try:
            self.publish(json.dumps({'protocol': 1, 'source': 'game',
                                     'status': 'error', 'request_id': 'closed',
                                     'error': 'data_unavailable'}))
        except Exception:
            pass
        try:
            self.model.unbind()
        finally:
            self.window.destroy()


class GamefaceController(object):
    """Own one window and never carry an account across a context change.

    context_provider returns a freshly verified account only in the hangar.
    snapshot_provider accepts that account and the validated request. Native
    callbacks are coalesced: the most recent valid request always gets a reply.
    """

    def __init__(self, context_provider, snapshot_provider, log, runtime=None,
                 clock=None):
        self._context_provider = context_provider
        self._snapshot_provider = snapshot_provider
        self._log = log
        self._runtime = runtime if runtime is not None else NativeRuntime()
        self._clock = clock if clock is not None else time.time
        self._active = False
        self._ready = False
        self._layout = None
        self._window = None
        self._account = None
        self._generation = 0
        self._activation = 0
        self._load_started = 0.0
        self._request_timer = None
        self._watch_timer = None
        self._queued_request = None
        self._last_request = None
        self._reported = set()

    def _report(self, key, message, error=None):
        if key in self._reported:
            return
        self._reported.add(key)
        if error is not None:
            message += ' (' + type(error).__name__ + ')'
        self._log('Gameface: ' + message)

    def _current_account(self):
        try:
            return _verified_account(self._context_provider())
        except Exception:
            return None

    def start(self):
        if self._active:
            return True
        self._active = True
        self._activation += 1
        activation = self._activation
        owner = weakref.ref(self)

        def ready():
            controller = owner()
            if (controller is not None and controller._active and
                    controller._activation == activation):
                controller._on_loader_ready()

        try:
            self._runtime.prepare(ready)
            return self._active
        except Exception as error:
            self._report('loader', 'optional loader unavailable; UI disabled', error)
            self.stop()
            return False

    def _on_loader_ready(self):
        if not self._active or self._ready:
            return
        try:
            layout = self._runtime.layout_id()
            if (isinstance(layout, bool) or not isinstance(layout, _integer_types)
                    or layout < 0):
                raise RuntimeError('Layout is not registered')
            self._layout = layout
            # Keep an independent close path even if frontend initialization
            # fails. Missing input capability disables the optional window.
            self._runtime.bind_keys(self.toggle, self.close)
            self._ready = True
            self.on_hangar()
            self._report('ready', 'experimental hangar window available on F8')
        except Exception as error:
            self._report('resources', 'window capability unavailable', error)
            self.stop()

    def on_hangar(self):
        if not self._active or not self._ready:
            return
        try:
            self._runtime.register_mods_list(self.toggle)
        except Exception as error:
            self._report('mods_list', 'optional mods-list button unavailable', error)

    def _authorized(self, generation):
        return (self._active and self._window is not None and
                generation == self._generation and self._account is not None and
                self._current_account() == self._account)

    def toggle(self, *args, **kwargs):
        if self._window is not None:
            self.close()
            return False
        return self.open()

    def open(self):
        if not self._active or not self._ready:
            return False
        if self._window is not None:
            return True
        account = self._current_account()
        if account is None:
            return False
        self._generation += 1
        generation = self._generation
        self._account = account
        request = validate_request(None)
        try:
            payload = self._encode_snapshot(account, request)
            if self._current_account() != account:
                self.close()
                return False
            self._last_request = request
            self._load_started = self._clock()
            self._window = self._runtime.create(
                self._layout, payload,
                lambda arguments: self._request(arguments, generation),
                lambda *args, **kwargs: self._close_generation(generation),
                lambda: self._window_ready(generation))
            # Assign before load: a ready/close callback may be synchronous.
            self._window.load()
            if not self._authorized(generation):
                self.close()
                return False
            self._schedule_watch(generation)
            return True
        except Exception as error:
            self._report('open', 'window could not be opened', error)
            self.close()
            return False

    def _encode_snapshot(self, account, request):
        try:
            snapshot = self._snapshot_provider(account, request)
            if (not isinstance(snapshot, dict) or snapshot.get('source') != 'game'
                    or snapshot.get('request_id') != request['request_id']):
                raise ValueError('Invalid snapshot envelope')
            payload = json.dumps(snapshot, ensure_ascii=True, allow_nan=False,
                                 separators=(',', ':'))
            if len(payload) > MAX_PAYLOAD_CHARS:
                raise ValueError('Snapshot too large')
            return payload
        except Exception as error:
            self._report('data', 'snapshot preparation failed', error)
            # The JS bridge treats this envelope as an error and discards its
            # previous snapshot. No exception text or stale data crosses over.
            return json.dumps({'protocol': 1, 'source': 'game', 'status': 'error',
                               'request_id': request['request_id'],
                               'error': 'data_unavailable'})

    def _window_ready(self, generation):
        if self._authorized(generation):
            return True
        self._close_generation(generation)
        return False

    def _close_generation(self, generation):
        if generation == self._generation:
            self.close()

    def _request(self, arguments, generation):
        if not self._authorized(generation):
            self._close_generation(generation)
            return
        try:
            request = decode_request(arguments)
            self._queue(request, generation)
        except Exception as error:
            # Never log payloads, account IDs or exception messages from a mod.
            self._report('request', 'invalid UI request rejected', error)

    def _queue(self, request, generation):
        self._queued_request = request
        if self._request_timer is None:
            try:
                self._request_timer = self._runtime.schedule(
                    REQUEST_DELAY, lambda: self._deliver(generation))
            except Exception as error:
                self._report('schedule', 'UI callback scheduling unavailable', error)
                self.close()

    def _deliver(self, generation):
        if generation != self._generation:
            return
        self._request_timer = None
        request, self._queued_request = self._queued_request, None
        if not self._authorized(generation):
            self.close()
            return
        if request is None:
            return
        try:
            payload = self._encode_snapshot(self._account, request)
            # A provider can re-enter game code; recheck before crossing into JS.
            if not self._authorized(generation):
                self.close()
                return
            self._window.publish(payload)
            self._last_request = request
        except Exception as error:
            self._report('snapshot', 'snapshot delivery failed; window closed', error)
            self.close()

    def refresh(self):
        generation = self._generation
        if not self._authorized(generation):
            if self._window is not None:
                self.close()
            return
        # Preserve a newer filter request and its ID if results arrived while
        # that request was waiting. Unsolicited updates reuse the current ID.
        self._queue(self._queued_request or self._last_request, generation)

    def _schedule_watch(self, generation):
        self._watch_timer = self._runtime.schedule(
            CONTEXT_CHECK_DELAY, lambda: self._watch(generation))

    def _watch(self, generation):
        if generation != self._generation:
            return
        self._watch_timer = None
        try:
            if (not self._authorized(generation) or not self._window.alive() or
                    (not self._window.ready() and
                     self._clock() - self._load_started > LOAD_TIMEOUT)):
                self.close()
                return
            # Only checks lifecycle/identity; no journal scan or JSON snapshot.
            self._schedule_watch(generation)
        except Exception as error:
            self._report('watch', 'window lifecycle unavailable', error)
            self.close()

    def close(self, *args, **kwargs):
        self._generation += 1
        window, self._window = self._window, None
        self._account = self._queued_request = self._last_request = None
        for name in ('_request_timer', '_watch_timer'):
            timer = getattr(self, name)
            setattr(self, name, None)
            if timer is not None:
                try:
                    self._runtime.cancel(timer)
                except Exception:
                    pass
        if window is not None:
            try:
                # Destroy instead of hiding: a hidden TOP_WINDOW may continue
                # to obstruct native dialogs and retain a previous account.
                window.close()
            except Exception as error:
                self._report('close', 'native window cleanup failed', error)

    def stop(self):
        self._activation += 1
        self._active = self._ready = False
        self.close()
        for cleanup in (self._runtime.unbind_keys,
                        self._runtime.unregister_mods_list):
            try:
                cleanup()
            except Exception:
                pass
