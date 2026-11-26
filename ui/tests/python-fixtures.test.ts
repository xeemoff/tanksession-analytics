import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { parseSnapshot } from '../src/contracts';

test('Python-generated snapshots satisfy the frontend protocol', () => {
  for (const name of ['demo', 'empty', 'incomplete', 'account_unavailable', 'release',
    'coach_ready', 'coach_collecting', 'coach_incomplete', 'coach_record', 'coach_mixed_modes']) {
    const raw = readFileSync('../sample_data/ui/' + name + '.json', 'utf8');
    const snapshot = parseSnapshot(raw);
    assert.equal(snapshot.protocol, 1);
  }
  const filters: unknown[] = JSON.parse(readFileSync('../sample_data/ui/demo_filters.json', 'utf8'));
  assert(filters.length > 1);
  filters.forEach(raw => parseSnapshot(raw));
});
