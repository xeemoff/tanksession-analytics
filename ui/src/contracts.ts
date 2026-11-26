export type WindowSize = 10 | 30 | 100;
export type Mode = 'gameface' | 'demo' | 'local';
export type PanelSection = 'progress' | 'dynamics' | 'history' | 'summary' | 'settings';
export interface Selection { vehicle: string; window: WindowSize; page?: number }
export interface Preferences { vehicle: string; window: WindowSize; tab: PanelSection; density: 'normal' | 'compact'; contrast: 'standard' | 'high' }
export interface GoalDefinition { vehicle: string; window: number; target_avg_damage: number }
export type UserCommand = { action: 'initialize' | 'export_csv' }
  | { action: 'save_preferences'; preferences: Preferences }
  | { action: 'save_goal'; goal: GoalDefinition }
  | { action: 'delete_goal'; goal: Pick<GoalDefinition, 'vehicle' | 'window'> };
export type SnapshotRequest = Selection & { protocol: 1; request_id: string } & Partial<UserCommand>;
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
export type ObservedOutcome = 'win' | 'loss' | 'draw' | 'unknown';
export interface BattlePoint { battle: number; damage: number | null; outcome: ObservedOutcome }
export interface InsightGroup { label: string; summary: Summary }
export interface AssistanceMetric { samples: number; average: number | null }
export interface Insights {
  version: 1;
  pending_count: number | null;
  recent_damage: BattlePoint[];
  streak: { outcome: Exclude<ObservedOutcome, 'unknown'> | null; length: number };
  days: InsightGroup[];
  tanks: InsightGroup[];
  assistance_radio: AssistanceMetric;
  assistance_track: AssistanceMetric;
}
export interface HistoryBattle {
  timestamp: number; vehicle: string; outcome: string | null; damage: number | null; xp: number | null;
  map?: string | null; kills?: number | null; survived?: boolean | null;
  shots?: number | null; direct_hits?: number | null; penetrations?: number | null;
  xp_base?: number | null; credits_gross?: number | null; credits_net?: number | null;
  assistance_radio?: number | null; assistance_track?: number | null;
}
export interface Workspace {
  version: 1; can_edit: boolean; preferences: Preferences; goals: GoalDefinition[];
  operation: null | { status: 'saved' | 'deleted' | 'exported' | 'error'; code: string; filename?: string; rows?: number };
}
export interface ExtendedMetrics {
  version: 1;
  fields: Record<'kills' | 'xp_base' | 'credits_gross' | 'credits_net', AssistanceMetric>;
  survival: { samples: number; survived: number; rate: number | null };
  accuracy: { samples: number; shots: number; hits: number; rate: number | null };
  penetration: { samples: number; hits: number; penetrations: number; rate: number | null };
  maps: InsightGroup[];
}
export interface Sessions {
  version: 1; gap_minutes: 60; basis: 'received_at';
  items: Array<{ started_at: number; ended_at: number; summary: Summary; median_damage: number | null }>;
  comparison: {
    status: 'choose_vehicle' | 'insufficient_data' | 'incomplete' | 'mixed_modes' | 'mode_unknown' | 'ready';
    minimum_battles: number; current_battles: number; previous_battles: number;
    current_average: number | null; previous_average: number | null;
    current_median: number | null; previous_median: number | null;
    delta_average: number | null; delta_median: number | null;
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
  history: HistoryBattle[];
  quality: { total_records: number; incomplete_records: number; invalid_records: number; conflicts: number };
  coach?: Coach;
  insights?: Insights;
  pagination?: { page: number; page_size: 5; pages: number; total: number };
  workspace?: Workspace;
  metrics?: ExtendedMetrics;
  sessions?: Sessions;
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
  return record(value) && text(value.vehicle) && [10, 30, 100].indexOf(value.window as number) !== -1
    && (!('page' in value) || count(value.page));
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

function validInsights(value: unknown, totals: Summary, status: Snapshot['status'], selected: Selection): value is Insights {
  if (!record(value) || value.version !== 1
      || !(value.pending_count === null || count(value.pending_count))
      || !array(value.recent_damage, 24)
      || value.recent_damage.length !== Math.min(24, totals.battles)) return false;
  if (!value.recent_damage.every((point, index) => record(point)
      && point.battle === totals.battles - Math.min(24, totals.battles) + index + 1
      && (point.damage === null || count(point.damage))
      && ['win', 'loss', 'draw', 'unknown'].includes(point.outcome as string))) return false;
  const streak = value.streak;
  if (!record(streak) || !count(streak.length)
      || ![null, 'win', 'loss', 'draw'].includes(streak.outcome as string | null)
      || (streak.outcome === null) !== (streak.length === 0)) return false;
  const points = value.recent_damage as unknown as BattlePoint[];
  const latest = points.length ? points[points.length - 1].outcome : 'unknown';
  if (streak.outcome !== (latest === 'unknown' ? null : latest)) return false;
  if (streak.outcome !== null) {
    const bound = streak.outcome === 'win' ? totals.wins : streak.outcome === 'loss' ? totals.losses : totals.draws;
    if (streak.length > bound) return false;
    let tail = 0;
    for (let i = points.length - 1; i >= 0 && points[i].outcome === latest; i--) tail++;
    if (tail < points.length ? streak.length !== tail : streak.length < tail) return false;
  }
  const groups = (items: unknown, limit: number, days: boolean): boolean => {
    if (!array(items, limit)) return false;
    const labels = new Set<string>();
    let total = 0;
    for (const item of items) {
      if (!record(item) || !text(item.label, days ? 10 : 128) || !item.label
          || (days && !/^\d{4}-\d{2}-\d{2}$/.test(item.label))
          || (!days && !!selected.vehicle && item.label !== selected.vehicle)
          || labels.has(item.label) || !summary(item.summary) || item.summary.battles === 0
          || item.summary.wins + item.summary.losses + item.summary.draws !== item.summary.known_outcomes) return false;
      labels.add(item.label);
      total += item.summary.battles;
    }
    return total <= totals.battles;
  };
  if (!groups(value.days, 14, true) || !groups(value.tanks, 20, false)) return false;
  const assistance = (item: unknown) => record(item) && count(item.samples)
    && item.samples <= totals.battles && metric(item.average)
    && ((item.average === null) === (item.samples === 0));
  if (!assistance(value.assistance_radio) || !assistance(value.assistance_track)) return false;
  if (status === 'account_unavailable' && (value.pending_count !== null || totals.battles !== 0)) return false;
  return true;
}

function validWorkspace(value: unknown): value is Workspace {
  if (!record(value) || value.version !== 1 || typeof value.can_edit !== 'boolean' || !record(value.preferences)) return false;
  const p = value.preferences;
  if (!selection(p) || !['progress', 'dynamics', 'history', 'summary', 'settings'].includes(p.tab as string)
      || !['normal', 'compact'].includes(p.density as string) || !['standard', 'high'].includes(p.contrast as string)) return false;
  if (!array(value.goals, 30) || !value.goals.every(g => record(g) && text(g.vehicle) && !!g.vehicle
      && count(g.window) && g.window >= 10 && g.window <= 1000 && count(g.target_avg_damage)
      && g.target_avg_damage > 0 && g.target_avg_damage <= 50000)) return false;
  const op = value.operation;
  return op === null || (record(op) && ['saved', 'deleted', 'exported', 'error'].includes(op.status as string)
    && text(op.code, 64) && (!('rows' in op) || count(op.rows))
    && (!('filename' in op) || (text(op.filename, 180) && !!op.filename && !/[\\/:\x00-\x1f]/.test(op.filename))));
}

function validMetrics(value: unknown, total: number): value is ExtendedMetrics {
  if (!record(value) || value.version !== 1 || !record(value.fields)) return false;
  const fields = value.fields;
  for (const key of ['kills', 'xp_base', 'credits_gross', 'credits_net']) {
    const field = fields[key];
    if (!record(field) || !count(field.samples) || field.samples > total
        || !(key === 'credits_net' ? nullableNumber(field.average) : metric(field.average))
        || (field.samples === 0) !== (field.average === null)) return false;
  }
  const rate = (v: unknown) => v === null || (number(v) && v >= 0 && v <= 100);
  for (const key of ['survival', 'accuracy', 'penetration']) {
    const data = value[key];
    if (!record(data) || !count(data.samples) || data.samples > total || !rate(data.rate)) return false;
    const counts = key === 'survival' ? ['survived'] : key === 'accuracy' ? ['shots', 'hits'] : ['hits', 'penetrations'];
    if (!counts.every(field => count(data[field])) || (data.samples === 0 && data.rate !== null)) return false;
    if (key === 'survival' && (data.survived as number) > data.samples) return false;
  }
  if (!array(value.maps, 20)) return false;
  let sum = 0;
  const labels = new Set<string>();
  for (const group of value.maps) {
    if (!record(group) || !text(group.label) || !group.label || labels.has(group.label) || !summary(group.summary)) return false;
    labels.add(group.label); sum += group.summary.battles;
  }
  return sum <= total;
}

function validSessions(value: unknown, total: number): value is Sessions {
  if (!record(value) || value.version !== 1 || value.gap_minutes !== 60 || value.basis !== 'received_at'
      || !array(value.items, 7)) return false;
  let sum = 0;
  for (const item of value.items) {
    if (!record(item) || !count(item.started_at) || !count(item.ended_at) || item.started_at > item.ended_at
        || item.ended_at > 253402300799 || !summary(item.summary) || !metric(item.median_damage)) return false;
    sum += item.summary.battles;
  }
  const c = value.comparison;
  if (sum > total || !record(c) || !['choose_vehicle', 'insufficient_data', 'incomplete', 'mixed_modes', 'mode_unknown', 'ready'].includes(c.status as string)
      || !count(c.minimum_battles) || c.minimum_battles < 10 || !count(c.current_battles) || !count(c.previous_battles)
      || c.current_battles + c.previous_battles > total) return false;
  const averages = ['current_average', 'previous_average', 'current_median', 'previous_median'];
  if (!averages.every(key => metric(c[key])) || !nullableNumber(c.delta_average) || !nullableNumber(c.delta_median)) return false;
  return c.status !== 'ready' || (c.current_battles >= c.minimum_battles && c.previous_battles >= c.minimum_battles
    && [...averages, 'delta_average', 'delta_median'].every(key => number(c[key])));
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
      && [null, 'unknown', 'win', 'loss', 'draw'].includes(v.outcome as string | null) && metric(v.damage) && metric(v.xp)
      && ['kills', 'shots', 'direct_hits', 'penetrations', 'xp_base', 'credits_gross', 'assistance_radio', 'assistance_track'].every(key => !(key in v) || v[key] === null || count(v[key]))
      && (!('credits_net' in v) || v.credits_net === null || (number(v.credits_net) && Number.isSafeInteger(v.credits_net)))
      && (!('survived' in v) || v.survived === null || typeof v.survived === 'boolean')
      && (!('map' in v) || v.map === null || text(v.map)))) return fail();
  if (!record(raw.quality) || !['total_records', 'incomplete_records', 'invalid_records', 'conflicts'].every(key => count((raw.quality as Record<string, unknown>)[key]))) return fail();
  // Optional additive protocol-1 extension; older hosts remain readable.
  if ('coach' in raw && (!coach(raw.coach, raw.selection.window)
      || !coachScope(raw.coach, raw.selection, raw.status as Snapshot['status'], raw.vehicles as Snapshot['vehicles'], raw.summary.battles))) return fail();
  if ('insights' in raw && !validInsights(raw.insights, raw.summary,
      raw.status as Snapshot['status'], raw.selection)) return fail();
  if ('pagination' in raw) {
    const p = raw.pagination;
    if (!record(p) || !count(p.page) || p.page_size !== 5 || !count(p.pages) || !count(p.total)
        || p.total !== raw.summary.battles || p.pages !== Math.max(1, Math.ceil(p.total / 5))
        || p.page >= p.pages || raw.history.length !== Math.min(5, Math.max(0, p.total - p.page * 5))) return fail();
  }
  if ('workspace' in raw && !validWorkspace(raw.workspace)) return fail();
  if ('metrics' in raw && !validMetrics(raw.metrics, raw.summary.battles)) return fail();
  if ('sessions' in raw && !validSessions(raw.sessions, raw.summary.battles)) return fail();
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
