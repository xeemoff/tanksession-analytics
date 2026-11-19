import assert from 'node:assert/strict';
import test from 'node:test';
import { SnapshotController } from '../src/controller';
import { FakeBridge, snapshot } from './helpers';

test('waits for ready and ignores an older result after a filter change', () => {
  const bridge = new FakeBridge();
  const controller = new SnapshotController(bridge, () => {});
  controller.start();
  assert.equal(bridge.requests.length, 0);
  bridge.ready();
  const old = bridge.requests[0];
  controller.request({ window: 30, vehicle: 'IS-7' });
  const current = bridge.requests[1];
  bridge.receive(snapshot(old.request_id));
  assert.equal(controller.state.phase, 'loading');
  assert.equal(controller.state.snapshot, null);
  bridge.receive({ ...snapshot(current.request_id), selection: { window: 30, vehicle: 'IS-7' } });
  assert.equal(controller.state.selection.window, 30);
  assert.equal(controller.state.phase, 'ready');
  controller.dispose();
});
test('a failed refresh does not present stale metrics as current data', () => {
  const bridge = new FakeBridge();
  const controller = new SnapshotController(bridge, () => {});
  controller.start(); bridge.ready();
  bridge.receive(snapshot(bridge.requests[0].request_id));
  controller.request();
  bridge.report(new Error('unavailable'));
  assert.equal(controller.state.phase, 'error');
  assert.equal(controller.state.snapshot, null);
  assert.equal(controller.state.message, 'unavailable');
  controller.dispose();
});
test('closing unsubscribes and late callbacks cannot reopen the panel', () => {
  const bridge = new FakeBridge();
  const controller = new SnapshotController(bridge, () => {});
  controller.start(); bridge.ready(); controller.close();
  bridge.receive(snapshot(bridge.requests[0].request_id));
  assert.equal(controller.state.phase, 'closed');
  assert.equal(bridge.disposed, 1);
  assert.equal(bridge.closed, 1);
  controller.dispose();
  assert.equal(bridge.disposed, 1);
});
test('connection timeout produces an explicit error', async () => {
  const bridge = new FakeBridge();
  const controller = new SnapshotController(bridge, () => {}, 5);
  controller.start();
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(controller.state.phase, 'error');
  assert.match(controller.state.message, /вовремя/);
  controller.dispose();
});
