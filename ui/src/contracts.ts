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
export interface Coach {
  version: 1;
  status: 'choose_vehicle' | 'empty' | 'collecting' | 'incomplete' | 'mixed_modes' | 'ready';
  vehicle: string; window: WindowSize; battles: number; required_battles: number; remaining_battles: number;
  coverage: { current_battles: number; current_damage: number; previous_battles: number; previous_damage: number };
  comparison: null | {
    current_avg: number; previous_avg: number; delta: number; delta_percent: number | null;
    current_median: number; previous_median: number; median_delta: number;
  };
  records: {
    best_damage: number | null; latest_damage: number | null; previous_best_damage: number | null;
    new_damage_record: boolean;
    best_window_avg: number | null; previous_best_window_avg: number | null; current_window_avg: number | null;
    new_window_record: boolean;
  };
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
  coach?: Coach;
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

function coach(value: unknown, window: WindowSize): value is Coach {
  if (!record(value) || value.version !== 1 || !['choose_vehicle', 'empty', 'collecting', 'incomplete', 'mixed_modes', 'ready'].includes(value.status as string)
      || !text(value.vehicle) || value.window !== window || !count(value.battles)
      || value.required_battles !== window * 2 || !count(value.remaining_battles)
      || value.remaining_battles !== Math.max(0, window * 2 - value.battles)) return false;
  const coverage = value.coverage;
  if (!record(coverage) || !['current_battles', 'current_damage', 'previous_battles', 'previous_damage'].every(key => count(coverage[key]))) return false;
  if ((coverage.current_battles as number) > window || (coverage.previous_battles as number) > window
      || (coverage.current_damage as number) > (coverage.current_battles as number)
      || (coverage.previous_damage as number) > (coverage.previous_battles as number)
      || coverage.current_battles !== Math.min(window, value.battles)
      || coverage.previous_battles !== Math.min(window, Math.max(0, value.battles - window))) return false;
  const comparison = value.comparison;
  if (value.status === 'ready') {
    if (!value.vehicle || value.remaining_battles !== 0 || coverage.current_damage !== window || coverage.previous_damage !== window
        || !record(comparison) || !['current_avg', 'previous_avg', 'current_median', 'previous_median'].every(key => number(comparison[key]) && (comparison[key] as number) >= 0)
        || !number(comparison.delta) || !number(comparison.median_delta) || !nullableNumber(comparison.delta_percent)) return false;
  } else if (comparison !== null) return false;
  if (value.status === 'collecting' && (!value.vehicle || value.battles === 0 || value.remaining_battles === 0)) return false;
  if (value.status === 'incomplete' && (!value.vehicle || value.remaining_battles !== 0
      || (coverage.current_damage === window && coverage.previous_damage === window))) return false;
  if (value.status === 'mixed_modes' && (!value.vehicle || value.remaining_battles !== 0)) return false;
  if ((value.status === 'empty' || value.status === 'choose_vehicle') && value.battles !== 0) return false;
  const records = value.records;
  if (!record(records) || !['best_damage', 'latest_damage', 'previous_best_damage'].every(key => records[key] === null || count(records[key]))
      || !['best_window_avg', 'previous_best_window_avg', 'current_window_avg'].every(key => metric(records[key]))
      || typeof records.new_damage_record !== 'boolean' || typeof records.new_window_record !== 'boolean') return false;
  const r = records as unknown as Coach['records'];
  const maximum = (a: number | null, b: number | null) => a === null ? b : b === null ? a : Math.max(a, b);
  if (r.best_damage !== maximum(r.latest_damage, r.previous_best_damage)
      || r.best_window_avg !== maximum(r.current_window_avg, r.previous_best_window_avg)) return false;
  if (r.new_damage_record !== (r.latest_damage !== null && r.previous_best_damage !== null
      && r.latest_damage > r.previous_best_damage)) return false;
  if (r.new_window_record && (r.current_window_avg === null || r.previous_best_window_avg === null
      || r.current_window_avg < r.previous_best_window_avg)) return false;
  // Exact sums can improve while both displayed averages round to the same
  // tenth. Equality is valid with either flag; a displayed decrease is not.
  if (!r.new_window_record && r.current_window_avg !== null && r.previous_best_window_avg !== null
      && r.current_window_avg > r.previous_best_window_avg) return false;
  if ((r.current_window_avg !== null) !== (coverage.current_battles === window && coverage.current_damage === window)
      || (value.battles <= window && r.previous_best_window_avg !== null)
      || (value.battles <= 1 && r.previous_best_damage !== null)
      || (r.best_window_avg !== null && (r.best_damage === null || r.best_window_avg > r.best_damage))
      || (r.previous_best_window_avg !== null && (r.previous_best_damage === null || r.previous_best_window_avg > r.previous_best_damage))) return false;
  if (value.status === 'ready' && r.current_window_avg !== (comparison as Record<string, unknown>).current_avg) return false;
  if (value.battles === 0 && (records.new_damage_record || records.new_window_record
      || ['best_damage', 'latest_damage', 'previous_best_damage', 'best_window_avg', 'previous_best_window_avg', 'current_window_avg'].some(key => records[key] !== null))) return false;
  return true;
}

function coachScope(value: Coach, selected: Selection, status: Snapshot['status'], vehicles: Snapshot['vehicles'], battles: number): boolean {
  if (status === 'account_unavailable') return value.status === 'empty' && value.vehicle === '';
  if (status === 'empty') {
    return selected.vehicle === 'unknown'
      ? value.status === 'choose_vehicle' && value.vehicle === ''
      : value.status === 'empty' && value.vehicle === selected.vehicle;
  }
  const needsChoice = selected.vehicle === 'unknown' || (!selected.vehicle
    && (vehicles.length > 1 || (vehicles.length === 1 && vehicles[0].name === 'unknown')));
  if (needsChoice) return value.status === 'choose_vehicle' && value.vehicle === '';
  const vehicle = selected.vehicle || (vehicles.length === 1 ? vehicles[0].name : '');
  const available = vehicles.find(item => item.name === vehicle);
  return !!vehicle && vehicle !== 'unknown' && !!available && available.battles > 0
    && value.status !== 'empty' && value.status !== 'choose_vehicle'
    && value.vehicle === vehicle && value.battles === battles && value.battles === available.battles;
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
  // Optional additive protocol-1 extension; older hosts remain readable.
  if ('coach' in raw && (!coach(raw.coach, raw.selection.window)
      || !coachScope(raw.coach, raw.selection, raw.status as Snapshot['status'], raw.vehicles as Snapshot['vehicles'], raw.summary.battles))) return fail();
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
