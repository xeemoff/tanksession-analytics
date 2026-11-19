export type WindowSize = 10 | 30 | 100;
export type Mode = 'gameface' | 'demo' | 'local';
export interface Selection { vehicle: string; window: WindowSize }
export interface SnapshotRequest extends Selection { protocol: 1; request_id: string }
export interface Summary {
  battles: number; known_outcomes: number; wins: number; losses: number; draws: number;
  win_rate: number | null; avg_damage: number | null; avg_xp: number | null; damage_samples: number;
}
export interface Goal {
  vehicle: string; target: number; window: number; battles: number; known_damage: number;
  avg_damage: number | null;
  status: 'no_data' | 'in_progress' | 'insufficient_data' | 'achieved' | 'not_achieved';
}
export interface Snapshot {
  protocol: 1; source: 'game' | 'demo'; status: 'ready' | 'empty' | 'account_unavailable';
  request_id: string; selection: Selection;
  vehicles: Array<{ name: string; battles: number }>;
  summary: Summary;
  comparison: {
    window: WindowSize; current: Summary; previous: Summary | null;
    enough_current: boolean; enough_previous: boolean;
    damage_delta: number | null; win_rate_delta_pp: number | null;
  };
  series: Array<{ battle: number; avg_damage: number | null; known_damage: number }>;
  goals: Goal[];
  history: Array<{ timestamp: number; vehicle: string; outcome: string | null; damage: number | null; xp: number | null }>;
  quality: { total_records: number; incomplete_records: number; invalid_records: number; conflicts: number };
  updated_at: number;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function number(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER; }
function count(value: unknown): value is number { return number(value) && value >= 0 && Number.isSafeInteger(value); }
function metric(value: unknown): value is number | null { return value === null || (number(value) && value >= 0); }
function nullableNumber(value: unknown): boolean { return value === null || number(value); }
function text(value: unknown, limit = 128): value is string { return typeof value === 'string' && value.length <= limit; }
function array(value: unknown, max: number): value is unknown[] { return Array.isArray(value) && value.length <= max; }
function summary(value: unknown): value is Summary {
  if (!record(value)) return false;
  return ['battles', 'known_outcomes', 'wins', 'losses', 'draws', 'damage_samples'].every(key => count(value[key]))
    && ['win_rate', 'avg_damage', 'avg_xp'].every(key => metric(value[key]))
    && (value.win_rate === null || (value.win_rate as number) <= 100)
    && (value.known_outcomes as number) <= (value.battles as number)
    && (value.damage_samples as number) <= (value.battles as number);
}
function selection(value: unknown): value is Selection {
  return record(value) && text(value.vehicle) && [10, 30, 100].indexOf(value.window as number) !== -1;
}

export function decodePayload(raw: unknown): unknown {
  if (typeof raw === 'string') {
    if (raw.length > 512 * 1024) throw new Error('Ответ превышает допустимый размер.');
    try { raw = JSON.parse(raw); } catch { throw new Error('Не удалось прочитать ответ мода.'); }
  }
  return raw;
}

/** Validate the complete boundary before data reaches the renderer. */
export function parseSnapshot(raw: unknown): Snapshot {
  raw = decodePayload(raw);
  const fail = () => { throw new Error('Формат данных не поддерживается этой версией панели.'); };
  if (!record(raw) || raw.protocol !== 1 || !['game', 'demo'].includes(raw.source as string)
      || !['ready', 'empty', 'account_unavailable'].includes(raw.status as string)
      || !text(raw.request_id, 64) || !selection(raw.selection) || !summary(raw.summary)
      || !count(raw.updated_at) || raw.updated_at > 253402300799) return fail();
  if (!array(raw.vehicles, 2048) || !raw.vehicles.every(v => record(v) && text(v.name) && count(v.battles))) return fail();
  const comparison = raw.comparison;
  if (!record(comparison) || ![10, 30, 100].includes(comparison.window as number)
      || !summary(comparison.current) || !(comparison.previous === null || summary(comparison.previous))
      || typeof comparison.enough_current !== 'boolean' || typeof comparison.enough_previous !== 'boolean'
      || !nullableNumber(comparison.damage_delta) || !nullableNumber(comparison.win_rate_delta_pp)) return fail();
  if (!array(raw.series, 60) || !raw.series.every(v => record(v) && count(v.battle) && metric(v.avg_damage) && count(v.known_damage))) return fail();
  if (!array(raw.goals, 30) || !raw.goals.every(v => record(v) && text(v.vehicle)
      && count(v.target) && count(v.window) && count(v.battles) && count(v.known_damage)
      && metric(v.avg_damage) && ['no_data', 'in_progress', 'insufficient_data', 'achieved', 'not_achieved'].includes(v.status as string))) return fail();
  if (!array(raw.history, 12) || !raw.history.every(v => record(v) && count(v.timestamp) && v.timestamp <= 253402300799 && text(v.vehicle)
      && [null, 'unknown', 'win', 'loss', 'draw'].includes(v.outcome as string | null) && metric(v.damage) && metric(v.xp))) return fail();
  if (!record(raw.quality) || !['total_records', 'incomplete_records', 'invalid_records', 'conflicts'].every(key => count((raw.quality as Record<string, unknown>)[key]))) return fail();
  return raw as unknown as Snapshot;
}

export function queryFlag(search: string, key: string): boolean {
  return search.replace(/^\?/, '').split('&').some(part => part === key + '=1');
}
export function getMode(search: string): Mode {
  if (queryFlag(search, 'demo')) return 'demo';
  if (queryFlag(search, 'local')) return 'local';
  return 'gameface';
}
