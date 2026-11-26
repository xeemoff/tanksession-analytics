import assert from 'node:assert/strict';
import test from 'node:test';
import { vehicleLabel } from '../src/vehicleLabel';
test('known T-34 alias and unknown IDs', () => {
  assert.equal(vehicleLabel('ussr:R04_T-34'), 'Т-34');
  assert.equal(vehicleLabel('unknown'), 'Неизвестная техника');
  assert.equal(vehicleLabel('other:future_vehicle'), 'other:future_vehicle');
  assert.equal(vehicleLabel('IS-7'), 'IS-7');
});
