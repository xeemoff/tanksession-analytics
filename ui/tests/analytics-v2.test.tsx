import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { ActivityGrid, AnalyticsView, EconomyView, GroupChart, sortGroups } from '../src/Analytics';
import { CoachEvidence } from '../src/CoachEvidence';
import { SnapshotView } from '../src/App';
import { AnalysisGroup, parseSnapshot, Snapshot } from '../src/contracts';
import { ReportsView, reportRange } from '../src/Reports';
import { VehicleCard } from '../src/VehicleCards';

function fixture(name = 'analytics_v2'): Snapshot {
  return JSON.parse(readFileSync('../sample_data/ui/' + name + '.json', 'utf8')) as Snapshot;
}

test('real 2.0 snapshots preserve metadata, complete UTC calendars, signed totals and reports', () => {
  const value = parseSnapshot(fixture());
  assert.equal(value.analytics!.activity.days.length, 90);
  assert.equal(value.analytics!.activity.hours.length, 24);
  assert.equal(value.analytics!.activity.weekdays.length, 7);
  assert.equal(value.analytics!.timezone, 'UTC');
  assert.deepEqual(value.reports!.periods.map(item => item.key), ['week', 'month', 'all_time']);
  assert(value.vehicles.some(item => item.vehicle_tier !== null));
  const legacy = fixture(); delete legacy.analytics; delete legacy.reports;
  legacy.vehicles.forEach(item => { delete item.vehicle_tier; delete item.vehicle_class; delete item.vehicle_nation; });
  delete legacy.selection.history_query; delete legacy.selection.history_sort;
  assert.doesNotThrow(() => parseSnapshot(legacy));
});

test('metadata and analytics reject invalid enums, duplicate groups and invented coverage', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.vehicles[0].vehicle_tier = 0; },
    value => { value.vehicles[0].vehicle_tier = 12; },
    value => { value.vehicles[0].vehicle_class = 'fast' as never; },
    value => { value.history[0].vehicle_nation = 'invented'; },
    value => { value.history[0].map_label = 17 as never; },
    value => { value.analytics!.coverage.vehicle_tier = value.summary.battles + 1; },
    value => { value.analytics!.dimensions.maps.push(value.analytics!.dimensions.maps[0]); },
    value => { value.analytics!.economy.xp_bonus.total = -1; },
    value => { value.analytics!.economy.credits_net.samples = 0; },
    value => { value.analytics!.economy.credits_net.average = 999999; },
    value => { value.analytics!.timezone = 'local' as never; }
  ];
  for (const corrupt of corruptions) { const value = fixture(); corrupt(value); assert.throws(() => parseSnapshot(value)); }
});

test('group ordering is observed, stable, immutable and keeps zero and negatives before unknown values', () => {
  const base = fixture().analytics!.economy.vehicles[0];
  const group = (key: string, average: number | null, battles = 10): AnalysisGroup => ({ ...base, key, label: key,
    summary: { ...base.summary, battles }, credits_net: { samples: average === null ? 0 : 1, total: average, average } });
  const groups = [group('missing', null, 20), group('negative', -120), group('zero', 0), group('b', 50), group('a', 50)];
  const original = groups.map(item => item.key);
  assert.deepEqual(sortGroups(groups, 'credits', 'metric').map(item => item.key), ['a', 'b', 'zero', 'negative', 'missing']);
  assert.deepEqual(sortGroups(groups, 'credits', 'battles').map(item => item.key), ['missing', 'a', 'b', 'negative', 'zero']);
  assert.deepEqual(groups.map(item => item.key), original);
  const html = renderToStaticMarkup(<GroupChart groups={groups} title="Итог кредитов" initialMetric="credits" />);
  assert.match(html, /negative-bar/); assert.match(html, /-120,0/); assert.match(html, /0,0/); assert.match(html, /—/);
  assert.match(html, /По показателю/); assert.match(html, /Итог кредитов известен/);
});

test('calendar keeps known zero activity separate from missing damage and offers keyboard selection', () => {
  const value = parseSnapshot(fixture());
  const hours = value.analytics!.activity.hours;
  assert(hours.some(item => item.summary.battles === 0));
  const html = renderToStaticMarkup(<ActivityGrid groups={hours} unit="hours" />);
  assert.equal((html.match(/class="activity-cell/g) || []).length, 24);
  assert.match(html, /0 боёв/); assert.match(html, /aria-pressed="true"/);
  assert.match(html, /стрелки влево и вправо/);
});

test('reports show exact UTC intervals and cannot claim a delta with incomplete contributing data', () => {
  const value = fixture('coach_v2');
  const month = value.reports!.periods.find(item => item.key === 'month')!;
  assert.equal(month.comparison.status, 'ready');
  month.summary.damage_samples -= 1;
  month.comparison.avg_damage_delta = null;
  month.comparison.status = 'partial_data';
  assert.doesNotThrow(() => parseSnapshot(value));
  month.comparison.avg_damage_delta = 0;
  assert.throws(() => parseSnapshot(value));
  assert.equal(reportRange({ start_at: 0, end_at: 3601 }), '01.01.1970 00:00:00 — 01.01.1970 01:00:00 UTC');
  const html = renderToStaticMarkup(<ReportsView snapshot={parseSnapshot(fixture())} />);
  assert.match(html, /UTC/); assert.match(html, /Сравнение периодов отчёта/);
  assert.match(html, /полной известности соответствующего поля/);
  const invalid = fixture(); invalid.reports!.excluded_future += 1;
  assert.throws(() => parseSnapshot(invalid));
});

test('Coach evidence rejects impossible spread, unverifiable observations and automatic goal suggestions', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.coach!.consistency!.lower_quartile = 999999; },
    value => { value.coach!.consistency!.interquartile_range = 999999; },
    value => { value.coach!.observations![0].samples = 11; },
    value => { value.coach!.observations![0].delta = 999999; },
    value => { value.coach!.goal_suggestions![0].vehicle = 'other'; },
    value => { value.coach!.goal_suggestions![0].requires_confirmation = false as never; },
    value => { value.coach!.goal_suggestions![0].target_avg_damage = 0; }
  ];
  for (const corrupt of corruptions) { const value = fixture('coach_v2'); corrupt(value); assert.throws(() => parseSnapshot(value)); }
  const ambiguous = fixture('identity_ambiguous');
  ambiguous.coach!.observations = fixture('coach_v2').coach!.observations;
  assert.throws(() => parseSnapshot(ambiguous));
  const coach = parseSnapshot(fixture('coach_v2')).coach!;
  const html = renderToStaticMarkup(<CoachEvidence coach={coach} onSaveGoal={() => assert.fail('render must not save a goal')} />);
  assert.match(html, /MAD/); assert.match(html, /эвристика, не прогноз успеха/);
  assert.match(html, /Рассмотреть цель/); assert(!html.includes('Сохранить эту цель'));
});

test('dashboard modules and themes are bounded preferences, while default legacy layout remains available', () => {
  const value = fixture('coach_v2');
  value.workspace!.preferences.modules = ['metrics'];
  value.workspace!.preferences.theme = 'light';
  value.workspace!.preferences.motion = 'reduced';
  const html = renderToStaticMarkup(<SnapshotView snapshot={parseSnapshot(value)} section="progress" />);
  assert.match(html, /battle-count/); assert(!html.includes('coach-card'));
  for (const bad of [[], ['coach', 'coach'], ['untrusted']]) {
    const copy = fixture(); copy.workspace!.preferences.modules = bad as never; assert.throws(() => parseSnapshot(copy));
  }
  const invalid = fixture(); invalid.workspace!.preferences.theme = 'remote-css' as never;
  assert.throws(() => parseSnapshot(invalid));
});

test('whole-history search may have zero matches without emptying overall analytics', () => {
  const value = fixture(); const battles = value.summary.battles;
  value.selection.history_query = 'нет совпадений'; value.selection.history_sort = 'damage_desc';
  value.history = []; value.pagination = { page: 0, page_size: 5, pages: 1, total: 0 };
  assert.equal(parseSnapshot(value).summary.battles, battles);
  const html = renderToStaticMarkup(<SnapshotView snapshot={value} section="history" onHistoryFilter={() => {}} />);
  assert.match(html, /Совпадений не найдено/); assert.match(html, /всей выбранной истории/);
  value.selection.history_query = ''; assert.throws(() => parseSnapshot(value));
  value.selection.history_query = 'x'.repeat(65); assert.throws(() => parseSnapshot(value));
});

test('class illustrations do not invent metadata or masquerade as vehicle photographs', () => {
  const unknown = renderToStaticMarkup(<VehicleCard vehicle={{ name: 'type:257', label: 'Т-34', battles: 2 }} />);
  assert.match(unknown, /Класс неизвестен/); assert.match(unknown, /Нация неизвестна/);
  assert.match(unknown, /Схема класса, не модель машины/); assert(!unknown.includes('<img'));
  const known = renderToStaticMarkup(<VehicleCard vehicle={{ name: 'type:257', label: '<Т-34>', battles: 2, vehicle_class: 'mediumTank', vehicle_tier: 5, vehicle_nation: 'ussr' }} />);
  assert.match(known, /Средний танк/); assert.match(known, /СССР/); assert.match(known, /&lt;Т-34&gt;/);
});

test('new sections render only supplied data and retain economy scope qualifications', () => {
  const value = parseSnapshot(fixture());
  const analytics = renderToStaticMarkup(<AnalyticsView snapshot={value} />);
  assert.match(analytics, /Неизвестные характеристики сохранены отдельной группой/);
  const economy = renderToStaticMarkup(<EconomyView snapshot={value} compact />);
  assert.match(economy, /Запасы со склада не оцениваются/);
  assert.match(economy, /сумма части истории не является полным итогом/);
});
