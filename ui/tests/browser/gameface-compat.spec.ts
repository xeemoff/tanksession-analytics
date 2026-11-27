import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

// Exercise the game's transport/layout path with synthetic preview data.
// Chromium is not the embedded renderer; the release still needs a client smoke.
async function nativeHost(page: Page) {
  await page.addInitScript(() => {
    const listeners = new Map<string, (...args: unknown[]) => void>();
    window.isDomBuilt = true;
    window.engine = {
      whenReady: Promise.resolve(),
      on: (name, callback) => { listeners.set(name, callback); },
      off: name => { listeners.delete(name); }
    };
    window.viewEnv = { addDataChangedCallback: () => 0, removeDataChangedCallback: () => {}, resizeViewPx: () => {} };
    window.model = {
      payload: '', onClose: () => {},
      onRequest: async ({ payload }: { payload: string }) => {
        const values = JSON.parse(payload);
        const query = new URLSearchParams();
        for (const key of ['request_id', 'window', 'vehicle', 'page', 'history_query', 'history_sort']) {
          if (values[key] !== undefined) query.set(key, String(values[key]));
        }
        const response = await fetch('/api/snapshot?' + query);
        const snapshot = await response.json();
        window.model!.payload = JSON.stringify({ ...snapshot, source: 'game' });
        listeners.get('viewEnv.onDataChanged')?.();
      }
    };
  });
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.goto('/');
  await expect(page.getByTestId('battle-count')).toBeVisible();
}

test('native transport keeps the history pager below all rows and card counters on one line', async ({ page }) => {
  await nativeHost(page);
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  const row = page.getByRole('table', { name: 'Последние бои' }).getByRole('row').last();
  const pager = page.locator('.history-pages');
  const rowBox = await row.boundingBox();
  const pagerBox = await pager.boundingBox();
  expect(rowBox).not.toBeNull();
  expect(pagerBox).not.toBeNull();
  expect(pagerBox!.y).toBeGreaterThanOrEqual(rowBox!.y + rowBox!.height + 8);
  await expect(page.getByRole('button', { name: 'Первая страница боёв' })).toHaveClass(/is-disabled/);
  await expect(page.getByRole('button', { name: 'Следующая страница боёв' })).toHaveClass(/is-enabled/);
  const open = page.getByRole('button', { name: 'Подробности боя 1', exact: true });
  expect(await open.evaluate(button => getComputedStyle(button).color)).not.toBe('rgb(0, 0, 0)');
  expect(await open.evaluate(button => parseFloat(getComputedStyle(button).fontSize))).toBeGreaterThanOrEqual(14);
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/hangar-native-compat-history.png', animations: 'disabled' });

  await page.getByRole('button', { name: 'Аналитика', exact: true }).click();
  await page.getByRole('button', { name: 'Техника', exact: true }).click();
  const counter = page.locator('.vehicle-collection .page-controls > span');
  expect(await counter.evaluate(element => element.childNodes.length)).toBe(1);
  await expect(counter).toHaveText(/^1 \/ \d+$/);
  expect(await counter.evaluate(element => getComputedStyle(element).whiteSpace)).toBe('nowrap');
  await page.screenshot({ path: 'test-results/hangar-native-compat-vehicles.png', animations: 'disabled' });
});

test('native wheel is canceled once, scrolls in the corrected direction and has reachable button and keyboard alternatives', async ({ page }) => {
  await nativeHost(page);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const area = page.locator('#panel-content');
  expect(await area.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(192);
  const box = (await area.boundingBox())!;
  await page.mouse.move(box.x + box.width - 16, box.y + box.height / 2);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(96);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
  const down = page.getByRole('button', { name: 'Прокрутить вниз', exact: true });
  await expect(down).toBeInViewport();
  await down.click();
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(192);
  await page.getByRole('button', { name: 'Прокрутить вверх', exact: true }).click();
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
  await area.focus();
  await page.keyboard.press('End');
  await expect.poll(() => area.evaluate(element => element.scrollTop >= element.scrollHeight - element.clientHeight - 1)).toBe(true);
  await expect(down).toBeInViewport();
  await page.screenshot({ path: 'test-results/hangar-native-compat-report-bottom.png', animations: 'disabled' });
  await page.keyboard.press('Home');
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
});

test('browser demo keeps ordinary positive-down wheel scrolling without native controls', async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 650 });
  await page.goto('/?demo=1');
  await expect(page.getByTestId('battle-count')).toBeVisible();
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const area = page.locator('#panel-content');
  await expect(page.getByRole('group', { name: 'Прокрутка панели' })).toHaveCount(0);
  const box = (await area.boundingBox())!;
  await page.mouse.move(box.x + box.width - 16, box.y + box.height / 2);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
});
