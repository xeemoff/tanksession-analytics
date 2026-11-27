export type WindowSize = 10 | 30 | 100;
export type Mode = 'gameface' | 'demo' | 'local';
export type PanelSection = 'progress' | 'dynamics' | 'history' | 'summary' | 'analytics' | 'reports' | 'settings';
export type HistorySort = 'time_desc' | 'time_asc' | 'damage_desc' | 'xp_desc' | 'credits_desc';
export type DashboardModule = 'metrics' | 'coach' | 'vehicle' | 'chart' | 'goals' | 'activity' | 'economy' | 'reports';
export type Theme = 'hangar' | 'slate' | 'light';
export type VehicleClass = 'lightTank' | 'mediumTank' | 'heavyTank' | 'AT-SPG' | 'SPG';
export interface VehicleMetadata { vehicle_tier?: number | null; vehicle_class?: VehicleClass | null; vehicle_nation?: string | null }
export interface VehicleEntry extends VehicleMetadata { name: string; label?: string; battles: number }
export interface Selection { vehicle: string; window: WindowSize; page?: number; history_query?: string; history_sort?: HistorySort }
export interface Preferences {
  vehicle: string; window: WindowSize; tab: PanelSection; density: 'normal' | 'compact'; contrast: 'standard' | 'high';
  theme?: Theme; modules?: DashboardModule[]; motion?: 'system' | 'reduced';
}
export interface GoalDefinition { vehicle: string; vehicle_label?: string; window: number; target_avg_damage: number }
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
  vehicle: string; vehicle_label?: string; target: number; window: number; battles: number; known_damage: number;
  avg_damage: number | null;
  status: 'no_data' | 'in_progress' | 'insufficient_data' | 'identity_ambiguous' | 'achieved' | 'not_achieved';
}
export interface Coach {
  version: 1;
  status: 'choose_vehicle' | 'empty' | 'collecting' | 'incomplete' | 'mixed_modes' | 'identity_ambiguous' | 'ready';
  vehicle: string; vehicle_label?: string; window: WindowSize; battles: number; required_battles: number; remaining_battles: number;
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
  consistency?: {
    status: 'ready' | 'insufficient_data' | 'not_comparable'; samples: number; required: number;
    median: number | null; lower_quartile: number | null; upper_quartile: number | null;
    interquartile_range: number | null; median_absolute_deviation: number | null;
  };
  observations?: Array<{
    kind: 'damage_average' | 'damage_median' | 'damage_spread' | 'net_credits';
    current: number; previous: number | null; delta: number | null; samples: number; previous_samples: number;
    window: number; scope: 'last_windows' | 'current_window';
  }>;
  goal_suggestions?: Array<{
    vehicle: string; window: number; target_avg_damage: number; baseline_avg_damage: number; samples: number;
    adjustment_percent: 5; rounding_step: 50; basis: 'recent_window'; requires_confirmation: true;
  }>;
}
export type ObservedOutcome = 'win' | 'loss' | 'draw' | 'unknown';
export interface BattlePoint { battle: number; damage: number | null; outcome: ObservedOutcome }
export interface InsightGroup { label: string; vehicle_label?: string; summary: Summary }
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
export interface HistoryBattle extends VehicleMetadata {
  timestamp: number; vehicle: string; vehicle_label?: string; outcome: string | null; damage: number | null; xp: number | null;
  map?: string | null; map_label?: string | null; kills?: number | null; survived?: boolean | null;
  shots?: number | null; direct_hits?: number | null; penetrations?: number | null;
  xp_base?: number | null; xp_bonus?: number | null; credits_gross?: number | null; credits_net?: number | null;
  assistance_radio?: number | null; assistance_track?: number | null;
}
export interface Workspace {
  version: 1; can_edit: boolean; preferences: Preferences; goals: GoalDefinition[];
  operation: null | { status: 'saved' | 'deleted' | 'exported' | 'error'; code: string; filename?: string; rows?: number };
}
export interface ExtendedMetrics {
  version: 1;
  fields: Record<'kills' | 'xp_base' | 'credits_gross' | 'credits_net', AssistanceMetric>
    & { xp_bonus?: AssistanceMetric };
  survival: { samples: number; survived: number; rate: number | null };
  accuracy: { samples: number; shots: number; hits: number; rate: number | null };
  penetration: { samples: number; hits: number; penetrations: number; rate: number | null };
  maps: InsightGroup[];
}
export interface Sessions {
  version: 1; gap_minutes: 60; basis: 'received_at';
  items: Array<{ started_at: number; ended_at: number; summary: Summary; median_damage: number | null }>;
  comparison: {
    status: 'choose_vehicle' | 'insufficient_data' | 'incomplete' | 'mixed_modes' | 'mode_unknown' | 'identity_ambiguous' | 'ready';
    minimum_battles: number; current_battles: number; previous_battles: number;
    current_average: number | null; previous_average: number | null;
    current_median: number | null; previous_median: number | null;
    delta_average: number | null; delta_median: number | null;
  };
}
export interface TotalMetric extends AssistanceMetric { total: number | null }
export interface AnalysisGroup { key: string; label: string; vehicle_label?: string; summary: Summary; credits_net: TotalMetric }
export interface Analytics {
  version: 1; basis: 'received_at'; timezone: 'UTC';
  dimensions: Record<'maps' | 'tiers' | 'classes' | 'nations', AnalysisGroup[]>;
  activity: Record<'days' | 'weekdays' | 'hours', AnalysisGroup[]>;
  economy: Record<'credits_gross' | 'credits_net' | 'xp_bonus', TotalMetric> & { vehicles: AnalysisGroup[] };
  coverage: Record<'map_label' | 'vehicle_tier' | 'vehicle_class' | 'vehicle_nation', number>;
}
export interface PeriodReport {
  key: 'week' | 'month' | 'all_time'; label: string; start_at: number | null; end_at: number;
  summary: Summary; credits_net: TotalMetric; xp_bonus: TotalMetric; vehicles: AnalysisGroup[];
  previous: { start_at: number; end_at: number; summary: Summary; credits_net: TotalMetric } | null;
  comparison: {
    status: 'ready' | 'insufficient_data' | 'partial_data' | 'not_applicable';
    avg_damage_delta: number | null; win_rate_delta_pp: number | null; credits_net_average_delta: number | null;
  };
}
export interface Reports { version: 1; basis: 'received_at'; timezone: 'UTC'; excluded_future: number; periods: PeriodReport[] }
export interface Snapshot {
  protocol: 1; source: 'game' | 'demo'; status: 'ready' | 'empty' | 'account_unavailable';
  request_id: string; selection: Selection;
  vehicles: VehicleEntry[];
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
  analytics?: Analytics;
  reports?: Reports;
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
    && (!('page' in value) || count(value.page))
    && (!('history_query' in value) || text(value.history_query, 64))
    && (!('history_sort' in value) || ['time_desc', 'time_asc', 'damage_desc', 'xp_desc', 'credits_desc'].includes(value.history_sort as string));
}

const vehicleClasses = ['lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG'];
const vehicleNations = ['ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan', 'czech', 'sweden', 'poland', 'italy', 'intunion'];
export const dashboardModules: DashboardModule[] = ['metrics', 'coach', 'vehicle', 'chart', 'goals', 'activity', 'economy', 'reports'];
function vehicleMetadata(value: Record<string, unknown>): boolean {
  return (!('vehicle_tier' in value) || value.vehicle_tier === null || (count(value.vehicle_tier) && value.vehicle_tier >= 1 && value.vehicle_tier <= 11))
    && (!('vehicle_class' in value) || value.vehicle_class === null || vehicleClasses.includes(value.vehicle_class as string))
    && (!('vehicle_nation' in value) || value.vehicle_nation === null || vehicleNations.includes(value.vehicle_nation as string));
}

function coach(value: unknown, window: WindowSize): value is Coach {
  if (!record(value) || value.version !== 1 || !['choose_vehicle', 'empty', 'collecting', 'incomplete', 'mixed_modes', 'identity_ambiguous', 'ready'].includes(value.status as string)
      || !text(value.vehicle) || ('vehicle_label' in value && !text(value.vehicle_label)) || value.window !== window || !count(value.battles)
      || value.required_battles !== window * 2 || !count(value.remaining_battles)
      || value.remaining_battles !== Math.max(0, window * 2 - value.battles)) return false;
  if (!coachExtensions(value, window)) return false;
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
  if (value.status === 'identity_ambiguous') {
    return !!value.vehicle && value.battles > 0 && !r.new_damage_record && !r.new_window_record
      && ['best_damage', 'latest_damage', 'previous_best_damage', 'best_window_avg', 'previous_best_window_avg', 'current_window_avg']
        .every(key => records[key] === null);
  }
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

function coachExtensions(value: Record<string, unknown>, window: number): boolean {
  const blocked = ['choose_vehicle', 'empty', 'incomplete', 'mixed_modes', 'identity_ambiguous'].includes(value.status as string);
  if ('consistency' in value) {
    const c = value.consistency;
    const fields = ['median', 'lower_quartile', 'upper_quartile', 'interquartile_range', 'median_absolute_deviation'];
    if (!record(c) || !['ready', 'insufficient_data', 'not_comparable'].includes(c.status as string)
        || !count(c.samples) || c.samples > window || c.required !== window || !fields.every(key => metric(c[key]))) return false;
    if (c.status === 'ready') {
      if (blocked || c.samples !== window || !fields.every(key => number(c[key]))
          || (c.lower_quartile as number) > (c.median as number) || (c.median as number) > (c.upper_quartile as number)
          || Math.abs((c.upper_quartile as number) - (c.lower_quartile as number) - (c.interquartile_range as number)) > 0.11) return false;
    } else if (!fields.every(key => c[key] === null)) return false;
  }
  if ('observations' in value) {
    if (!array(value.observations, 4) || (blocked && value.observations.length > 0)) return false;
    const kinds = new Set<string>();
    for (const item of value.observations) {
      if (!record(item) || !['damage_average', 'damage_median', 'damage_spread', 'net_credits'].includes(item.kind as string)
          || kinds.has(item.kind as string) || !number(item.current) || !nullableNumber(item.previous) || !nullableNumber(item.delta)
          || !count(item.samples) || item.samples > window || !count(item.previous_samples) || item.previous_samples > window
          || item.window !== window || !['last_windows', 'current_window'].includes(item.scope as string)) return false;
      if (item.kind !== 'net_credits' && (item.current < 0 || (typeof item.previous === 'number' && item.previous < 0))) return false;
      if (item.scope === 'current_window' ? item.previous !== null || item.delta !== null
        : !number(item.previous) || !number(item.delta) || Math.abs(item.current - item.previous - item.delta) > 0.11) return false;
      kinds.add(item.kind as string);
    }
  }
  if ('goal_suggestions' in value) {
    if (!array(value.goal_suggestions, 1) || (blocked && value.goal_suggestions.length > 0)) return false;
    for (const item of value.goal_suggestions) {
      if (!record(item) || !text(item.vehicle) || !item.vehicle || item.vehicle !== value.vehicle || item.window !== window
          || !count(item.target_avg_damage) || item.target_avg_damage < 1 || item.target_avg_damage > 50000
          || !number(item.baseline_avg_damage) || item.baseline_avg_damage < 0 || item.samples !== window
          || item.adjustment_percent !== 5 || item.rounding_step !== 50 || item.basis !== 'recent_window'
          || item.requires_confirmation !== true) return false;
    }
  }
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
          || ('vehicle_label' in item && !text(item.vehicle_label))
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
  if (!selection(p) || !['progress', 'dynamics', 'history', 'summary', 'analytics', 'reports', 'settings'].includes(p.tab as string)
      || !['normal', 'compact'].includes(p.density as string) || !['standard', 'high'].includes(p.contrast as string)) return false;
  if (('theme' in p && !['hangar', 'slate', 'light'].includes(p.theme as string))
      || ('motion' in p && !['system', 'reduced'].includes(p.motion as string))
      || ('modules' in p && (!array(p.modules, dashboardModules.length) || p.modules.length === 0
        || new Set(p.modules).size !== p.modules.length || !p.modules.every(key => dashboardModules.includes(key as DashboardModule))))) return false;
  if (!array(value.goals, 30) || !value.goals.every(g => record(g) && text(g.vehicle) && !!g.vehicle
      && (!('vehicle_label' in g) || text(g.vehicle_label))
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
  for (const key of ['kills', 'xp_base', 'xp_bonus', 'credits_gross', 'credits_net']) {
    // Additive protocol-1 field: older sources do not provide bonus XP.
    if (key === 'xp_bonus' && !(key in fields)) continue;
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
  if (sum > total || !record(c) || !['choose_vehicle', 'insufficient_data', 'incomplete', 'mixed_modes', 'mode_unknown', 'identity_ambiguous', 'ready'].includes(c.status as string)
      || !count(c.minimum_battles) || c.minimum_battles < 10 || !count(c.current_battles) || !count(c.previous_battles)
      || c.current_battles + c.previous_battles > total) return false;
  const averages = ['current_average', 'previous_average', 'current_median', 'previous_median'];
  if (!averages.every(key => metric(c[key])) || !nullableNumber(c.delta_average) || !nullableNumber(c.delta_median)) return false;
  if (c.status === 'identity_ambiguous') return [...averages, 'delta_average', 'delta_median'].every(key => c[key] === null);
  return c.status !== 'ready' || (c.current_battles >= c.minimum_battles && c.previous_battles >= c.minimum_battles
    && [...averages, 'delta_average', 'delta_median'].every(key => number(c[key])));
}

function totalMetric(value: unknown, battles: number, signed = false): value is TotalMetric {
  if (!record(value) || !count(value.samples) || value.samples > battles
      || !(signed ? nullableNumber(value.average) : metric(value.average))
      || !(value.total === null || (number(value.total) && Number.isSafeInteger(value.total) && (signed || value.total >= 0)))
      || (value.samples === 0) !== (value.average === null) || (value.samples === 0) !== (value.total === null)) return false;
  return value.samples === 0 || Math.abs((value.total as number) / value.samples - (value.average as number)) <= 0.051;
}

function analysisGroups(value: unknown, max: number, battles: number): value is AnalysisGroup[] {
  if (!array(value, max)) return false;
  const keys = new Set<string>();
  let total = 0;
  for (const item of value) {
    if (!record(item) || !text(item.key) || !item.key || keys.has(item.key) || !text(item.label) || !item.label
        || ('vehicle_label' in item && !text(item.vehicle_label)) || !summary(item.summary)
        || item.summary.wins + item.summary.losses + item.summary.draws !== item.summary.known_outcomes
        || !totalMetric(item.credits_net, item.summary.battles, true)) return false;
    keys.add(item.key); total += item.summary.battles;
  }
  return total <= battles;
}

function validAnalytics(value: unknown, battles: number): value is Analytics {
  if (!record(value) || value.version !== 1 || value.basis !== 'received_at' || value.timezone !== 'UTC'
      || !record(value.dimensions) || !record(value.activity) || !record(value.economy) || !record(value.coverage)) return false;
  const limits: Record<string, number> = { maps: 24, tiers: 12, classes: 6, nations: 13 };
  for (const key of Object.keys(limits)) if (!analysisGroups(value.dimensions[key], limits[key], battles)) return false;
  if (!analysisGroups(value.activity.days, 90, battles) || !analysisGroups(value.activity.weekdays, 7, battles)
      || !analysisGroups(value.activity.hours, 24, battles)) return false;
  if (!totalMetric(value.economy.credits_gross, battles) || !totalMetric(value.economy.credits_net, battles, true)
      || !totalMetric(value.economy.xp_bonus, battles) || !analysisGroups(value.economy.vehicles, 64, battles)) return false;
  return ['map_label', 'vehicle_tier', 'vehicle_class', 'vehicle_nation']
    .every(key => count(value.coverage && (value.coverage as Record<string, unknown>)[key])
      && ((value.coverage as Record<string, number>)[key] <= battles));
}

function validReports(value: unknown, battles: number): value is Reports {
  if (!record(value) || value.version !== 1 || value.basis !== 'received_at' || value.timezone !== 'UTC'
      || !count(value.excluded_future) || value.excluded_future > battles || !array(value.periods, 3) || value.periods.length !== 3) return false;
  const keys = new Set<string>();
  for (const item of value.periods) {
    if (!record(item) || !['week', 'month', 'all_time'].includes(item.key as string) || keys.has(item.key as string)
        || !text(item.label) || !count(item.end_at) || item.end_at > 253402300800
        || !(item.start_at === null || (count(item.start_at) && item.start_at < item.end_at))
        || !summary(item.summary) || item.summary.battles > battles
        || !totalMetric(item.credits_net, item.summary.battles, true) || !totalMetric(item.xp_bonus, item.summary.battles)
        || !analysisGroups(item.vehicles, 10, item.summary.battles) || !record(item.comparison)) return false;
    keys.add(item.key as string);
    const c = item.comparison;
    const deltas = ['avg_damage_delta', 'win_rate_delta_pp', 'credits_net_average_delta'];
    if (!['ready', 'insufficient_data', 'partial_data', 'not_applicable'].includes(c.status as string)
        || !deltas.every(key => nullableNumber(c[key]))) return false;
    if (item.key === 'all_time') {
      if (item.previous !== null || c.status !== 'not_applicable'
          || !deltas.every(key => c[key] === null) || item.summary.battles + value.excluded_future !== battles) return false;
    } else {
      const p = item.previous;
      if (item.start_at === null || !record(p) || !count(p.start_at) || !count(p.end_at)
          || p.start_at > p.end_at || p.end_at !== item.start_at || !summary(p.summary)
          || p.summary.battles + item.summary.battles > battles || !totalMetric(p.credits_net, p.summary.battles, true)
          || c.status === 'not_applicable') return false;
      if (c.avg_damage_delta !== null && (item.summary.damage_samples !== item.summary.battles
          || p.summary.damage_samples !== p.summary.battles || item.summary.avg_damage === null || p.summary.avg_damage === null
          || Math.abs(item.summary.avg_damage - p.summary.avg_damage - (c.avg_damage_delta as number)) > 0.11)) return false;
      if (c.win_rate_delta_pp !== null && (item.summary.known_outcomes !== item.summary.battles
          || p.summary.known_outcomes !== p.summary.battles || item.summary.win_rate === null || p.summary.win_rate === null
          || Math.abs(item.summary.win_rate - p.summary.win_rate - (c.win_rate_delta_pp as number)) > 0.11)) return false;
      if (c.credits_net_average_delta !== null && (item.credits_net.samples !== item.summary.battles
          || p.credits_net.samples !== p.summary.battles || item.credits_net.average === null || p.credits_net.average === null
          || Math.abs(item.credits_net.average - p.credits_net.average - (c.credits_net_average_delta as number)) > 0.11)) return false;
      if ((item.summary.battles === 0 || p.summary.battles === 0)
          && (c.status !== 'insufficient_data' || !deltas.every(key => c[key] === null))) return false;
    }
  }
  return true;
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
  if (!array(raw.vehicles, 2048) || !raw.vehicles.every(v => record(v) && text(v.name)
      && (!('label' in v) || text(v.label)) && count(v.battles) && vehicleMetadata(v))) return fail();
  const comparison = raw.comparison;
  if (!record(comparison) || ![10, 30, 100].includes(comparison.window as number)
      || !summary(comparison.current) || !(comparison.previous === null || summary(comparison.previous))
      || typeof comparison.enough_current !== 'boolean' || typeof comparison.enough_previous !== 'boolean'
      || !nullableNumber(comparison.damage_delta) || !nullableNumber(comparison.win_rate_delta_pp)) return fail();
  if (!array(raw.series, 60) || !raw.series.every(v => record(v) && count(v.battle) && metric(v.avg_damage) && count(v.known_damage))) return fail();
  if (!array(raw.goals, 30) || !raw.goals.every(v => record(v) && text(v.vehicle)
      && (!('vehicle_label' in v) || text(v.vehicle_label))
      && count(v.target) && count(v.window) && count(v.battles) && count(v.known_damage)
      && metric(v.avg_damage) && ['no_data', 'in_progress', 'insufficient_data', 'identity_ambiguous', 'achieved', 'not_achieved'].includes(v.status as string))) return fail();
  if (!array(raw.history, 12) || !raw.history.every(v => record(v) && count(v.timestamp) && v.timestamp <= 253402300799 && text(v.vehicle)
      && (!('vehicle_label' in v) || text(v.vehicle_label))
      && [null, 'unknown', 'win', 'loss', 'draw'].includes(v.outcome as string | null) && metric(v.damage) && metric(v.xp)
      && ['kills', 'shots', 'direct_hits', 'penetrations', 'xp_base', 'xp_bonus', 'credits_gross', 'assistance_radio', 'assistance_track'].every(key => !(key in v) || v[key] === null || count(v[key]))
      && (!('credits_net' in v) || v.credits_net === null || (number(v.credits_net) && Number.isSafeInteger(v.credits_net)))
      && (!('survived' in v) || v.survived === null || typeof v.survived === 'boolean')
      && (!('map' in v) || v.map === null || text(v.map)) && (!('map_label' in v) || v.map_label === null || text(v.map_label))
      && vehicleMetadata(v))) return fail();
  if (!record(raw.quality) || !['total_records', 'incomplete_records', 'invalid_records', 'conflicts'].every(key => count((raw.quality as Record<string, unknown>)[key]))) return fail();
  // Optional additive protocol-1 extension; older hosts remain readable.
  if ('coach' in raw && (!coach(raw.coach, raw.selection.window)
      || !coachScope(raw.coach, raw.selection, raw.status as Snapshot['status'], raw.vehicles as Snapshot['vehicles'], raw.summary.battles))) return fail();
  if ('insights' in raw && !validInsights(raw.insights, raw.summary,
      raw.status as Snapshot['status'], raw.selection)) return fail();
  if ('pagination' in raw) {
    const p = raw.pagination;
    if (!record(p) || !count(p.page) || p.page_size !== 5 || !count(p.pages) || !count(p.total)
        || (raw.selection.history_query ? p.total > raw.summary.battles : p.total !== raw.summary.battles)
        || p.pages !== Math.max(1, Math.ceil(p.total / 5))
        || p.page >= p.pages || raw.history.length !== Math.min(5, Math.max(0, p.total - p.page * 5))) return fail();
  }
  if ('workspace' in raw && !validWorkspace(raw.workspace)) return fail();
  if ('metrics' in raw && !validMetrics(raw.metrics, raw.summary.battles)) return fail();
  if ('sessions' in raw && !validSessions(raw.sessions, raw.summary.battles)) return fail();
  if ('analytics' in raw && !validAnalytics(raw.analytics, raw.summary.battles)) return fail();
  if ('reports' in raw && !validReports(raw.reports, raw.summary.battles)) return fail();
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
