import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';

// Capture the actual browser render using only synthetic preview data.
async function captureDocumentation(page: Page, name: string) {
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/hangar-' + name + '.png', fullPage: true });
}

async function serveCoachFixture(page: Page, name: string) {
  const fixture = JSON.parse(readFileSync(resolve('../sample_data/ui/' + name + '.json'), 'utf8'));
  await page.route('**/api/snapshot?**', route => {
    const url = new URL(route.request().url());
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...fixture, request_id: url.searchParams.get('request_id') }) });
  });
  await page.route('**/api/command', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ ...fixture, request_id: route.request().postDataJSON().request_id }) }));
}

test('demo displays the Python snapshot and produces a review screenshot', async ({ page, request }) => {
  const response = await request.get('/api/snapshot?window=10&vehicle=&request_id=expected');
  const snapshot = await response.json();
  await page.goto('/?demo=1');
  await expect(page.getByRole('heading', { name: 'TankSession' })).toBeVisible();
  await expect(page.getByText('DEMO · вымышленные данные', { exact: true })).toBeVisible();
  await expect(page.getByTestId('battle-count')).toHaveText(String(snapshot.summary.battles));
  await expect(page.getByRole('heading', { name: 'Разбор прогресса' })).toBeVisible();
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Последние бои' })).toBeVisible();
  await page.getByRole('button', { name: 'Прогресс', exact: true }).click();
  await expect(page.getByText('Выберите машину для личного сравнения')).toBeVisible();
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/hangar-demo.png', fullPage: true });
});

test('window and tank filters request fresh data and keep the selected scope', async ({ page, request }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: '100 боёв', exact: true }).click();
  await expect(page.getByRole('button', { name: '100 боёв', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('Выберите машину для личного сравнения')).toBeVisible();
  await page.getByRole('button', { name: 'Выбрать танк' }).click();
  await page.getByRole('option', { name: /IS-7/ }).click();
  const response = await request.get('/api/snapshot?window=100&vehicle=IS-7&request_id=expected');
  const snapshot = await response.json();
  await expect(page.getByTestId('battle-count')).toHaveText(String(snapshot.summary.battles));
  await expect(page.getByRole('button', { name: 'Выбрать танк' })).toContainText('IS-7');
  await expect(page.getByRole('button', { name: '100 боёв', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('coach-remaining')).toHaveText(String(snapshot.coach.remaining_battles));
});

test('last-machine shortcut scopes progress without mixing vehicles', async ({ page, request }) => {
  const response = await request.get('/api/snapshot?window=10&vehicle=&request_id=expected');
  const initial = await response.json();
  const latest = initial.history[0].vehicle;
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Разобрать последнюю машину' }).click();
  await expect(page.getByRole('button', { name: 'Выбрать танк' })).toContainText(latest);
  await expect(page.getByTestId('coach-card')).toContainText(latest);
  await expect(page.getByText('Выберите машину для личного сравнения')).toHaveCount(0);
});

test('coach shows evidence and method in the native-sized viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await serveCoachFixture(page, 'coach_ready');
  await page.goto('/?demo=1');
  await expect(page.getByTestId('coach-delta')).toHaveText('+810,0 урона (+81,0%)');
  await expect(page.getByRole('table', { name: 'Сравнение урона двух периодов' })).toContainText('Медиана урона');
  await expect(page.getByText(/Среднее и медиана изменились в разные стороны/)).toBeVisible();
  await mkdir('test-results', { recursive: true });
  await captureDocumentation(page, 'coach');
  const explain = page.getByRole('button', { name: 'Как рассчитано' });
  await explain.click();
  await expect(page.getByRole('button', { name: 'Скрыть пояснение' })).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#coach-explanation')).toContainText('не доказывает изменение навыка');
  await expect(page.locator('#coach-explanation')).toContainText('временем получения результата');
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 1120);
});

test('one battle, missing damage and mixed modes show actionable states without invented progress', async ({ page }) => {
  await serveCoachFixture(page, 'coach_collecting');
  await page.goto('/?demo=1');
  await expect(page.getByTestId('coach-remaining')).toHaveText('19');
  await expect(page.getByTestId('coach-best-window')).toHaveText('—');
  await expect(page.getByText('Новый рекорд', { exact: true })).toHaveCount(0);
  await page.unroute('**/api/snapshot?**');
  await serveCoachFixture(page, 'coach_incomplete');
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await expect(page.getByText('Для вывода не хватает значений урона')).toBeVisible();
  await expect(page.getByTestId('coach-delta')).toHaveCount(0);
  await page.unroute('**/api/snapshot?**');
  await serveCoachFixture(page, 'coach_mixed_modes');
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await expect(page.getByText('В этих периодах разные типы боёв')).toBeVisible();
  await expect(page.getByTestId('coach-delta')).toHaveCount(0);
});

test('unavailable account and malformed coach clear displayed progress', async ({ page }) => {
  await serveCoachFixture(page, 'coach_ready');
  await page.goto('/?demo=1');
  await expect(page.getByTestId('coach-delta')).toBeVisible();
  await page.unroute('**/api/snapshot?**');
  await serveCoachFixture(page, 'account_unavailable');
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await expect(page.getByText('Аккаунт ещё не определён')).toBeVisible();
  await expect(page.getByTestId('coach-card')).toHaveCount(0);
  await page.unroute('**/api/snapshot?**');
  const fixture = JSON.parse(readFileSync(resolve('../sample_data/ui/coach_ready.json'), 'utf8'));
  fixture.coach.comparison.current_avg = 'bad';
  await page.route('**/api/snapshot?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...fixture, request_id: new URL(route.request().url()).searchParams.get('request_id') }) }));
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('coach-card')).toHaveCount(0);
});

test('missing game bridge shows an error without fabricated statistics', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Подключение к игре недоступно');
  await expect(page.getByTestId('battle-count')).toHaveCount(0);
  await expect(page.getByText('DEMO · вымышленные данные', { exact: true })).toHaveCount(0);
});

test('server failure clears the previous metrics and can recover', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.route('**/api/snapshot?**', route => route.fulfill({ status: 503, body: '{}' }));
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('battle-count')).toHaveCount(0);
  await page.unroute('**/api/snapshot?**');
  await page.getByRole('button', { name: 'Повторить подключение' }).click();
  await expect(page.getByTestId('battle-count')).toBeVisible();
});

test('Escape closes the preview and reopening reconnects', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Панель закрыта' })).toBeVisible();
  await page.getByRole('button', { name: 'Открыть снова' }).click();
  await expect(page.getByTestId('battle-count')).toBeVisible();
});


test('native-sized panel exposes the entire paged history without wheel input', async ({ page, request }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: 'Динамика и цели', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Динамика урона' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Личная цель' })).toBeVisible();
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  const expected = await (await request.get('/api/snapshot?window=10&vehicle=&request_id=expected&page=0')).json();
  const pages = expected.pagination.pages;
  await expect(page.getByTestId('history-page')).toHaveText('1 / ' + pages);
  await expect(page.getByRole('row')).toHaveCount(6);
  await captureDocumentation(page, 'history');
  await page.getByRole('button', { name: 'Следующая страница боёв' }).click();
  await expect(page.getByTestId('history-page')).toHaveText('2 / ' + pages);
  await page.getByRole('button', { name: 'Последняя страница боёв' }).click();
  await expect(page.getByTestId('history-page')).toHaveText(pages + ' / ' + pages);
  await expect(page.getByRole('row')).toHaveCount(1 + expected.pagination.total - (pages - 1) * 5);
  await expect(page.getByRole('button', { name: 'Следующая страница боёв' })).toBeDisabled();
  await page.getByRole('button', { name: 'Прогресс', exact: true }).click();
  await expect(page.getByTestId('coach-card')).toBeVisible();
});

test('live Python preview exposes raw damage chart and grouped summaries without scrolling', async ({ page, request }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  const response = await request.get('/api/snapshot?window=10&vehicle=&request_id=expected');
  const data = await response.json();
  expect(data.insights.recent_damage.length).toBe(24);
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: 'Динамика и цели', exact: true }).click();
  const bars = page.getByRole('group', { name: 'Урон отдельных боёв' }).getByRole('button');
  await expect(bars).toHaveCount(24);
  await captureDocumentation(page, 'damage');
  await bars.first().click();
  await expect(page.getByTestId('damage-detail')).toContainText('Бой ' + data.insights.recent_damage[0].battle + ' ·');
  await page.getByRole('button', { name: 'Скользящее среднее', exact: true }).click();
  await expect(page.getByRole('group', { name: 'Урон отдельных боёв' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Сводка', exact: true }).click();
  await expect(page.getByTestId('outcome-tally')).toContainText(data.summary.losses + ' Пор');
  await page.getByRole('button', { name: 'По дням', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Сводка результатов' })).toBeVisible();
  await page.getByRole('button', { name: 'По технике', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Сводка результатов' })).toContainText('IS-7');
  await captureDocumentation(page, 'summary');
  await page.getByRole('button', { name: 'По дням', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: 'Дата получения' })).toBeVisible();
});


test('new battle details and optional metrics preserve missing values without hiding older pages', async ({ page, request }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  const response = await request.get('/api/snapshot?window=10&vehicle=&request_id=expected&page=0');
  const data = await response.json();
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await page.getByRole('button', { name: 'Подробности боя 1', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Подробности боя' });
  await expect(detail).toContainText('Тире означает');
  await expect(detail).toContainText('Выстрелы / попадания / пробития');
  await page.getByRole('button', { name: 'Опыт и экономика', exact: true }).click();
  await expect(detail).toContainText('Базовый опыт');
  await expect(detail).toContainText('Может включать бонусы');
  await page.getByRole('button', { name: 'К списку боёв' }).click();
  await expect(page.getByTestId('history-page')).toHaveText('1 / ' + data.pagination.pages);
  await page.getByRole('button', { name: 'Сводка', exact: true }).click();
  await page.getByRole('button', { name: 'Показатели', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Дополнительные показатели' })).toContainText('У каждой метрики своя полнота данных');
  await captureDocumentation(page, 'metrics');
  await page.getByRole('button', { name: 'Сессии', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Сессии', exact: true })).toContainText('по времени получения результатов');
  await page.getByRole('button', { name: 'Последние сессии', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Последние сессии' })).toBeVisible();
  await captureDocumentation(page, 'sessions');
});

test('goals can be created and removed from the panel and CSV uses the selected history', async ({ page, request }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'Выбрать танк', exact: true }).click();
  await page.getByRole('option', { name: /IS-7/ }).click();
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await page.getByRole('group', { name: 'Раздел настроек' }).getByRole('button', { name: 'Цели', exact: true }).click();
  await page.getByRole('button', { name: 'Добавить цель', exact: true }).click();
  await page.getByRole('textbox', { name: 'Целевой средний урон' }).fill('2300');
  await page.getByRole('textbox', { name: 'Боёв для цели' }).fill('20');
  await page.getByRole('button', { name: 'Сохранить цель', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('Цель сохранена');
  await page.getByRole('button', { name: 'К списку целей', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Настройка целей' })).toContainText('2 300 урона · 20 боёв');
  await captureDocumentation(page, 'goals');
  await page.getByRole('button', { name: 'Удалить цель IS-7 20', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('Цель удалена');
  await expect(page.getByRole('button', { name: 'Удалить цель IS-7 20', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Экспорт CSV', exact: true }).click();
  const expected = await (await request.get('/api/snapshot?window=10&vehicle=IS-7&request_id=expected')).json();
  await page.getByRole('button', { name: 'Сохранить CSV', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('CSV сохранён');
  await expect(page.getByTestId('operation-result')).toContainText('Строк: ' + expected.summary.battles);
  await expect(page.getByTestId('operation-result')).toContainText('Демонстрационный CSV во временной папке локального сервера');
});

test('saved appearance, vehicle and starting section survive reopening with all controls in view', async ({ page, request }) => {
  const reset = { protocol: 1, request_id: 'test-reset', vehicle: '', window: 10, action: 'save_preferences', preferences: {
    vehicle: '', window: 10, tab: 'progress', density: 'normal', contrast: 'standard'
  } };
  try {
    await page.setViewportSize({ width: 1120, height: 800 });
    await page.goto('/?demo=1');
    await page.getByRole('button', { name: 'Выбрать танк', exact: true }).click();
    await page.getByRole('option', { name: /IS-7/ }).click();
    await page.getByRole('button', { name: '30 боёв', exact: true }).click();
    await page.getByRole('button', { name: 'Настройки', exact: true }).click();
    await page.getByRole('button', { name: 'Компактная', exact: true }).click();
    await page.getByRole('button', { name: 'Повышенный', exact: true }).click();
    await page.getByRole('group', { name: 'Стартовый раздел' }).getByRole('button', { name: 'История боёв', exact: true }).click();
    const save = page.getByRole('button', { name: 'Сохранить вид и фильтры', exact: true });
    await expect(save).toBeInViewport();
    await save.click();
    await expect(page.getByTestId('operation-result')).toContainText('Вид и фильтры сохранены');
    await expect(page.locator('.panel')).toHaveClass(/density-compact/);
    await expect(page.locator('.panel')).toHaveClass(/contrast-high/);
    await captureDocumentation(page, 'settings');
    await page.reload();
    await expect(page.getByRole('table', { name: 'Последние бои' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Выбрать танк', exact: true })).toContainText('IS-7');
    await expect(page.getByRole('button', { name: '30 боёв', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.panel')).toHaveClass(/contrast-high/);
  } finally {
    await request.post('/api/command', { headers: { 'X-TankSession-Request': '1' }, data: reset });
  }
});
