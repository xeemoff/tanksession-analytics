import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { ExtendedMetrics, parseSnapshot, Snapshot } from '../src/contracts';
import { EconomyMetrics } from '../src/SummaryExtras';
import { snapshot } from './helpers';

function metrics(): ExtendedMetrics {
  return {
    version: 1,
    fields: {
      kills: { samples: 0, average: null }, xp_base: { samples: 1, average: 500 },
      credits_gross: { samples: 1, average: 1000 }, credits_net: { samples: 1, average: -120 }
    },
    survival: { samples: 0, survived: 0, rate: null },
    accuracy: { samples: 0, shots: 0, hits: 0, rate: null },
    penetration: { samples: 0, hits: 0, penetrations: 0, rate: null }, maps: []
  };
}

function economySnapshot(): Snapshot {
  const result = snapshot();
  result.metrics = metrics();
  return result;
}

test('bonus XP is additive: legacy, unknown and known zero snapshots remain distinct', () => {
  const result = economySnapshot();
  assert.equal(parseSnapshot(result).history[0].xp_bonus, undefined);
  assert.equal(parseSnapshot(result).metrics!.fields.xp_bonus, undefined);
  result.history[0].xp_bonus = null;
  result.metrics!.fields.xp_bonus = { samples: 0, average: null };
  assert.equal(parseSnapshot(result).history[0].xp_bonus, null);
  result.history[0].xp_bonus = 0;
  result.metrics!.fields.xp_bonus = { samples: 1, average: 0 };
  assert.equal(parseSnapshot(result).history[0].xp_bonus, 0);
  assert.equal(parseSnapshot(result).metrics!.fields.xp_bonus!.average, 0);
  assert.equal(parseSnapshot(result).metrics!.fields.credits_net.average, -120);
});

test('bonus XP rejects invalid counters and inconsistent sample coverage', () => {
  const corruptions: Array<(value: Snapshot) => void> = [
    value => { value.history[0].xp_bonus = -1; },
    value => { value.history[0].xp_bonus = 1.5; },
    value => { value.history[0].xp_bonus = Number.MAX_SAFE_INTEGER + 1; },
    value => { value.history[0].xp_bonus = '10' as never; },
    value => { value.metrics!.fields.xp_bonus = { samples: 0, average: 0 }; },
    value => { value.metrics!.fields.xp_bonus = { samples: 1, average: null }; },
    value => { value.metrics!.fields.xp_bonus = { samples: value.summary.battles + 1, average: 10 }; },
    value => { value.metrics!.fields.xp_bonus = { samples: 1, average: -10 }; },
    value => { value.metrics!.fields.xp_bonus = { samples: 1, average: NaN }; }
  ];
  for (const corrupt of corruptions) {
    const value = economySnapshot();
    corrupt(value);
    assert.throws(() => parseSnapshot(value));
  }
});

test('economy cards show source bonus XP and signed net credits with independent coverage', () => {
  const fields = metrics().fields;
  fields.xp_bonus = { samples: 2, average: 70 };
  const html = renderToStaticMarkup(<EconomyMetrics fields={fields} battles={20} />);
  assert.match(html, /Средний базовый опыт<\/span><strong>500<\/strong>/);
  assert.match(html, /Средний бонусный опыт<\/span><strong>70<\/strong><small>Известно в 2 из 20/);
  assert.match(html, /Итог кредитов в среднем<\/span><strong>-120<\/strong><small>Известно в 1 из 20/);
});

test('missing bonus XP is never inferred from other XP and zero stays visible', () => {
  const fields = metrics().fields;
  let html = renderToStaticMarkup(<EconomyMetrics fields={fields} battles={20} />);
  assert.match(html, /Средний бонусный опыт<\/span><strong>—<\/strong><small>Известно в 0 из 20/);
  fields.xp_bonus = { samples: 2, average: 0 };
  fields.credits_net = { samples: 0, average: null };
  html = renderToStaticMarkup(<EconomyMetrics fields={fields} battles={20} />);
  assert.match(html, /Средний бонусный опыт<\/span><strong>0<\/strong><small>Известно в 2 из 20/);
  assert.match(html, /Итог кредитов в среднем<\/span><strong>—<\/strong><small>Известно в 0 из 20/);
});
