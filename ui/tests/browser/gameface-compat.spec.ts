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

for (const legacyGeometry of [false, true]) test('native wheel, text buttons and keys work ' + (legacyGeometry ? 'without clientHeight (pre-1.54)' : 'with modern geometry'), async ({ page }) => {
  await nativeHost(page);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const area = page.locator('#panel-content');
  if (legacyGeometry) {
    await area.evaluate(element => Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => undefined }));
    expect(await area.evaluate(element => element.clientHeight)).toBeUndefined();
  }
  const end = await area.evaluate(element => element.scrollHeight - (element as HTMLElement).offsetHeight);
  expect(end).toBeGreaterThan(96);
  const box = (await area.boundingBox())!;
  await page.mouse.move(box.x + box.width - 16, box.y + box.height / 2);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(96);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
  const down = page.getByRole('button', { name: 'Прокрутить вниз', exact: true });
  await expect(down).toHaveText('Вниз');
  await expect(page.getByRole('button', { name: 'Прокрутить вверх', exact: true })).toHaveText('Вверх');
  await expect(down).toBeInViewport();
  await down.click();
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(Math.min(192, end));
  await page.getByRole('button', { name: 'Прокрутить вверх', exact: true }).click();
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
  await area.focus();
  await page.keyboard.press('End');
  await expect.poll(() => area.evaluate(element => element.scrollTop >= element.scrollHeight - (element as HTMLElement).offsetHeight - 1)).toBe(true);
  const bottom = await area.evaluate(element => element.scrollTop);
  await page.mouse.move(box.x + box.width - 16, box.y + box.height / 2);
  await page.mouse.wheel(0, -120);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(bottom);
  await expect(down).toBeInViewport();
  await expect(page.locator('.report-economy')).toBeInViewport({ ratio: 1 });
  if (legacyGeometry) await page.screenshot({ path: 'test-results/hangar-native-compat-report-bottom.png', animations: 'disabled' });
  await page.keyboard.press('Home');
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
  await page.mouse.wheel(0, 120);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => area.evaluate(element => element.scrollTop)).toBe(0);
});

test('native report period controls stay in a horizontal row and inside the panel', async ({ page }) => {
  await nativeHost(page);
  await page.getByRole('button', { name: 'Отчёты', exact: true }).click();
  const periods = page.getByRole('group', { name: 'Период отчёта' });
  for (const width of [1120, 900]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(periods).toHaveCSS('flex-direction', 'row');
    const buttons = await periods.getByRole('button').all();
    const boxes = await Promise.all(buttons.map(button => button.boundingBox()));
    expect(boxes).toHaveLength(3);
    for (const box of boxes) {
      expect(box).not.toBeNull();
      expect(Math.abs(box!.y - boxes[0]!.y)).toBeLessThan(1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }
    if (width === 1120) await page.screenshot({ path: 'test-results/hangar-native-compat-report-periods.png', animations: 'disabled' });
    await buttons[1].click();
    await expect(buttons[1]).toHaveAttribute('aria-pressed', 'true');
  }
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
