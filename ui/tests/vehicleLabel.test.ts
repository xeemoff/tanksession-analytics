import assert from 'node:assert/strict';
import test from 'node:test';
import { vehicleLabel, vehicleLabelFor } from '../src/vehicleLabel';
test('known T-34 alias and unknown IDs', () => {
  assert.equal(vehicleLabel('ussr:R04_T-34'), 'Т-34');
  assert.equal(vehicleLabel('unknown'), 'Неизвестная техника');
  assert.equal(vehicleLabel('other:future_vehicle'), 'other:future_vehicle');
  assert.equal(vehicleLabel('IS-7'), 'IS-7');
});

test('stable selectors keep separate friendly labels and honest fallbacks', () => {
  assert.equal(vehicleLabel('type:507', 'Т-34'), 'Т-34');
  assert.equal(vehicleLabel('type:507'), 'Техника #507');
  assert.equal(vehicleLabel('name:ussr:R04_T-34'), 'Т-34');
  assert.equal(vehicleLabel('name:other:future_vehicle'), 'other:future_vehicle');
  assert.equal(vehicleLabel('type:507', 'ussr:R04_T-34'), 'Т-34');
  assert.equal(vehicleLabel('IS-7', ''), 'IS-7');
  const vehicles = [{ name: 'type:507', label: 'Т-34' }, { name: 'type:508', label: 'Т-34' }];
  assert.equal(vehicleLabelFor('type:507', vehicles), 'Т-34');
  assert.equal(vehicleLabelFor('type:509', vehicles), 'Техника #509');
  assert.deepEqual(vehicles.map(item => item.name), ['type:507', 'type:508']);
});
