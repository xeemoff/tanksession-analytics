import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { DamageBars, formatNumber, SnapshotView, Trend } from '../src/App';
import { snapshot } from './helpers';

test('unknown values render as a dash while zero remains a number', () => {
  assert.equal(formatNumber(null), '—');
  assert.equal(formatNumber(0), '0');
  assert.equal(formatNumber(2001.5, 1), '2 001,5');
});
test('the view escapes names and makes incomplete data visible', () => {
  const value = snapshot();
  value.history[0].vehicle = '<script>alert(1)</script>';
  const html = renderToStaticMarkup(<SnapshotView snapshot={value} />);
  assert(!html.includes('<script>'));
  assert(html.includes('&lt;script&gt;'));
  assert(html.includes('Неполных результатов: 2'));
});
test('an unavailable account never renders statistics from a stale payload', () => {
  const value = { ...snapshot(), status: 'account_unavailable' as const };
  const html = renderToStaticMarkup(<SnapshotView snapshot={value} />);
  assert(html.includes('Аккаунт ещё не определён'));
  assert(!html.includes('IS-7'));
  assert(!html.includes('battle-count'));
});
test('the chart preserves gaps instead of connecting unknown damage', () => {
  const html = renderToStaticMarkup(<Trend series={snapshot().series} windowSize={10} />);
  const paths = html.match(/stroke="#dfb875"/g) || [];
  assert.equal(paths.length, 2);
  assert.equal((html.match(/<circle /g) || []).length, 2);
});

test('single zero damage and unknown damage are visually distinct', () => {
  const html = renderToStaticMarkup(<DamageBars points={[
    { battle: 1, damage: 0, outcome: 'loss' },
    { battle: 2, damage: null, outcome: 'unknown' }
  ]} />);
  assert(html.includes('height:2px'));
  assert(html.includes('damage-unknown'));
  assert(html.includes('0 урона'));
  assert(html.includes('урон неизвестен'));
  assert(html.includes('Поражение'));
});
