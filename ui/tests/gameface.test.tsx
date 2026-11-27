import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { Button } from '../src/Button';
import { GAMEFACE_SCROLL_STEP, gamefaceWheelDistance, handlePanelKey, handlePanelWheel, panelViewportHeight, scrollPanel, PanelWheelEvent, ScrollPosition } from '../src/scroll';

test('native wheel ticks and Windows packets scroll up with positive input and down with negative input', () => {
  for (const packet of [1, 120]) {
    assert.equal(gamefaceWheelDistance(packet), -GAMEFACE_SCROLL_STEP);
    assert.equal(gamefaceWheelDistance(-packet), GAMEFACE_SCROLL_STEP);
  }
  assert.equal(gamefaceWheelDistance(0.25), -24);
  assert.equal(gamefaceWheelDistance(-3, 1), GAMEFACE_SCROLL_STEP);
  assert.equal(gamefaceWheelDistance(-1, 2, 500), 400);
  assert.equal(gamefaceWheelDistance(-120000, 0, 500), 400);
  for (const missingSize of [0, NaN, Infinity]) assert.equal(gamefaceWheelDistance(-120, 0, missingSize), GAMEFACE_SCROLL_STEP);
  for (const invalid of [0, NaN, Infinity, -Infinity]) assert.equal(gamefaceWheelDistance(invalid), 0);
});

test('native wheel cancels successful movement and known edges while browser previews retain native scrolling', () => {
  const panel = { scrollTop: 150, scrollHeight: 900, clientHeight: 500 };
  let canceled = 0;
  const event: PanelWheelEvent = { deltaY: -120, cancelable: true, preventDefault() { canceled += 1; } };
  assert.equal(handlePanelWheel(panel, event, 'gameface'), true);
  assert.equal(panel.scrollTop, 246);
  assert.equal(canceled, 1);
  panel.scrollTop = 390;
  assert.equal(handlePanelWheel(panel, event, 'gameface'), true);
  assert.equal(panel.scrollTop, 400);
  assert.equal(handlePanelWheel(panel, event, 'gameface'), true);
  assert.equal(panel.scrollTop, 400);
  assert.equal(canceled, 3);
  for (const mode of ['demo', 'local'] as const) {
    assert.equal(handlePanelWheel(panel, event, mode), false);
    assert.equal(panel.scrollTop, 400);
    assert.equal(canceled, 3);
  }
  event.deltaY = 120;
  panel.scrollTop = 10;
  handlePanelWheel(panel, event, 'gameface');
  assert.equal(panel.scrollTop, 0);
});

test('pre-1.54 geometry without clientHeight supports wheel, footer and page keys without NaN', () => {
  // Gameface 1.54.0 added clientHeight. This reproduces the RC2 failure without
  // relying on Chromium's complete DOM implementation.
  const panel: ScrollPosition = { scrollTop: 0, scrollHeight: 1600, offsetHeight: 500 };
  let canceled = 0;
  assert.equal(panelViewportHeight(panel), 500);
  assert.equal(handlePanelWheel(panel, { deltaY: -1, preventDefault() { canceled += 1; } }, 'gameface'), true);
  assert.equal(panel.scrollTop, 96);
  assert.equal(canceled, 1);
  assert.equal(scrollPanel(panel, GAMEFACE_SCROLL_STEP * 2), true);
  assert.equal(panel.scrollTop, 288);
  assert.equal(handlePanelKey(panel, 'PageDown'), true);
  assert.equal(panel.scrollTop, 688);
  assert.equal(handlePanelKey(panel, 'End'), true);
  assert.equal(panel.scrollTop, 1100);
  assert.equal(handlePanelKey(panel, 'PageUp'), true);
  assert.equal(panel.scrollTop, 700);
  assert.equal(handlePanelKey(panel, 'Home'), true);
  assert.equal(panel.scrollTop, 0);
  assert.equal(handlePanelKey(panel, 'ArrowRight'), false);
});

test('zero or nonfinite geometry falls back to measured bounds and never writes NaN', () => {
  const panel: ScrollPosition = { scrollTop: 0, scrollHeight: 900, clientHeight: NaN,
    offsetHeight: 0, getBoundingClientRect: () => ({ height: 400 }) };
  assert.equal(panelViewportHeight(panel), 400);
  assert.equal(scrollPanel(panel, 900), true);
  assert.equal(panel.scrollTop, 500);

  // An unavailable first-frame size can still use the DOM setter's own clamp.
  let position = 0;
  const noGeometry = { scrollHeight: 900, get scrollTop() { return position; },
    set scrollTop(value: number) { assert.ok(Number.isFinite(value)); position = Math.max(0, Math.min(400, value)); } };
  assert.equal(scrollPanel(noGeometry, 192), true);
  assert.equal(noGeometry.scrollTop, 192);
  assert.equal(scrollPanel(noGeometry, 900), true);
  assert.equal(noGeometry.scrollTop, 400);
});

test('unsupported or rejected setters do not suppress the native wheel fallback', () => {
  for (const throws of [false, true]) {
    const panel = { scrollHeight: 1000, offsetHeight: 500, get scrollTop() { return 100; },
      set scrollTop(_value: number) { if (throws) throw new Error('unsupported setter'); } };
    const event = { deltaY: -120, preventDefault() { assert.fail('a failed custom move must not swallow native input'); } };
    assert.equal(handlePanelWheel(panel, event, 'gameface'), false);
    assert.equal(scrollPanel(panel, 192), false);
    assert.equal(handlePanelKey(panel, 'PageDown'), false);
  }
});

test('already handled, noncancelable, modified and horizontal wheel events never double-scroll the panel', () => {
  const panel = { scrollTop: 120, scrollHeight: 900, clientHeight: 500 };
  for (const values of [
    { defaultPrevented: true }, { cancelable: false }, { ctrlKey: true }, { shiftKey: true }, { deltaX: 240 }, { deltaY: 0 }
  ]) {
    const event = { deltaY: 120, ...values, preventDefault() { assert.fail('unhandled event must not be canceled'); } };
    assert.equal(handlePanelWheel(panel, event, 'gameface'), false);
    assert.equal(panel.scrollTop, 120);
  }
  scrollPanel(panel, NaN);
  assert.equal(panel.scrollTop, 120);
  scrollPanel(panel, 900);
  assert.equal(panel.scrollTop, 400);
  scrollPanel(panel, -900);
  assert.equal(panel.scrollTop, 0);
});

test('buttons retain native disabled semantics and expose compatible visual states', () => {
  const enabled = renderToStaticMarkup(<Button type="button" className="detail-button">Открыть</Button>);
  const disabled = renderToStaticMarkup(<Button type="button" className="detail-button" disabled>Открыть</Button>);
  assert.match(enabled, /class="detail-button is-enabled"/);
  assert.doesNotMatch(enabled, / disabled=/);
  assert.match(disabled, /class="detail-button is-disabled"/);
  assert.match(disabled, / disabled=""/);
});

test('styles avoid selectors and inherit values rejected by the client Gameface build', () => {
  const css = readFileSync('src/styles.css', 'utf8');
  assert.doesNotMatch(css, /:(?:disabled|not)\b/);
  assert.doesNotMatch(css, /\b(?:font(?:-family)?|color)\s*:\s*inherit\b/);
});
