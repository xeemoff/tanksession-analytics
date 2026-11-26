import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseSnapshot, Snapshot } from '../src/contracts';
import { SnapshotController } from '../src/controller';
import { HttpBridge } from '../src/bridge';
import { ExtendedMetricsView, SessionsView } from '../src/SummaryExtras';
import { OperationNotice, SettingsView } from '../src/Workspace';
import { FakeBridge, snapshot } from './helpers';

function releaseSnapshot(id = 'initial'): Snapshot {
  const value = snapshot(id);
  value.workspace = { version: 1, can_edit: true, preferences: {
    vehicle: '', window: 10, tab: 'progress', density: 'normal', contrast: 'standard'
  }, goals: [], operation: null };
  value.pagination = { page: 0, page_size: 5, pages: 4, total: 20 };
  value.history = Array.from({ length: 5 }, (_, i) => ({ ...value.history[0], timestamp: 1800000000 - i,
    kills: 0, shots: null, direct_hits: null, penetrations: null, survived: false, xp_base: 0,
    credits_gross: 100, credits_net: -50, map: null }));
  value.metrics = { version: 1,
    fields: { kills: { samples: 1, average: 0 }, xp_base: { samples: 0, average: null },
      credits_gross: { samples: 1, average: 100 }, credits_net: { samples: 1, average: -50 } },
    survival: { samples: 1, survived: 0, rate: 0 }, accuracy: { samples: 0, shots: 0, hits: 0, rate: null },
    penetration: { samples: 0, hits: 0, penetrations: 0, rate: null }, maps: [] };
  value.sessions = { version: 1, gap_minutes: 60, basis: 'received_at', items: [], comparison: {
    status: 'ready', minimum_battles: 10, current_battles: 10, previous_battles: 10,
    current_average: 0, previous_average: 1, current_median: 0, previous_median: 1, delta_average: -1, delta_median: -1
  } };
  return value;
}

test('release boundary accepts zero, negative credit totals and older readonly snapshots', () => {
  assert.equal(parseSnapshot(snapshot()).workspace, undefined);
  const value = parseSnapshot(releaseSnapshot());
  assert.equal(value.history[0].survived, false);
  assert.equal(value.metrics!.fields.credits_net.average, -50);
  assert.equal(value.history[0].xp_base, 0);
});

test('release boundary rejects inconsistent pagination and malformed optional extensions', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.pagination!.total = 21; },
    value => { value.pagination!.page = 8; },
    value => { value.history[0].xp_base = -1; },
    value => { value.metrics!.survival.rate = 101; },
    value => { value.metrics!.fields.kills.samples = 21; },
    value => { value.sessions!.comparison.current_battles = 9; },
    value => { value.workspace!.operation = { status: 'exported', code: 'csv_exported', filename: '../private.csv' }; },
    value => { value.workspace!.preferences.tab = 'unexpected' as never; },
    value => { value.workspace!.goals = [{ vehicle: 'IS-7', window: 9, target_avg_damage: 100 }]; }
  ];
  for (const corrupt of corruptions) {
    const value = releaseSnapshot(); corrupt(value); assert.throws(() => parseSnapshot(value));
  }
});

test('a pending mutation cannot be replaced by filters or duplicated by a second button press', () => {
  const bridge = new FakeBridge();
  const controller = new SnapshotController(bridge, () => {});
  controller.start(); bridge.ready();
  assert.equal(bridge.requests[0].action, 'initialize');
  bridge.receive(releaseSnapshot(bridge.requests[0].request_id));
  controller.command({ action: 'export_csv' });
  const command = bridge.requests[1];
  assert.equal(controller.state.phase, 'loading');
  controller.command({ action: 'export_csv' });
  controller.request({ vehicle: 'IS-7', window: 100 });
  assert.equal(bridge.requests.length, 2);
  bridge.receive(releaseSnapshot(command.request_id));
  controller.request({ vehicle: 'IS-7', window: 100 });
  assert.equal(bridge.requests.length, 3);
  assert.equal(bridge.requests[2].action, undefined);
  controller.dispose();
});

test('readonly sources do not dispatch mutations, and failed commands clear data', () => {
  const bridge = new FakeBridge(); const controller = new SnapshotController(bridge, () => {});
  controller.start(); bridge.ready(); bridge.receive(snapshot(bridge.requests[0].request_id));
  controller.command({ action: 'export_csv' }); assert.equal(bridge.requests.length, 1);
  bridge.receive(releaseSnapshot(bridge.requests[0].request_id));
  controller.command({ action: 'export_csv' });
  bridge.report(new Error('write unavailable'));
  assert.equal(controller.state.phase, 'error'); assert.equal(controller.state.snapshot, null);
  controller.dispose();
});

test('metrics render missing values separately from zero and sessions describe receipt grouping', () => {
  const value = releaseSnapshot();
  const metrics = renderToStaticMarkup(<ExtendedMetricsView snapshot={value} />);
  assert.match(metrics, /0,0%/); assert.match(metrics, /—/); assert.match(metrics, /Известно в 1 из 20/);
  const sessions = renderToStaticMarkup(<SessionsView snapshot={value} />);
  assert.match(sessions, /Сравнение двух сессий/); assert.match(sessions, /по времени получения/);
  assert.match(sessions, /не доказывает изменение навыка/);
  const legacy = renderToStaticMarkup(<SettingsView snapshot={snapshot()} busy={false} onCommand={() => {}} />);
  assert.match(legacy, /только для чтения/); assert(!legacy.includes('Сохранить CSV'));
});

test('export feedback escapes filenames and reports the local result without exposing identifiers', () => {
  const value = releaseSnapshot();
  value.workspace!.operation = { status: 'exported', code: 'csv_exported', filename: '<export>.csv', rows: 20 };
  const html = renderToStaticMarkup(<OperationNotice snapshot={value} />);
  assert.match(html, /&lt;export&gt;.csv/); assert.match(html, /Строк: 20/); assert(!html.includes('<export>'));
});

test('HTTP writes use the command endpoint, JSON and an explicit same-origin request header', () => {
  const original = globalThis.XMLHttpRequest;
  const calls: FakeXHR[] = [];
  class FakeXHR {
    method = ''; url = ''; body: string | null = null; timeout = 0;
    headers: Record<string, string> = {}; status = 200; responseText = ''; onload: (() => void) | null = null;
    onerror = null; ontimeout = null;
    constructor() { calls.push(this); }
    open(method: string, url: string) { this.method = method; this.url = url; }
    setRequestHeader(name: string, value: string) { this.headers[name] = value; }
    send(body: string | null) { this.body = body; }
    abort() {}
  }
  globalThis.XMLHttpRequest = FakeXHR as unknown as typeof XMLHttpRequest;
  try {
    const bridge = new HttpBridge('game'); const dispose = bridge.start(() => {}, error => { throw error; }, () => {});
    bridge.request({ protocol: 1, request_id: 'read', vehicle: 'IS-7', window: 10, page: 3 });
    assert.equal(calls[0].method, 'GET'); assert.match(calls[0].url, /page=3/); assert.equal(calls[0].body, null);
    bridge.request({ protocol: 1, request_id: 'write', vehicle: 'IS-7', window: 10, action: 'export_csv' });
    assert.equal(calls[1].method, 'POST'); assert.equal(calls[1].url, '/api/command');
    assert.equal(calls[1].headers['X-TankSession-Request'], '1');
    assert.equal(calls[1].headers['Content-Type'], 'application/json');
    assert.equal(JSON.parse(calls[1].body!).action, 'export_csv'); dispose();
  } finally { globalThis.XMLHttpRequest = original; }
});
