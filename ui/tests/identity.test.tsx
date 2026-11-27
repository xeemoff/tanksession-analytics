import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { SnapshotView } from '../src/App';
import { CoachCard } from '../src/Coach';
import { parseSnapshot, Snapshot } from '../src/contracts';
import { SnapshotController } from '../src/controller';
import { VehiclePicker } from '../src/VehiclePicker';
import { SettingsView } from '../src/Workspace';
import { SessionsView } from '../src/SummaryExtras';
import { FakeBridge } from './helpers';

function identitySnapshot(): Snapshot {
  const value = JSON.parse(readFileSync('../sample_data/ui/release.json', 'utf8')) as Snapshot;
  const key = 'type:507';
  value.selection.vehicle = key;
  value.vehicles = [{ name: key, label: 'Т-34', battles: value.summary.battles }];
  value.history.forEach(row => { row.vehicle = key; row.vehicle_label = 'Т-34'; });
  value.coach!.vehicle = key;
  value.coach!.vehicle_label = 'Т-34';
  value.coach!.goal_suggestions?.forEach(goal => { goal.vehicle = key; });
  value.goals.forEach(goal => { goal.vehicle = key; goal.vehicle_label = 'Т-34'; });
  value.insights!.tanks.forEach(row => { row.label = key; row.vehicle_label = 'Т-34'; });
  value.workspace!.preferences.vehicle = key;
  value.workspace!.goals = [{ vehicle: key, vehicle_label: 'Т-34', window: 10, target_avg_damage: 1000 }];
  return value;
}

test('friendly vehicle labels do not replace selectors in the snapshot contract', () => {
  const value = parseSnapshot(identitySnapshot());
  assert.equal(value.selection.vehicle, 'type:507');
  assert.equal(value.vehicles[0].name, 'type:507');
  assert.equal(value.vehicles[0].label, 'Т-34');
  assert.equal(value.history[0].vehicle, 'type:507');
  assert.equal(value.goals[0].vehicle, 'type:507');
  assert.equal(value.coach!.vehicle, 'type:507');
  assert.equal(value.insights!.tanks[0].label, 'type:507');
  assert.equal(value.workspace!.goals[0].vehicle, 'type:507');
});

test('all optional vehicle labels are validated before rendering', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.vehicles[0].label = 1 as never; },
    value => { value.history[0].vehicle_label = {} as never; },
    value => { value.goals[0].vehicle_label = null as never; },
    value => { value.coach!.vehicle_label = 'x'.repeat(129); },
    value => { value.insights!.tanks[0].vehicle_label = true as never; },
    value => { value.workspace!.goals[0].vehicle_label = [] as never; }
  ];
  for (const corrupt of corruptions) {
    const value = identitySnapshot(); corrupt(value); assert.throws(() => parseSnapshot(value));
  }
});

test('picker, history, coach, goals and saved filter captions display the supplied label', () => {
  const value = parseSnapshot(identitySnapshot());
  const views = [
    <VehiclePicker vehicles={value.vehicles} selected={value.selection.vehicle} disabled={false} onSelect={() => {}} />,
    <SnapshotView snapshot={value} section="history" />,
    <SnapshotView snapshot={value} section="dynamics" />,
    <CoachCard coach={value.coach!} />,
    <SettingsView snapshot={value} busy={false} onCommand={() => {}} />
  ];
  for (const view of views) {
    const html = renderToStaticMarkup(view);
    assert.match(html, /Т-34/);
    assert(!html.includes('type:507'));
  }
});

test('display labels cannot silently redirect a filter or goal to another selector', () => {
  const bridge = new FakeBridge();
  const control = new SnapshotController(bridge, () => {});
  control.start(); bridge.ready();
  const value = identitySnapshot();
  value.request_id = bridge.requests[0].request_id;
  bridge.receive(value);
  control.request({ vehicle: 'type:507', window: 30 });
  assert.equal(bridge.requests[1].vehicle, 'type:507');
  value.request_id = bridge.requests[1].request_id;
  bridge.receive(value);
  control.command({ action: 'save_goal', goal: { vehicle: 'type:507', window: 10, target_avg_damage: 1700 } });
  const request = bridge.requests[2];
  assert.equal(request.action, 'save_goal');
  assert.equal(request.goal?.vehicle, 'type:507');
  assert(!JSON.stringify(request).includes('Т-34'));
  control.dispose();
});

function ambiguousSnapshot(): Snapshot {
  return parseSnapshot(readFileSync('../sample_data/ui/identity_ambiguous.json', 'utf8'));
}

test('real ambiguous-identity payload keeps observed history but no comparison or records', () => {
  const value = ambiguousSnapshot();
  assert.equal(value.coach!.status, 'identity_ambiguous');
  assert(value.coach!.battles > 0);
  assert.equal(value.coach!.comparison, null);
  assert.equal(value.sessions!.comparison.status, 'identity_ambiguous');
  assert(value.sessions!.items.length > 0);
  assert.equal(value.goals[0].status, 'identity_ambiguous');
  const coach = renderToStaticMarkup(<CoachCard coach={value.coach!} />);
  assert.match(coach, /Название связано с разной техникой/);
  assert.match(coach, /Старая история сохранена/);
  for (const hidden of ['coach-records', 'coach-delta', 'coach-remaining', 'Нужно ещё', 'Лучший бой']) {
    assert(!coach.includes(hidden));
  }
  const sessions = renderToStaticMarkup(<SessionsView snapshot={value} />);
  assert.match(sessions, /подтверждённым идентификатором/);
  assert(!sessions.includes('session-comparison'));
  const goals = renderToStaticMarkup(<SnapshotView snapshot={value} section="dynamics" />);
  assert.match(goals, /Техника не определена однозначно/);
  assert(!goals.includes('role="progressbar"'));
  assert(!goals.includes('Цель достигнута'));

  // Additive protocol extensions can arrive independently: a host exposing
  // sessions without the coach still must not revive the legacy comparison.
  delete value.coach;
  delete value.insights;
  const legacy = renderToStaticMarkup(<SnapshotView snapshot={parseSnapshot(value)} section="dynamics" />);
  assert.match(legacy, /Название связано с разной техникой/);
  assert(!legacy.includes('class="comparison-row"'));
  assert(!legacy.includes('Для сравнения двух периодов нужно ещё'));
});

test('ambiguous identity cannot carry numerical records, verdicts or reward flags', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.coach!.records.best_damage = 100; },
    value => { value.coach!.records.current_window_avg = 100; },
    value => { value.coach!.records.new_damage_record = true; },
    value => { value.coach!.records.new_window_record = true; },
    value => { value.coach!.comparison = identitySnapshot().coach!.comparison; },
    value => { value.sessions!.comparison.current_average = 100; },
    value => { value.sessions!.comparison.delta_average = 0; }
  ];
  for (const corrupt of corruptions) {
    const value = ambiguousSnapshot(); corrupt(value); assert.throws(() => parseSnapshot(value));
  }
});
