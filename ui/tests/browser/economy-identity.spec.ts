import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';
import type { Snapshot, SnapshotRequest } from '../../src/contracts';

function fixture(selector = 'type:507'): Snapshot {
  const value = JSON.parse(readFileSync(resolve('../sample_data/ui/release.json'), 'utf8')) as Snapshot;
  const label = selector === 'type:507' ? 'Т-34' : 'ИС-7';
  value.selection.vehicle = selector;
  value.vehicles = [
    { name: 'type:507', label: 'Т-34', battles: value.summary.battles },
    { name: 'type:508', label: 'ИС-7', battles: value.summary.battles }
  ];
  value.history.forEach(row => { row.vehicle = selector; row.vehicle_label = label; });
  value.coach!.vehicle = selector;
  value.coach!.vehicle_label = label;
  value.goals.forEach(goal => { goal.vehicle = selector; goal.vehicle_label = label; });
  value.insights!.tanks.forEach(row => { row.label = selector; row.vehicle_label = label; });
  value.workspace!.preferences.vehicle = selector;
  value.workspace!.goals = [{ vehicle: selector, vehicle_label: label, window: 10, target_avg_damage: 1000 }];
  Object.assign(value.history[0], { xp: 500, xp_base: 500, xp_bonus: 0, credits_gross: 1000, credits_net: -120 });
  value.metrics!.fields.xp_bonus = { samples: 1, average: 0 };
  value.metrics!.fields.credits_net = { samples: 1, average: -120 };
  return value;
}

async function serve(page: Page, transform?: (value: Snapshot) => void) {
  const requests: SnapshotRequest[] = [];
  await page.route('**/api/**', async route => {
    const incoming = route.request().method() === 'POST' ? route.request().postDataJSON()
      : Object.fromEntries(new URL(route.request().url()).searchParams.entries());
    requests.push(incoming);
    const value = fixture(incoming.vehicle || 'type:507');
    value.request_id = incoming.request_id;
    if (incoming.action === 'save_preferences') {
      value.workspace!.preferences = incoming.preferences;
      value.workspace!.operation = { status: 'saved', code: 'preferences_saved' };
    }
    if (incoming.action === 'save_goal') {
      value.workspace!.goals = [{ ...incoming.goal, vehicle_label: value.vehicles.find(v => v.name === incoming.goal.vehicle)?.label }];
      value.workspace!.operation = { status: 'saved', code: 'goal_saved' };
    }
    transform?.(value);
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
  });
  return requests;
}

test('bonus XP, net credits and missing values remain explicit in native-sized details and totals', async ({ page }) => {
  let missing = false;
  await serve(page, value => {
    if (missing) {
      value.history[0].xp = 2000;
      value.history[0].xp_bonus = null;
      value.history[0].credits_net = null;
      value.metrics!.fields.xp_bonus = { samples: 0, average: null };
      value.metrics!.fields.credits_net = { samples: 0, average: null };
    }
  });
  await page.setViewportSize({ width: 1120, height: 800 });
  await page.goto('/?demo=1');
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await page.getByRole('button', { name: 'Подробности боя 1', exact: true }).click();
  await page.getByRole('button', { name: 'Опыт и экономика', exact: true }).click();
  const details = page.getByRole('region', { name: 'Подробности боя' });
  const bonus = details.locator('.detail-metric').filter({ has: page.getByText('Бонусный опыт', { exact: true }) });
  const net = details.locator('.detail-metric').filter({ has: page.getByText('Итог кредитов', { exact: true }) });
  await expect(bonus.locator('strong')).toHaveText('0');
  await expect(net.locator('strong')).toHaveText('-120');
  await expect(net).toContainText('Запасы со склада не оцениваются');
  await expect(net).toBeInViewport({ ratio: 1 });
  await page.getByRole('button', { name: 'Сводка', exact: true }).click();
  await page.getByRole('button', { name: 'Показатели', exact: true }).click();
  await page.getByRole('button', { name: 'Опыт и кредиты', exact: true }).click();
  await expect(page.getByTestId('economy-xp_bonus')).toContainText('Известно в 1 из 20');
  await expect(page.getByTestId('economy-xp_bonus').locator('strong')).toHaveText('0');
  await expect(page.getByTestId('economy-credits_net').locator('strong')).toHaveText('-120');
  missing = true;
  await page.getByRole('button', { name: 'Обновить статистику' }).click();
  await page.getByRole('button', { name: 'Показатели', exact: true }).click();
  await page.getByRole('button', { name: 'Опыт и кредиты', exact: true }).click();
  await expect(page.getByTestId('economy-xp_bonus').locator('strong')).toHaveText('—');
  await expect(page.getByTestId('economy-xp_bonus')).toContainText('Известно в 0 из 20');
  await expect(page.getByTestId('economy-credits_net').locator('strong')).toHaveText('—');
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await page.getByRole('button', { name: 'Подробности боя 1', exact: true }).click();
  await page.getByRole('button', { name: 'Опыт и экономика', exact: true }).click();
  await expect(bonus.locator('strong')).toHaveText('—');
  await expect(net.locator('strong')).toHaveText('—');
});

test('friendly labels are displayed while filters, preferences and goals send the stable selector', async ({ page }) => {
  const requests = await serve(page);
  await page.goto('/?demo=1');
  await expect(page.getByRole('button', { name: 'Выбрать танк', exact: true })).toContainText('Т-34');
  await page.getByRole('button', { name: 'Выбрать танк', exact: true }).click();
  await page.getByRole('option', { name: /ИС-7/ }).click();
  await expect(page.getByRole('button', { name: 'Выбрать танк', exact: true })).toContainText('ИС-7');
  expect(requests[requests.length - 1].vehicle).toBe('type:508');
  await expect(page.getByTestId('coach-card')).toContainText('ИС-7');
  await expect(page.locator('.panel')).not.toContainText('type:508');
  await page.getByRole('button', { name: 'История боёв', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Последние бои' })).toContainText('ИС-7');
  await page.getByRole('button', { name: 'Настройки', exact: true }).click();
  await expect(page.getByText(/Будут сохранены фильтры сверху:/)).toContainText('ИС-7');
  await page.getByRole('button', { name: 'Сохранить вид и фильтры', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('Вид и фильтры сохранены');
  const preferenceRequest = requests.find(r => r.action === 'save_preferences');
  if (preferenceRequest?.action !== 'save_preferences') throw new Error('Preference command was not sent');
  expect(preferenceRequest.preferences?.vehicle).toBe('type:508');
  await page.getByRole('group', { name: 'Раздел настроек' }).getByRole('button', { name: 'Цели', exact: true }).click();
  await page.getByRole('button', { name: 'Изменить цель ИС-7 10', exact: true }).click();
  await page.getByRole('textbox', { name: 'Целевой средний урон' }).fill('1700');
  await page.getByRole('button', { name: 'Сохранить цель', exact: true }).click();
  await expect(page.getByTestId('operation-result')).toContainText('Цель сохранена');
  const goalRequest = requests.find(r => r.action === 'save_goal');
  if (goalRequest?.action !== 'save_goal') throw new Error('Goal command was not sent');
  expect(goalRequest.goal).toEqual({ vehicle: 'type:508', window: 10, target_avg_damage: 1700 });
});
