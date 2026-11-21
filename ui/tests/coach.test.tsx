import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { CoachCard } from '../src/Coach';
import { Coach, parseSnapshot } from '../src/contracts';

function fixture(name: string) { return JSON.parse(readFileSync('../sample_data/ui/' + name + '.json', 'utf8')); }
function render(name: string): string {
  const value = parseSnapshot(fixture(name));
  return renderToStaticMarkup(<CoachCard coach={value.coach as Coach} />);
}

test('coach explains opposing mean and median instead of claiming a skill gain', () => {
  const html = render('coach_ready');
  assert(html.includes('Средний урон в этой выборке выше'));
  assert(html.includes('+810,0 урона (+81,0%)'));
  assert(html.includes('Медиана урона'));
  assert(html.includes('−100,0') || html.includes('-100,0'));
  assert(html.includes('Среднее и медиана изменились в разные стороны'));
  assert(html.includes('Два непересекающихся периода'));
});

test('one saved result is a baseline with nineteen battles remaining', () => {
  const html = render('coach_collecting');
  assert(html.includes('data-testid="coach-remaining">19'));
  assert(html.includes('Первая запись — точка отсчёта'));
  assert(!html.includes('Новый рекорд'));
  assert(!html.includes('coach-delta'));
  assert(html.includes('data-testid="coach-best-window">—'));
});

test('missing damage and mixed battle types produce no period verdict', () => {
  const incomplete = render('coach_incomplete');
  assert(incomplete.includes('Для вывода не хватает значений урона'));
  assert(!incomplete.includes('coach-delta'));
  const mixed = render('coach_mixed_modes');
  assert(mixed.includes('В этих периодах разные типы боёв'));
  assert(!mixed.includes('coach-delta'));
  assert(!mixed.includes('Нужно ещё'));
});

test('record cards distinguish strict new records, zero damage and missing values', () => {
  const html = render('coach_record');
  assert.equal((html.match(/Новый рекорд/g) || []).length, 2);
  assert(html.includes('data-testid="coach-best-damage">3 500'));
  const value = parseSnapshot(fixture('coach_collecting'));
  const coach = value.coach as Coach;
  coach.records.best_damage = 0;
  coach.records.latest_damage = 0;
  const zero = renderToStaticMarkup(<CoachCard coach={coach} />);
  assert(zero.includes('data-testid="coach-best-damage">0'));
  assert(zero.includes('data-testid="coach-best-window">—'));
});

test('coach rejects inconsistent counts, missing metrics, flags and unsupported versions', () => {
  const changes: Array<(value: ReturnType<typeof fixture>) => void> = [
    value => { value.coach = null; },
    value => { value.coach.version = 2; },
    value => { value.coach.window = 30; },
    value => { value.coach.remaining_battles = 5; },
    value => { value.coach.coverage.current_damage = 11; },
    value => { value.coach.coverage.current_battles = 9; },
    value => { value.coach.comparison = null; },
    value => { value.coach.comparison.current_median = -1; },
    value => { value.coach.comparison.delta_percent = Infinity; },
    value => { value.coach.records.new_damage_record = 'true'; },
    value => { value.coach.records.previous_best_damage = null; },
    value => { value.coach.records.new_window_record = true; value.coach.records.previous_best_window_avg = null; },
    value => { delete value.coach.records.latest_damage; },
    value => { value.coach.status = 'incomplete'; },
  ];
  for (const change of changes) {
    const value = fixture('coach_ready');
    change(value);
    assert.throws(() => parseSnapshot(value));
  }
  const oldHost = fixture('coach_ready');
  delete oldHost.coach;
  assert.doesNotThrow(() => parseSnapshot(oldHost));
});

test('mixed and unknown vehicle selections cannot smuggle aggregate coach values', () => {
  const value = fixture('demo');
  assert.equal(parseSnapshot(value).coach?.status, 'choose_vehicle');
  value.coach.records.best_damage = 10;
  assert.throws(() => parseSnapshot(value));
  const escaped = fixture('coach_collecting');
  escaped.coach.vehicle = '<script>alert(1)</script>';
  escaped.vehicles[0].name = escaped.coach.vehicle;
  escaped.history[0].vehicle = escaped.coach.vehicle;
  const html = renderToStaticMarkup(<CoachCard coach={parseSnapshot(escaped).coach as Coach} />);
  assert(!html.includes('<script>'));
  assert(html.includes('&lt;script&gt;'));
});

test('coach scope follows the selected machine and permits only the documented automatic scope', () => {
  const automatic = fixture('coach_ready');
  assert.equal(parseSnapshot(automatic).coach?.vehicle, automatic.vehicles[0].name);
  automatic.selection.vehicle = 'Another tank';
  assert.throws(() => parseSnapshot(automatic));
  const unknown = fixture('coach_ready');
  unknown.selection.vehicle = unknown.coach.vehicle = unknown.vehicles[0].name = 'unknown';
  assert.throws(() => parseSnapshot(unknown));
  const mixed = fixture('coach_ready');
  mixed.vehicles.push({ name: 'Another tank', battles: 5 });
  assert.throws(() => parseSnapshot(mixed));

  const unknownGuard = fixture('demo');
  unknownGuard.selection.vehicle = 'unknown';
  assert.equal(parseSnapshot(unknownGuard).coach?.status, 'choose_vehicle');
  const unavailable = fixture('account_unavailable');
  unavailable.selection.vehicle = 'Previously selected tank';
  assert.doesNotThrow(() => parseSnapshot(unavailable));
  unavailable.coach = fixture('coach_ready').coach;
  assert.throws(() => parseSnapshot(unavailable));
  const empty = fixture('empty');
  empty.selection.vehicle = empty.coach.vehicle = 'No saved battles';
  assert.doesNotThrow(() => parseSnapshot(empty));
});

test('record maxima cannot contradict their latest result or an earlier record', () => {
  const badWindow = fixture('coach_record');
  badWindow.coach.records.current_window_avg = 100;
  assert.throws(() => parseSnapshot(badWindow));
  const badDamage = fixture('coach_record');
  badDamage.coach.records.best_damage = 0;
  assert.throws(() => parseSnapshot(badDamage));
  const falseFlag = fixture('coach_record');
  falseFlag.coach.records.new_damage_record = false;
  assert.throws(() => parseSnapshot(falseFlag));
  const incompleteWindow = fixture('coach_incomplete');
  incompleteWindow.coach.records.current_window_avg = 900;
  assert.throws(() => parseSnapshot(incompleteWindow));
  const mismatchedPeriod = fixture('coach_record');
  mismatchedPeriod.coach.comparison.current_avg = 1249;
  assert.throws(() => parseSnapshot(mismatchedPeriod));
});

test('an exact rolling record may legitimately tie the displayed rounded average', () => {
  const value = fixture('coach_record');
  value.coach.records.current_window_avg = 1000;
  value.coach.records.best_window_avg = 1000;
  value.coach.records.previous_best_window_avg = 1000;
  value.coach.comparison.current_avg = 1000;
  assert.equal(parseSnapshot(value).coach?.records.new_window_record, true);
  value.coach.records.new_window_record = false;
  assert.doesNotThrow(() => parseSnapshot(value));
});
