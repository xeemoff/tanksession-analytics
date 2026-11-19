import assert from 'node:assert/strict';
import test from 'node:test';
import { GamefaceBridge } from '../src/bridge';
import { snapshot } from './helpers';

test('native bridge waits for DOM and cleans callback id zero', async () => {
  const listeners = new Map<string, (...args: unknown[]) => void>();
  const removals: number[] = [];
  const requests: unknown[] = [];
  let received = 0;
  let ready = 0;
  const host = { isDomBuilt: false,
    engine: { whenReady: Promise.resolve(), on: (name: string, fn: (...args: unknown[]) => void) => listeners.set(name, fn),
      off: (name: string, fn: (...args: unknown[]) => void) => { if (listeners.get(name) === fn) listeners.delete(name); } },
    viewEnv: { addDataChangedCallback: () => 0, removeDataChangedCallback: (id: number) => { removals.push(id); } },
    model: { payload: { value: JSON.stringify(snapshot()) }, onRequest: { value: (args: unknown) => requests.push(args) }, onClose: () => {} }
  };
  const bridge = new GamefaceBridge(host);
  const dispose = bridge.start(() => { received++; }, error => { throw error; }, () => { ready++; });
  await Promise.resolve();
  assert.equal(received, 0);
  assert.equal(ready, 0);
  listeners.get('self.onDomBuilt')?.();
  assert.equal(received, 1);
  assert.equal(ready, 1);
  bridge.request({ protocol: 1, request_id: 'ui-1', vehicle: '', window: 10 });
  assert.equal(requests.length, 1);
  dispose();
  assert.deepEqual(removals, [0]);
  assert.equal(listeners.size, 0);
});
test('an unavailable native bridge never substitutes demo data', () => {
  const bridge = new GamefaceBridge({});
  let received = false;
  let error = '';
  bridge.start(() => { received = true; }, value => { error = value.message; }, () => {});
  assert.equal(received, false);
  assert.match(error, /недоступно/);
});
test('disposing before engine readiness prevents a late subscription', async () => {
  let resolve: () => void = () => {};
  let subscriptions = 0;
  const bridge = new GamefaceBridge({ engine: {
    whenReady: new Promise<void>(done => { resolve = done; }), on: () => { subscriptions++; }, off: () => {}
  } });
  const dispose = bridge.start(() => {}, () => {}, () => {});
  dispose(); resolve(); await Promise.resolve();
  assert.equal(subscriptions, 0);
});

test('native data errors clear current data while stale errors are ignored', async () => {
  const listeners = new Map<string, (...args: unknown[]) => void>();
  const errors: string[] = [];
  const host = { isDomBuilt: true,
    engine: { whenReady: Promise.resolve(), on: (name: string, fn: (...args: unknown[]) => void) => listeners.set(name, fn),
      off: (name: string) => { listeners.delete(name); } },
    viewEnv: { addDataChangedCallback: () => 7, removeDataChangedCallback: () => {} },
    model: { payload: '', onRequest: () => {}, onClose: () => {} }
  };
  const bridge = new GamefaceBridge(host);
  const dispose = bridge.start(() => {}, error => errors.push(error.message), () => {});
  await Promise.resolve();
  bridge.request({ protocol: 1, request_id: 'ui-2', vehicle: '', window: 10 });
  const error = { protocol: 1, source: 'game', status: 'error', request_id: 'ui-1', error: 'data_unavailable' };
  host.model.payload = JSON.stringify(error); listeners.get('viewEnv.onDataChanged')?.();
  assert.equal(errors.length, 0);
  host.model.payload = JSON.stringify({ ...error, request_id: 'ui-2' }); listeners.get('viewEnv.onDataChanged')?.();
  assert.match(errors[0], /goals.json/);
  host.model.payload = JSON.stringify({ ...error, request_id: 'closed' }); listeners.get('viewEnv.onDataChanged')?.();
  assert.match(errors[1], /закрыто/);
  dispose();
});
