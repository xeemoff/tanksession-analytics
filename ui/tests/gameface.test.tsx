import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { Button } from '../src/Button';
import { GAMEFACE_SCROLL_STEP, gamefaceWheelDistance, handlePanelWheel, scrollPanel, PanelWheelEvent } from '../src/scroll';

test('native wheel ticks and Windows packets scroll up with positive input and down with negative input', () => {
  for (const packet of [1, 120]) {
    assert.equal(gamefaceWheelDistance(packet), -GAMEFACE_SCROLL_STEP);
    assert.equal(gamefaceWheelDistance(-packet), GAMEFACE_SCROLL_STEP);
  }
  assert.equal(gamefaceWheelDistance(0.25), -24);
  assert.equal(gamefaceWheelDistance(-3, 1), GAMEFACE_SCROLL_STEP);
  assert.equal(gamefaceWheelDistance(-1, 2, 500), 400);
  assert.equal(gamefaceWheelDistance(-120000, 0, 500), 400);
  for (const invalid of [0, NaN, Infinity, -Infinity]) assert.equal(gamefaceWheelDistance(invalid), 0);
});

test('native wheel cancels default once, clamps at edges, and browser previews retain native scrolling', () => {
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
