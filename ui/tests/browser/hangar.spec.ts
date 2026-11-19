import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

test('demo displays the Python snapshot and produces a review screenshot', async ({ page, request }) => {
  const response = await request.get('/api/snapshot?window=10&vehicle=&request_id=expected');
  const snapshot = await response.json();
  await page.goto('/?demo=1');
  await expect(page.getByRole('heading', { name: 'TankSession' })).toBeVisible();
  await expect(page.getByText('DEMO · вымышленные данные', { exact: true })).toBeVisible();
  await expect(page.getByTestId('battle-count')).toHaveText(String(snapshot.summary.battles));
  await expect(page.getByRole('table', { name: 'Последние бои' })).toBeVisible();
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/hangar-demo.png', fullPage: true });
});

test('window and tank filters request fresh data and keep the selected scope', async ({ page, request }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: '100 боёв', exact: true }).click();
  await expect(page.getByRole('button', { name: '100 боёв', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText(/Для сравнения двух периодов нужно ещё/)).toBeVisible();
  await page.getByRole('button', { name: 'Выбрать танк' }).click();
  await page.getByRole('option', { name: /IS-7/ }).click();
  const response = await request.get('/api/snapshot?window=100&vehicle=IS-7&request_id=expected');
  const snapshot = await response.json();
  await expect(page.getByTestId('battle-count')).toHaveText(String(snapshot.summary.battles));
  await expect(page.getByRole('button', { name: 'Выбрать танк' })).toContainText('IS-7');
  await expect(page.getByRole('button', { name: '100 боёв', exact: true })).toHaveAttribute('aria-pressed', 'true');
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
