import assert from 'node:assert/strict';
import test from 'node:test';
import { getMode, parseSnapshot } from '../src/contracts';
import { snapshot } from './helpers';

test('accepts protocol 1 and preserves unknown values distinctly from zero', () => {
  const value = parseSnapshot(JSON.stringify(snapshot()));
  assert.equal(value.history[0].damage, 0);
  assert.equal(value.history[0].xp, null);
});
test('rejects malformed, unsupported and oversized snapshots at the boundary', () => {
  assert.throws(() => parseSnapshot('{broken'));
  assert.throws(() => parseSnapshot(' '.repeat(512 * 1024 + 1)));
  for (const raw of [{ ...snapshot(), protocol: 2 }, { ...snapshot(), source: 'remote' },
    { ...snapshot(), summary: { ...snapshot().summary, avg_damage: [] } },
    { ...snapshot(), summary: { ...snapshot().summary, battles: Number.MAX_SAFE_INTEGER + 1 } },
    { ...snapshot(), updated_at: 253402300800 },
    { ...snapshot(), history: [{ timestamp: 10, vehicle: 'x', outcome: 'victory', damage: 0, xp: 0 }] },
    { ...snapshot(), quality: { ...snapshot().quality, conflicts: -1 } }]) assert.throws(() => parseSnapshot(raw));
});
test('demo and local transport require explicit flags; native is the default', () => {
  assert.equal(getMode(''), 'gameface');
  assert.equal(getMode('?demo=0'), 'gameface');
  assert.equal(getMode('?demo=1'), 'demo');
  assert.equal(getMode('?local=1'), 'local');
});
