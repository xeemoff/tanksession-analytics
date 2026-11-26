import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';

async function serveCoachFixture(page: Page, name: string) {
  const fixture = JSON.parse(readFileSync(resolve('../sample_data/ui/' + name + '.json'), 'utf8'));
  await page.route('**/api/snapshot?**', route => {
    const url = new URL(route.request().url());
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...fixture, request_id: url.searchParams.get('request_id') }) });
  });
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
  await page.screenshot({ path: 'test-results/hangar-coach.png', fullPage: true });
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


test('native-sized panel exposes sections and twelve history rows without wheel input', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: 'Динамика и цели', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Динамика урона' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Личная цель' })).toBeVisible();
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await expect(page.getByTestId('history-page')).toHaveText('1 / 3');
  await expect(page.getByRole('row')).toHaveCount(6);
  await page.getByRole('button', { name: 'Следующая страница боёв' }).click();
  await expect(page.getByTestId('history-page')).toHaveText('2 / 3');
  await page.getByRole('button', { name: 'Следующая страница боёв' }).click();
  await expect(page.getByTestId('history-page')).toHaveText('3 / 3');
  await expect(page.getByRole('row')).toHaveCount(3);
  await expect(page.getByRole('button', { name: 'Следующая страница боёв' })).toBeDisabled();
  await page.getByRole('button', { name: 'Прогресс', exact: true }).click();
  await expect(page.getByTestId('coach-card')).toBeVisible();
});
