import { Button } from './Button';
import { useEffect, useRef, useState } from 'react';
import { createBridge } from './bridge';
import { getMode, Goal, GoalDefinition, DashboardModule, Mode, Selection, Snapshot, WindowSize, BattlePoint } from './contracts';
import { SnapshotController, ViewState } from './controller';
import { CoachCard } from './Coach';
import { vehicleLabel } from './vehicleLabel';
import { PanelSection } from './contracts';
import { formatNumber, signed, timeLabel, outcomeLabel } from './format';
import { VehiclePicker } from './VehiclePicker';
import { SettingsView, OperationNotice } from './Workspace';
import { SummaryView } from './SummaryExtras';
import { BattleHistory } from './History';
import { ActivityView, AnalyticsView, EconomyView, FeatureUnavailable } from './Analytics';
import { ReportsView } from './Reports';
import { VehicleCard, VehicleCollection } from './VehicleCards';
import { moduleLabels } from './preferences';
import { bindPanelWheel, GAMEFACE_SCROLL_STEP, handlePanelKey, scrollPanel } from './scroll';
export { formatNumber } from './format';
const SECTIONS: Array<{ id: PanelSection; label: string }> = [
  { id: 'progress', label: 'Прогресс' }, { id: 'dynamics', label: 'Динамика и цели' }, { id: 'history', label: 'История боёв' }, { id: 'summary', label: 'Сводка' },
  { id: 'analytics', label: 'Аналитика' }, { id: 'reports', label: 'Отчёты' }, { id: 'settings', label: 'Настройки' }
];
const PAGE_SIZE = 5;

const goalLabels: Record<Goal['status'], string> = {
  no_data: 'Ожидаем результаты', in_progress: 'Набираем серию', insufficient_data: 'Недостаточно данных',
  identity_ambiguous: 'Техника не определена однозначно',
  achieved: 'Цель достигнута', not_achieved: 'Цель ещё впереди'
};

function SourceBadge({ mode }: { mode: Mode }) {
  return <span className={'source-badge ' + (mode === 'demo' ? 'source-demo' : '')}>
    <span className="status-dot" />{mode === 'demo' ? 'DEMO · вымышленные данные' : mode === 'local' ? 'Локальная история' : 'Данные текущего аккаунта'}
  </span>;
}


function Metric({ label, value, detail, emphasis = false, testId }: {
  label: string; value: string; detail: string; emphasis?: boolean; testId?: string;
}) {
  return <div className={'metric-card' + (emphasis ? ' metric-emphasis' : '')}>
    <span className="eyebrow">{label}</span><strong data-testid={testId} className="metric-value">{value}</strong>
    <span className="metric-detail">{detail}</span>
  </div>;
}

export function Trend({ series, windowSize }: { series: Snapshot['series']; windowSize: WindowSize }) {
  const [selectedBattle, setSelectedBattle] = useState<number | null>(null);
  const known = series.filter(point => point.avg_damage !== null);
  if (known.length === 0) return <div className="chart-empty">
    <strong>{'График появится после ' + windowSize + ' боёв'}</strong>
    <span>Для каждой точки нужен известный урон минимум в 70% боёв окна.</span>
  </div>;
  const values = known.map(point => point.avg_damage as number);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(100, max - min);
  const lower = Math.max(0, min - range * 0.15);
  const upper = max + range * 0.15;
  const x = (index: number) => 8 + index * (584 / Math.max(1, series.length - 1));
  const y = (value: number) => 138 - (value - lower) * (122 / (upper - lower));
  let paths: string[] = [];
  let current = '';
  series.forEach((point, index) => {
    if (point.avg_damage === null) { if (current) paths.push(current); current = ''; return; }
    current += (current ? ' L ' : 'M ') + x(index).toFixed(2) + ' ' + y(point.avg_damage).toFixed(2);
  });
  if (current) paths.push(current);
  const lastIndex = series.reduce((last, point, index) => point.avg_damage === null ? last : index, 0);
  const activeIndex = series.findIndex(point => point.battle === selectedBattle && point.avg_damage !== null);
  const selectedIndex = activeIndex === -1 ? lastIndex : activeIndex;
  const active = series[selectedIndex];
  const description = (point: Snapshot['series'][number]) => 'Бой ' + point.battle + ' · средний урон ' + formatNumber(point.avg_damage, 1) + ' · известно ' + point.known_damage + '/' + windowSize;
  return <div className="chart-wrap" aria-label={'Скользящий средний урон, окно ' + windowSize + ' боёв'}>
    <div className="chart-range"><span>{formatNumber(max)}</span><span>СРЕДНИЙ УРОН</span></div>
    <svg className="trend-svg" viewBox="0 0 600 150" preserveAspectRatio="none" role="group" aria-label="Динамика среднего урона">
      {[22, 79, 137].map(row => <path key={row} d={'M 0 ' + row + ' L 600 ' + row} stroke="#344139" strokeWidth="1" fill="none" />)}
      {paths.map((path, index) => <path key={index} d={path} stroke="#dfb875" strokeWidth="2.5" fill="none" />)}
      {series.map((point, index) => point.avg_damage === null ? null : <circle key={point.battle} className="trend-point" data-trend-index={index}
        cx={x(index)} cy={y(point.avg_damage)} r={index === selectedIndex ? 5 : 3} fill="#dfb875" role="button" tabIndex={index === selectedIndex ? 0 : -1}
        aria-label={description(point)} aria-pressed={index === selectedIndex} onClick={() => setSelectedBattle(point.battle)} onFocus={() => setSelectedBattle(point.battle)}
        onMouseEnter={() => setSelectedBattle(point.battle)} onKeyDown={event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedBattle(point.battle); }
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          const indices = series.map((item, at) => item.avg_damage === null ? -1 : at).filter(at => at >= 0);
          const position = indices.indexOf(index);
          const next = indices[(position + (event.key === 'ArrowRight' ? 1 : indices.length - 1)) % indices.length];
          event.currentTarget.ownerSVGElement?.querySelector<SVGElement>('[data-trend-index="' + next + '"]')?.focus();
        }}><title>{description(point)}</title></circle>)}
    </svg>
    <div className="chart-axis"><span>{'Бой ' + series[0].battle}</span><span>{formatNumber(min) + ' — ' + formatNumber(max) + ' урона'}</span><span>{'Бой ' + series[series.length - 1].battle}</span></div>
    <p className="trend-selection" aria-live="polite" data-testid="trend-detail">{description(active)}</p>
  </div>;
}

export function DamageBars({ points }: { points: BattlePoint[] }) {
  const [selected, setSelected] = useState<number | null>(null);
  if (!points.length) return <div className="chart-empty"><strong>Нет записанных боёв</strong></div>;
  const active = points.find(point => point.battle === selected) || points[points.length - 1];
  const max = Math.max(1, ...points.map(point => point.damage === null ? 0 : point.damage));
  const known = points.some(point => point.damage !== null);
  const description = (point: BattlePoint) => 'Бой ' + point.battle + ' · ' +
    (point.damage === null ? 'урон неизвестен' : formatNumber(point.damage) + ' урона') + ' · ' + outcomeLabel[point.outcome];
  return <div className="damage-chart">
    <div className="chart-range"><span>{known ? formatNumber(Math.max(...points.map(point => point.damage || 0))) : '—'}</span><span>УРОН ЗА БОЙ</span></div>
    <div className="damage-bars" role="group" aria-label="Урон отдельных боёв">
      {points.map(point => <Button key={point.battle} type="button" className={'damage-column damage-' + point.outcome + (active.battle === point.battle ? ' selected' : '')}
        aria-label={description(point)} title={description(point)} aria-pressed={active.battle === point.battle} onClick={() => setSelected(point.battle)} onFocus={() => setSelected(point.battle)} onKeyDown={event => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          const buttons = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('button'));
          buttons[(buttons.indexOf(event.currentTarget) + (event.key === 'ArrowRight' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
        }}>
        <span className="damage-bar-area">
          {point.damage === null ? <span className="damage-unknown">—</span> :
            <span className="damage-bar" style={{ height: Math.max(2, Math.round(point.damage / max * 126)) + 'px' }} />}
        </span>
        <span className="damage-bar-number">{points.length <= 12 ? String(point.battle) : ''}</span>
      </Button>)}
    </div>
    <div className="chart-axis"><span>{'Бой ' + points[0].battle}</span><span>{'Бой ' + points[points.length - 1].battle}</span></div>
    <p className="damage-detail" data-testid="damage-detail">{description(active)}</p>
    <p className="trend-note">Цвет столбца — исход боя. Ноль показан короткой чертой, пропуск — тире. Нажмите на столбец для подробностей.</p>
  </div>;
}

function DamagePanel({ snapshot }: { snapshot: Snapshot }) {
  const [rolling, setRolling] = useState(false);
  const points = snapshot.insights?.recent_damage;
  return <section className="trend-card">
    <div className="section-heading"><h2>Динамика урона</h2><span className="subtle-tag">{rolling || !points ? 'ОКНО ' + snapshot.selection.window : 'ДО 24 БОЁВ'}</span></div>
    {points && <div className="insight-switch" role="group" aria-label="Вид графика">
      <Button type="button" className={!rolling ? 'active' : ''} aria-pressed={!rolling} onClick={() => setRolling(false)}>Урон за бой</Button>
      <Button type="button" className={rolling ? 'active' : ''} aria-pressed={rolling} onClick={() => setRolling(true)}>Скользящее среднее</Button>
    </div>}
    {!rolling && points ? <DamageBars points={points} /> : <><Trend series={snapshot.series} windowSize={snapshot.selection.window} />
      {snapshot.coach ? <p className="trend-note">Скользящее среднее: для точки нужен известный урон минимум в 70% боёв окна.</p> : <Comparison snapshot={snapshot} />}</>}
  </section>;
}

function PendingNotice({ snapshot }: { snapshot: Snapshot }) {
  const pending = snapshot.insights?.pending_count;
  if (pending === null || pending === undefined) return null;
  return <div className={'pending-note' + (pending > 0 ? ' pending-warning' : '')} role="status" data-testid="pending-note">
    <span>{'Незакрытые ожидания аккаунта: ' + pending + '.'}</span>
    {pending > 0 && <span>Часть результатов может быть недоступна или неполна; статистика отражает только сохранённые записи.</span>}
  </div>;
}

export function InsightsView({ snapshot }: { snapshot: Snapshot }) {
  const [group, setGroup] = useState<'totals' | 'days' | 'tanks'>('totals');
  const [page, setPage] = useState(0);
  const data = snapshot.insights;
  if (!data) return <div className="chart-empty">Дополнительная сводка недоступна в этой версии источника.</div>;
  const totals = snapshot.summary;
  const rows = group === 'totals' ? [] : data[group];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const streak = data.streak.outcome === null ? '—' :
    data.streak.length + ' · ' + outcomeLabel[data.streak.outcome];
  return <section className="insights-section">
    {group === 'totals' && <div className="insight-cards">
      <div className="insight-card"><span>ИСХОДЫ БОЁВ</span>
        <strong className="outcome-tally" data-testid="outcome-tally">{totals.wins + ' П / ' + totals.losses + ' Пор / ' + totals.draws + ' Н'}</strong>
        <p>{'Победы / поражения / ничьи. Неизвестно: ' + (totals.battles - totals.known_outcomes)}</p></div>
      <div className="insight-card"><span>ПОСЛЕДНЯЯ СЕРИЯ</span><strong data-testid="streak-value">{streak}</strong><p>Только последовательность сохранённых боёв.</p></div>
      <div className="insight-card"><span>СРЕДНЯЯ ПОМОЩЬ</span><strong>{formatNumber(data.assistance_radio.average) + ' / ' + formatNumber(data.assistance_track.average)}</strong>
        <p>{'Разведка / гусеница. Известно: ' + data.assistance_radio.samples + ' / ' + data.assistance_track.samples + ' боёв.'}</p></div>
    </div>}
    <div className="section-heading"><h2>Сводка по выборке</h2><span className="subtle-tag">ПО СОХРАНЁННЫМ ДАННЫМ</span></div>
    <div className="insight-switch" role="group" aria-label="Группировка сводки">
      <Button type="button" className={group === 'totals' ? 'active' : ''} aria-pressed={group === 'totals'} onClick={() => { setGroup('totals'); setPage(0); }}>Итоги</Button>
      <Button type="button" className={group === 'days' ? 'active' : ''} aria-pressed={group === 'days'} onClick={() => { setGroup('days'); setPage(0); }}>По дням</Button>
      <Button type="button" className={group === 'tanks' ? 'active' : ''} aria-pressed={group === 'tanks'} onClick={() => { setGroup('tanks'); setPage(0); }}>По технике</Button>
    </div>
    {group !== 'totals' && <><div className="history-table insight-table" role="table" aria-label="Сводка результатов">
      <div className="history-row history-head" role="row"><span role="columnheader" className="insight-label">{group === 'days' ? 'Дата получения' : 'Техника'}</span><span role="columnheader">Бои</span><span role="columnheader">Победы</span><span role="columnheader">Поражения</span><span role="columnheader">Ничьи</span><span role="columnheader">Побед, %</span><span role="columnheader">Ср. урон</span></div>
      {rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(row => <div key={row.label} className="history-row" role="row">
        <span role="cell" className="insight-label">{group === 'days' ? row.label : vehicleLabel(row.label, row.vehicle_label)}</span>
        <span role="cell">{row.summary.battles}</span><span role="cell" className="positive">{row.summary.wins}</span><span role="cell" className="negative">{row.summary.losses}</span><span role="cell">{row.summary.draws}</span>
        <span role="cell">{formatNumber(row.summary.win_rate, 1)}</span><span role="cell">{formatNumber(row.summary.avg_damage)}</span>
      </div>)}
    </div>
    <div className="page-controls"><Button type="button" aria-label="Предыдущая страница сводки" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</Button>
      <span>{String(current + 1) + ' / ' + pages}</span><Button type="button" aria-label="Следующая страница сводки" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</Button></div></>}
    <p className="trend-note">{group === 'days' ? 'До 14 последних дней по местному времени получения результатов, не начала боя.' : group === 'tanks' ? 'До 20 машин с наибольшим числом записанных боёв.' : 'Итоги относятся к выбранной технике и сохранённой истории.'} Процент побед — среди известных исходов, средний урон — среди известных значений.</p>
  </section>;
}

function GoalCard({ goals, selected, editable = false }: { goals: Goal[]; selected: string; editable?: boolean }) {
  const [index, setIndex] = useState(0);
  const available = selected ? goals.filter(item => item.vehicle === selected) : goals;
  const current = Math.min(index, Math.max(0, available.length - 1));
  const goal = available[current];
  if (!goal) return <section className="goal-card">
    <div className="section-heading"><h2>Личная цель</h2><span className="subtle-tag">ПО ТЕХНИКЕ</span></div>
    <div className="goal-empty"><span className="target-symbol">◎</span><strong>Цель пока не задана</strong><p>{editable ? 'Откройте «Настройки» → «Цели» и задайте средний урон для своей машины.' : 'Добавьте цель по среднему урону в локальный файл goals.json.'}</p></div>
  </section>;
  const percent = Math.max(0, Math.min(100, (goal.avg_damage || 0) * 100 / goal.target));
  const achieved = goal.status === 'achieved';
  const ambiguous = goal.status === 'identity_ambiguous';
  return <section className="goal-card">
    <div className="section-heading"><h2>Личная цель</h2><span className="subtle-tag">{goal.window} БОЁВ</span></div>
    {available.length > 1 && <div className="page-controls goal-navigation"><Button type="button" aria-label="Предыдущая цель" disabled={current === 0} onClick={() => setIndex(current - 1)}>Назад</Button><span>{String(current + 1) + ' / ' + available.length}</span><Button type="button" aria-label="Следующая цель" disabled={current + 1 >= available.length} onClick={() => setIndex(current + 1)}>Далее</Button></div>}
    <div className="goal-vehicle"><span className="target-symbol">◎</span><strong>{vehicleLabel(goal.vehicle, goal.vehicle_label)}</strong></div>
    <div className="goal-values"><strong>{formatNumber(goal.avg_damage)}</strong><span>{'/ ' + formatNumber(goal.target)}</span></div>
    <span className="small muted">средний урон за серию</span>
    {!ambiguous && <div className="progress-track" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100} aria-label="Прогресс среднего урона">
      <div className={'progress-fill' + (achieved ? ' progress-done' : '')} style={{ width: percent + '%' }} />
    </div>}
    <div className="goal-status"><span className={achieved ? 'positive' : 'muted'}>{goalLabels[goal.status]}</span><span>{goal.battles + '/' + goal.window}</span></div>
    <span className="tiny muted">Урон известен в {goal.known_damage} боях. {ambiguous ? 'Старая история сохранена. Для цели выберите машину с подтверждённым идентификатором.' : 'Для достижения нужен известный урон во всей серии.'}</span>
  </section>;
}

function Comparison({ snapshot }: { snapshot: Snapshot }) {
  if (snapshot.coach?.status === 'identity_ambiguous' || snapshot.sessions?.comparison.status === 'identity_ambiguous') {
    return <div className="comparison-note" role="status"><span className="note-marker">i</span>
      <span>Название связано с разной техникой. Для сравнения выберите машину с подтверждённым идентификатором. Старая история сохранена.</span></div>;
  }
  const comparison = snapshot.comparison;
  if (!comparison.enough_previous) {
    const remaining = Math.max(0, comparison.window * 2 - snapshot.summary.battles);
    return <div className="comparison-note"><span className="note-marker">i</span>
      <span>Для сравнения двух периодов нужно ещё <strong>{remaining} боёв</strong> в этой выборке.</span></div>;
  }
  return <div className="comparison-row">
    <span className="muted">К предыдущим {comparison.window} боям</span>
    <span><span className="comparison-label">Урон</span><strong className={comparison.damage_delta !== null && comparison.damage_delta >= 0 ? 'positive' : 'negative'}>{signed(comparison.damage_delta)}</strong></span>
    <span><span className="comparison-label">Победы</span><strong className={comparison.win_rate_delta_pp !== null && comparison.win_rate_delta_pp >= 0 ? 'positive' : 'negative'}>{signed(comparison.win_rate_delta_pp, ' п. п.')}</strong></span>
  </div>;
}


function ProgressDashboard({ snapshot, onSelectVehicle, onSaveGoal, busy }: { snapshot: Snapshot; onSelectVehicle?: (vehicle: string) => void; onSaveGoal?: (goal: GoalDefinition) => void; busy: boolean }) {
  const modules: DashboardModule[] = snapshot.workspace?.preferences.modules || ['metrics', 'coach'];
  const panels: DashboardModule[] = modules.filter(item => item !== 'metrics');
  const [active, setActive] = useState<DashboardModule>(panels[0] || 'metrics');
  const current = panels.includes(active) ? active : panels[0];
  const summary = snapshot.summary;
  const vehicle = snapshot.vehicles.find(item => item.name === (snapshot.selection.vehicle || snapshot.coach?.vehicle));
  return <section className="progress-dashboard" aria-label="Личная панель">
    {modules.includes('metrics') && <div className="metrics-row">
      <Metric label="БОЁВ В ВЫБОРКЕ" value={formatNumber(summary.battles)} detail="По выбранной технике" testId="battle-count" />
      <Metric label="ПОБЕДЫ" value={summary.win_rate === null ? '—' : formatNumber(summary.win_rate, 1) + '%'} detail={summary.wins + ' побед · ' + summary.losses + ' пораж. · ' + summary.draws + ' ничьих'} testId="win-rate" />
      <Metric label="СРЕДНИЙ УРОН" value={formatNumber(summary.avg_damage)} detail={'Известен в ' + summary.damage_samples + ' из ' + summary.battles + ' боёв'} emphasis testId="average-damage" />
    </div>}
    {panels.length > 1 && <div className="dashboard-module-tabs insight-switch" role="group" aria-label="Модули личной панели">{panels.map(item => <Button key={item} type="button" aria-pressed={current === item} className={current === item ? 'active' : ''} onClick={() => setActive(item)}>{moduleLabels[item]}</Button>)}</div>}
    {current && <div className="dashboard-panel" key={current}>
      {current === 'coach' ? snapshot.coach ? <CoachCard coach={snapshot.coach} latestVehicle={snapshot.history[0]?.vehicle} latestVehicleLabel={snapshot.history[0]?.vehicle_label} onSelectVehicle={onSelectVehicle} onSaveGoal={onSaveGoal} busy={busy} /> : <FeatureUnavailable name="Разбор прогресса" />
        : current === 'vehicle' ? vehicle ? <VehicleCard vehicle={vehicle} selected /> : <VehicleCollection snapshot={snapshot} onSelect={onSelectVehicle} />
          : current === 'chart' ? <DamagePanel snapshot={snapshot} />
            : current === 'goals' ? <GoalCard goals={snapshot.goals} selected={snapshot.selection.vehicle} editable={!!snapshot.workspace?.can_edit} />
              : current === 'activity' ? <ActivityView snapshot={snapshot} />
                : current === 'economy' ? <EconomyView snapshot={snapshot} compact /> : <ReportsView snapshot={snapshot} compact />}
    </div>}
  </section>;
}

export function SnapshotView({ snapshot, onSelectVehicle, onPage, onHistoryFilter, onSaveGoal, section = 'all', busy = false }: {
  snapshot: Snapshot; onSelectVehicle?: (vehicle: string) => void; onPage?: (page: number) => void; section?: PanelSection | 'all'; busy?: boolean;
  onHistoryFilter?: (filter: Pick<Selection, 'history_query' | 'history_sort'>) => void; onSaveGoal?: (goal: GoalDefinition) => void;
}) {
  if (snapshot.status === 'account_unavailable') return <div className="empty-state" role="status"><span className="large-symbol">◎</span><h2>Аккаунт ещё не определён</h2><p>Данные появятся после входа в ангар. История других аккаунтов здесь не отображается.</p></div>;
  if (snapshot.status === 'empty') return <div className="empty-state" role="status"><span className="large-symbol">＋</span><h2>В этой выборке ещё нет боёв</h2><p>Завершите бой или выберите другую технику. История обновляется по полученным результатам.</p></div>;
  const quality = snapshot.quality;
  return <>
    {(section === 'all' || section === 'progress') && <ProgressDashboard snapshot={snapshot} onSelectVehicle={onSelectVehicle} onSaveGoal={onSaveGoal} busy={busy} />}
    {(section === 'all' || section === 'dynamics') && <div className="analysis-row">
      <DamagePanel snapshot={snapshot} />
      <GoalCard goals={snapshot.goals} selected={snapshot.selection.vehicle} editable={!!snapshot.workspace?.can_edit} />
    </div>}
    {section === 'summary' && <SummaryView snapshot={snapshot}><InsightsView snapshot={snapshot} /></SummaryView>}
    {section === 'analytics' && <AnalyticsView snapshot={snapshot} onSelectVehicle={onSelectVehicle} />}
    {section === 'reports' && <ReportsView snapshot={snapshot} />}
    {(section === 'all' || section === 'history') && <><BattleHistory snapshot={snapshot} onPage={onPage} onFilter={onHistoryFilter} busy={busy} />
    <div className="quality-line"><span className="quality-icon">◈</span><span>
      {quality.incomplete_records === 0 ? 'Основные показатели всех боёв известны.' : 'Неполных результатов: ' + quality.incomplete_records + '. Пропуски не считаются нулём.'}
      {quality.invalid_records > 0 ? ' Отклонённых записей: ' + quality.invalid_records + '.' : ''}
      {quality.conflicts > 0 ? ' Конфликтов: ' + quality.conflicts + '.' : ''}
    </span></div></>}
  </>;
}

export default function App() {
  const mode = getMode(window.location.search);
  const [state, setState] = useState<ViewState>({ phase: 'connecting', snapshot: null, selection: { vehicle: '', window: 10 }, message: '' });
  const [generation, setGeneration] = useState(0);
  const [section, setSection] = useState<PanelSection>('progress');
  const control = useRef<SnapshotController | null>(null);
  const vehicles = useRef<Snapshot['vehicles']>([]);
  const panelContent = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    vehicles.current = [];
    let restored = false;
    const instance = new SnapshotController(createBridge(), next => {
      if (next.snapshot) vehicles.current = next.snapshot.vehicles;
      else if (next.phase === 'error') vehicles.current = [];
      if (!restored && next.snapshot?.workspace) { restored = true; setSection(next.snapshot.workspace.preferences.tab); }
      setState(next);
    });
    control.current = instance;
    setState(instance.state);
    instance.start();
    return () => { instance.dispose(); control.current = null; };
  }, [generation]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && state.phase !== 'closed') { event.preventDefault(); control.current?.close(); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [state.phase]);
  useEffect(() => {
    if (panelContent.current) return bindPanelWheel(panelContent.current, mode);
  }, [mode, generation, state.phase === 'closed']);
  const choose = (selection: Selection) => control.current?.request({ ...selection, page: 0 });
  const busy = state.phase === 'connecting' || state.phase === 'loading';
  const inactive = state.phase === 'connecting' || state.phase === 'closed';
  if (state.phase === 'closed') return <main className="page"><div className="closed-panel"><span className="brand-mark">TS</span><h1>Панель закрыта</h1>
    {mode !== 'gameface' && <Button className="primary-button" type="button" onClick={() => { vehicles.current = []; setGeneration(generation + 1); }}>Открыть снова</Button>}</div></main>;
  const preferences = state.snapshot?.workspace?.preferences;
  const theme = preferences?.theme || 'hangar';
  return <main className={'page theme-' + theme}><div className={'panel theme-' + theme + (preferences?.density === 'compact' ? ' density-compact' : '') + (preferences?.contrast === 'high' ? ' contrast-high' : '') + (preferences?.motion === 'reduced' ? ' motion-reduced' : '')} aria-busy={busy}>
    <header className="panel-header"><div className="brand"><span className="brand-mark">TS</span><div><h1>TankSession<span className="brand-sub">ANALYTICS</span></h1><p>История боёв и личный прогресс</p></div></div>
      <div className="header-actions"><SourceBadge mode={mode} /><Button type="button" className="icon-button refresh" aria-label="Обновить статистику" disabled={inactive || busy} onClick={() => control.current?.request()}>Обновить</Button>
        <Button type="button" className="icon-button close" aria-label="Закрыть панель" onClick={() => control.current?.close()}>×</Button></div></header>
    <div className="panel-content" id="panel-content" ref={panelContent} tabIndex={0} role="region" aria-label="Содержимое статистики" onKeyDown={event => {
      if (event.target !== event.currentTarget) return;
      if (handlePanelKey(event.currentTarget, event.key)) event.preventDefault();
    }}><div className="toolbar"><VehiclePicker vehicles={vehicles.current} selected={state.selection.vehicle} disabled={inactive || busy} onSelect={vehicle => choose({ ...state.selection, vehicle })} />
      <div className="period-control"><span className="field-label">ПЕРИОД СРАВНЕНИЯ</span><div className="period-buttons" role="group" aria-label="Размер периода">
        {([10, 30, 100] as WindowSize[]).map(size => <Button key={size} type="button" aria-label={size + ' боёв'} aria-pressed={state.selection.window === size} disabled={inactive || busy}
          className={state.selection.window === size ? 'active' : ''} onClick={() => choose({ ...state.selection, window: size })}>{size + ' боёв'}</Button>)}
      </div></div><span className="local-note"><span className="status-dot" />Данные на вашем компьютере</span></div>
      <div className="section-tabs" role="group" aria-label="Разделы статистики">
        {SECTIONS.map(item => <Button type="button" key={item.id} aria-pressed={section === item.id} className={section === item.id ? 'active' : ''} disabled={inactive || busy} onClick={() => {
          setSection(item.id);
          if (item.id !== 'history' && state.selection.page) control.current?.request({ ...state.selection, page: 0 });
        }}>{item.label}</Button>)}
      </div>
      {state.snapshot && (state.phase === 'ready' || state.phase === 'loading') ? <><PendingNotice snapshot={state.snapshot} />
        <OperationNotice snapshot={state.snapshot} />
        <div className="screen-content" key={section}>{section === 'settings' ? <SettingsView snapshot={state.snapshot} busy={busy} onCommand={command => control.current?.command(command)} /> :
          <SnapshotView snapshot={state.snapshot} section={section} busy={busy} onPage={page => control.current?.request({ ...state.selection, page })}
            onHistoryFilter={filter => control.current?.request({ ...state.selection, ...filter, page: 0 })}
            onSaveGoal={state.snapshot.workspace?.can_edit ? goal => control.current?.command({ action: 'save_goal', goal }) : undefined}
            onSelectVehicle={vehicle => choose({ ...state.selection, vehicle })} />}</div>
        {busy && <p className="command-progress" role="status">Сохраняем изменения…</p>}
      </> : state.phase === 'error' ? <div className="empty-state error-state" role="alert">
        <span className="large-symbol">!</span><h2>Данные сейчас недоступны</h2><p>{state.message}</p><Button className="primary-button" type="button" onClick={() => setGeneration(generation + 1)}>Повторить подключение</Button>
      </div> : <div className="empty-state loading-state" role="status"><span className="loading-bar" /><h2>{state.phase === 'connecting' ? 'Подключаем панель' : 'Обновляем статистику'}</h2><p>Показатели появятся после получения данных.</p></div>}
    </div>
    <footer className="panel-footer"><span>{mode === 'demo' ? 'Демонстрация интерфейса · данные вымышлены' : 'Только собственные завершённые бои'}</span>
      {mode === 'gameface' && <div className="panel-scroll-buttons" role="group" aria-label="Прокрутка панели">
        <Button type="button" aria-label="Прокрутить вверх" aria-controls="panel-content" title="Прокрутить вверх" onClick={() => { if (panelContent.current) scrollPanel(panelContent.current, -GAMEFACE_SCROLL_STEP * 2); }}>Вверх</Button>
        <Button type="button" aria-label="Прокрутить вниз" aria-controls="panel-content" title="Прокрутить вниз" onClick={() => { if (panelContent.current) scrollPanel(panelContent.current, GAMEFACE_SCROLL_STEP * 2); }}>Вниз</Button>
      </div>}
      <span>{state.snapshot ? 'Обновлено ' + timeLabel(state.snapshot.updated_at) : 'TankSession Analytics'}</span></footer>
  </div></main>;
}
