import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { Preferences, Snapshot, SnapshotRequest } from '../../src/contracts';
import { parseSnapshot } from '../../src/contracts';
import { formatNumber } from '../../src/format';

async function serveFixture(page: Page, name = 'analytics_v2') {
  const original = parseSnapshot(readFileSync(resolve('../sample_data/ui/' + name + '.json'), 'utf8'));
  let preferences: Preferences = original.workspace!.preferences;
  const requests: SnapshotRequest[] = [];
  await page.route('**/api/**', async route => {
    const incoming = route.request().method() === 'POST' ? route.request().postDataJSON() as SnapshotRequest
      : Object.fromEntries(new URL(route.request().url()).searchParams.entries()) as unknown as SnapshotRequest;
    requests.push(incoming);
    const value = JSON.parse(JSON.stringify(original)) as Snapshot;
    value.request_id = incoming.request_id;
    if (incoming.action === 'save_preferences' && incoming.preferences) {
      preferences = incoming.preferences;
      value.workspace!.operation = { status: 'saved', code: 'preferences_saved' };
    }
    value.workspace!.preferences = preferences;
    if (incoming.action === 'save_goal' && incoming.goal) {
      value.workspace!.goals = [incoming.goal];
      value.workspace!.operation = { status: 'saved', code: 'goal_saved' };
    }
    parseSnapshot(value);
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
  });
  return { original, requests };
}

async function capture(page: Page, name: string) {
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/hangar-v2-' + name + '.png', fullPage: true });
}

test('2.0 analytics explores metadata, ordered observations, UTC activity and honest vehicle cards', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await serveFixture(page);
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Аналитика', exact: true }).click();
  const dimensions = page.getByRole('group', { name: 'Срез результатов' });
  for (const label of ['Уровни', 'Классы', 'Нации', 'Карты']) {
    await dimensions.getByRole('button', { name: label, exact: true }).click();
    await expect(dimensions.getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true');
  }
  await page.getByRole('group', { name: 'Показатель графика' }).getByRole('button', { name: 'Средний урон', exact: true }).click();
  await page.getByRole('button', { name: 'По показателю', exact: true }).click();
  const bars = page.getByRole('group', { name: 'Группы на графике' }).getByRole('button');
  await bars.first().focus(); await bars.first().press('ArrowDown');
  await expect(bars.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('complementary', { name: 'Выбранная группа' })).toContainText('Итог кредитов известен');
  await capture(page, 'analytics');
  await page.getByRole('group', { name: 'Разделы аналитики' }).getByRole('button', { name: 'Активность', exact: true }).click();
  await expect(page.getByRole('group', { name: 'Календарь активности' }).getByRole('button')).toHaveCount(90);
  await page.getByRole('button', { name: 'Часы', exact: true }).click();
  const hours = page.getByRole('group', { name: 'Часы активности' });
  await expect(hours.getByRole('button')).toHaveCount(24);
  await hours.getByRole('button', { name: /^18:00/ }).click();
  await expect(page.getByTestId('activity-selection')).toContainText('18:00');
  await expect(page.getByText('Получение результата · UTC, не местное время')).toBeVisible();
  await capture(page, 'activity');
  await page.getByRole('group', { name: 'Разделы аналитики' }).getByRole('button', { name: 'Техника', exact: true }).click();
  await expect(page.locator('.vehicle-card').first()).toContainText('Схема класса, не модель машины');
  await expect(page.locator('.vehicle-art').first()).toHaveAttribute('role', 'img');
  await capture(page, 'vehicles');
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 1120);
});

test('period reports expose each interval and keep all-time totals free of invented comparisons', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  const { original } = await serveFixture(page);
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  for (const [key, label] of [['week', '7 дней'], ['month', '30 дней'], ['all_time', 'Вся история']] as const) {
    await page.getByRole('group', { name: 'Период отчёта' }).getByRole('button', { name: label, exact: true }).click();
    await expect(page.getByTestId('report-battles')).toHaveText(formatNumber(original.reports!.periods.find(item => item.key === key)!.summary.battles));
    await expect(page.getByTestId('report-range')).toContainText('UTC');
  }
  await expect(page.getByRole('table', { name: 'Сравнение периодов отчёта' })).toHaveCount(0);
  await page.getByRole('button', { name: '30 дней', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Сравнение периодов отчёта' })).toBeVisible();
  await capture(page, 'report');
  await page.getByRole('group', { name: 'Содержание отчёта' }).getByRole('button', { name: 'По технике', exact: true }).click();
  await expect(page.getByRole('group', { name: 'Группы на графике' })).toBeVisible();
});

test('expanded Coach uses explicit evidence and saves a proposed goal only after confirmation', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  const { original, requests } = await serveFixture(page, 'coach_v2');
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Наблюдения и цель', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Разброс урона' })).toContainText('MAD');
  await expect(page.getByRole('region', { name: 'Ориентир личной цели' })).toContainText('эвристика, не прогноз успеха');
  expect(requests.filter(item => item.action === 'save_goal')).toHaveLength(0);
  await capture(page, 'coach-evidence');
  await page.getByRole('button', { name: 'Рассмотреть цель', exact: true }).click();
  await expect(page.getByRole('group', { name: 'Подтверждение предлагаемой цели' })).toBeVisible();
  expect(requests.filter(item => item.action === 'save_goal')).toHaveLength(0);
  await page.getByRole('button', { name: 'Сохранить эту цель', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('Цель сохранена');
  const sent = requests.find(item => item.action === 'save_goal');
  expect(sent?.action).toBe('save_goal');
  if (!sent || sent.action !== 'save_goal') throw new Error('No confirmed goal command');
  const suggestion = original.coach!.goal_suggestions![0];
  expect(sent.goal).toEqual({ vehicle: suggestion.vehicle, window: suggestion.window, target_avg_damage: suggestion.target_avg_damage });
});

test('themes, reduced motion and dashboard modules are saved account preferences', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const { requests } = await serveFixture(page);
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('button', { name: 'Темы и движение', exact: true }).click();
  await page.getByRole('group', { name: 'Цветовая тема' }).getByRole('button', { name: /^Светлая/ }).click();
  await page.getByRole('button', { name: 'Уменьшить движение', exact: true }).click();
  await page.getByRole('button', { name: 'Сохранить вид и фильтры', exact: true }).click();
  await expect(page.locator('.panel')).toHaveClass(/theme-light.*motion-reduced/);
  await expect(page.locator('.screen-content')).toHaveCSS('animation-name', 'none');
  await page.getByRole('button', { name: 'Модули панели', exact: true }).click();
  await page.getByRole('button', { name: 'Модуль Разбор прогресса', exact: true }).click();
  await page.getByRole('button', { name: 'Модуль Карточка техники', exact: true }).click();
  await page.getByRole('button', { name: 'Модуль Экономика', exact: true }).click();
  await page.getByRole('button', { name: 'Сохранить вид и фильтры', exact: true }).click();
  const saved = requests.filter(item => item.action === 'save_preferences').pop();
  if (!saved || saved.action !== 'save_preferences') throw new Error('No preferences command');
  expect(saved.preferences?.modules).toEqual(['metrics', 'vehicle', 'economy']);
  await page.getByRole('group', { name: 'Разделы статистики' }).getByRole('button', { name: 'Прогресс', exact: true }).click();
  await expect(page.getByTestId('coach-card')).toHaveCount(0);
  await page.getByRole('group', { name: 'Модули личной панели' }).getByRole('button', { name: 'Экономика', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Экономика сохранённых боёв' })).toBeVisible();
  await capture(page, 'light-dashboard');
});

test('history searches and sorts the complete Python journal before pagination', async ({ page, request }) => {
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  const initial = await (await request.get('/api/snapshot?window=10&vehicle=&request_id=v2-initial')).json() as Snapshot;
  const query = initial.history[0].map_label || initial.history[0].vehicle_label || initial.history[0].vehicle;
  const expected = await (await request.get('/api/snapshot?window=10&vehicle=&request_id=v2-search&history_query=' + encodeURIComponent(query) + '&history_sort=damage_desc')).json() as Snapshot;
  await page.getByRole('searchbox', { name: 'Поиск по всей истории' }).fill(query);
  await page.getByRole('group', { name: 'Сортировка всей истории' }).getByRole('button', { name: 'Урон', exact: true }).click();
  await expect(page.getByRole('searchbox', { name: 'Поиск по всей истории' })).toHaveValue(query);
  await expect(page.locator('.history-section .section-heading')).toContainText(expected.pagination!.total + ' найдено из ' + initial.summary.battles);
  await expect(page.locator('.history-scroll .col-damage').first()).toHaveText(formatNumber(expected.history[0].damage));
  if (expected.pagination!.pages > 1) {
    await page.getByRole('button', { name: 'Следующая страница боёв', exact: true }).click();
    await expect(page.getByTestId('history-page')).toHaveText('2 / ' + expected.pagination!.pages);
  }
  await page.getByRole('button', { name: 'Сбросить поиск', exact: true }).click();
  await expect(page.getByRole('searchbox', { name: 'Поиск по всей истории' })).toHaveValue('');
  await expect(page.getByTestId('history-page')).toHaveText('1 / ' + initial.pagination!.pages);
});
