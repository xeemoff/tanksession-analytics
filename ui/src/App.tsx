import { useEffect, useRef, useState } from 'react';
import { createBridge } from './bridge';
import { getMode, Goal, Mode, Selection, Snapshot, WindowSize, BattlePoint } from './contracts';
import { SnapshotController, ViewState } from './controller';
import { CoachCard } from './Coach';
import { vehicleLabel } from './vehicleLabel';
type PanelSection = 'progress' | 'trend' | 'history' | 'summary';
const SECTIONS: Array<{ id: PanelSection; label: string }> = [
  { id: 'progress', label: 'Прогресс' }, { id: 'trend', label: 'Динамика и цели' }, { id: 'history', label: 'История боёв' }, { id: 'summary', label: 'Сводка' }
];
const PAGE_SIZE = 5;

export function formatNumber(value: number | null, digits = 0): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const fixed = value.toFixed(digits).split('.');
  return fixed[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (fixed.length > 1 ? ',' + fixed[1] : '');
}
function signed(value: number | null, suffix = ''): string {
  if (value === null) return '—';
  return (value > 0 ? '+' : '') + formatNumber(value, 1) + suffix;
}
function timeLabel(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const pad = (value: number) => value < 10 ? '0' + value : String(value);
  return pad(date.getDate()) + '.' + pad(date.getMonth() + 1) + ' · ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
}
const outcomeLabel: Record<string, string> = { win: 'Победа', loss: 'Поражение', draw: 'Ничья', unknown: 'Неизвестно' };
const goalLabels: Record<Goal['status'], string> = {
  no_data: 'Ожидаем результаты', in_progress: 'Набираем серию', insufficient_data: 'Недостаточно данных',
  achieved: 'Цель достигнута', not_achieved: 'Цель ещё впереди'
};

function SourceBadge({ mode }: { mode: Mode }) {
  return <span className={'source-badge ' + (mode === 'demo' ? 'source-demo' : '')}>
    <span className="status-dot" />{mode === 'demo' ? 'DEMO · вымышленные данные' : mode === 'local' ? 'Локальная история' : 'Данные текущего аккаунта'}
  </span>;
}

function VehiclePicker({ vehicles, selected, disabled, onSelect }: {
  vehicles: Snapshot['vehicles']; selected: string; disabled: boolean; onSelect: (vehicle: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(vehicles.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', outside);
    return () => document.removeEventListener('mousedown', outside);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  const choose = (name: string) => { setOpen(false); onSelect(name); };
  return <div className="vehicle-picker" ref={wrap}>
    <span className="field-label">ТЕХНИКА</span>
    <button className="picker-trigger" type="button" aria-haspopup="listbox" aria-expanded={open}
      aria-label="Выбрать танк" disabled={disabled} onClick={() => { setPage(0); setOpen(!open); }}>
      <span className="picker-label">{selected ? vehicleLabel(selected) : 'Вся техника'}</span><span className="chevron">v</span>
    </button>
    {open && <div className="picker-menu" role="listbox" aria-label="Техника">
      <button type="button" role="option" aria-selected={!selected} onClick={() => choose('')}>Вся техника</button>
      {vehicles.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(vehicle => <button type="button" role="option" aria-selected={selected === vehicle.name}
        key={vehicle.name} title={vehicle.name} onClick={() => choose(vehicle.name)}><span className="picker-label">{vehicleLabel(vehicle.name)}</span><span className="muted">{vehicle.battles}</span></button>)}
      {pages > 1 && <div className="page-controls picker-pages">
        <button type="button" aria-label="Предыдущая страница техники" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</button>
        <span>{String(current + 1) + ' / ' + pages}</span>
        <button type="button" aria-label="Следующая страница техники" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</button>
      </div>}
    </div>}
  </div>;
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
  return <div className="chart-wrap" aria-label={'Скользящий средний урон, окно ' + windowSize + ' боёв'}>
    <div className="chart-range"><span>{formatNumber(max)}</span><span>СРЕДНИЙ УРОН</span></div>
    <svg className="trend-svg" viewBox="0 0 600 150" preserveAspectRatio="none" role="img" aria-label="Динамика среднего урона">
      {[22, 79, 137].map(row => <path key={row} d={'M 0 ' + row + ' L 600 ' + row} stroke="#344139" strokeWidth="1" fill="none" />)}
      {paths.map((path, index) => <path key={index} d={path} stroke="#dfb875" strokeWidth="2.5" fill="none" />)}
      {series.map((point, index) => point.avg_damage !== null && index !== lastIndex
        && (index === 0 || series[index - 1].avg_damage === null)
        && (index === series.length - 1 || series[index + 1].avg_damage === null)
        ? <circle key={'isolated-' + index} cx={x(index)} cy={y(point.avg_damage)} r="3" fill="#dfb875" /> : null)}
      <circle cx={x(lastIndex)} cy={y(series[lastIndex].avg_damage as number)} r="4" fill="#dfb875" />
    </svg>
    <div className="chart-axis"><span>{'Бой ' + series[0].battle}</span><span>{formatNumber(min) + ' — ' + formatNumber(max) + ' урона'}</span><span>{'Бой ' + series[series.length - 1].battle}</span></div>
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
      {points.map(point => <button key={point.battle} type="button" className={'damage-column damage-' + point.outcome + (active.battle === point.battle ? ' selected' : '')}
        aria-label={description(point)} aria-pressed={active.battle === point.battle} onClick={() => setSelected(point.battle)}>
        <span className="damage-bar-area">
          {point.damage === null ? <span className="damage-unknown">—</span> :
            <span className="damage-bar" style={{ height: Math.max(2, Math.round(point.damage / max * 126)) + 'px' }} />}
        </span>
        <span className="damage-bar-number">{points.length <= 12 ? String(point.battle) : ''}</span>
      </button>)}
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
      <button type="button" className={!rolling ? 'active' : ''} aria-pressed={!rolling} onClick={() => setRolling(false)}>Урон за бой</button>
      <button type="button" className={rolling ? 'active' : ''} aria-pressed={rolling} onClick={() => setRolling(true)}>Скользящее среднее</button>
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

function InsightsView({ snapshot }: { snapshot: Snapshot }) {
  const [group, setGroup] = useState<'days' | 'tanks'>('days');
  const [page, setPage] = useState(0);
  const data = snapshot.insights;
  if (!data) return <div className="chart-empty">Дополнительная сводка недоступна в этой версии источника.</div>;
  const totals = snapshot.summary;
  const rows = data[group];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const streak = data.streak.outcome === null ? '—' :
    data.streak.length + ' · ' + outcomeLabel[data.streak.outcome];
  return <section className="insights-section">
    <div className="insight-cards">
      <div className="insight-card"><span>ИСХОДЫ БОЁВ</span>
        <strong className="outcome-tally" data-testid="outcome-tally">{totals.wins + ' П / ' + totals.losses + ' Пор / ' + totals.draws + ' Н'}</strong>
        <p>{'Победы / поражения / ничьи. Неизвестно: ' + (totals.battles - totals.known_outcomes)}</p></div>
      <div className="insight-card"><span>ПОСЛЕДНЯЯ СЕРИЯ</span><strong data-testid="streak-value">{streak}</strong><p>Только последовательность сохранённых боёв.</p></div>
      <div className="insight-card"><span>СРЕДНЯЯ ПОМОЩЬ</span><strong>{formatNumber(data.assistance_radio.average) + ' / ' + formatNumber(data.assistance_track.average)}</strong>
        <p>{'Разведка / гусеница. Известно: ' + data.assistance_radio.samples + ' / ' + data.assistance_track.samples + ' боёв.'}</p></div>
    </div>
    <div className="section-heading"><h2>Сводка по выборке</h2><span className="subtle-tag">ПО СОХРАНЁННЫМ ДАННЫМ</span></div>
    <div className="insight-switch" role="group" aria-label="Группировка сводки">
      <button type="button" className={group === 'days' ? 'active' : ''} aria-pressed={group === 'days'} onClick={() => { setGroup('days'); setPage(0); }}>По дням</button>
      <button type="button" className={group === 'tanks' ? 'active' : ''} aria-pressed={group === 'tanks'} onClick={() => { setGroup('tanks'); setPage(0); }}>По технике</button>
    </div>
    <div className="history-table insight-table" role="table" aria-label="Сводка результатов">
      <div className="history-row history-head" role="row"><span role="columnheader" className="insight-label">{group === 'days' ? 'Дата получения' : 'Техника'}</span><span role="columnheader">Бои</span><span role="columnheader">Победы</span><span role="columnheader">Поражения</span><span role="columnheader">Ничьи</span><span role="columnheader">Побед, %</span><span role="columnheader">Ср. урон</span></div>
      {rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(row => <div key={row.label} className="history-row" role="row">
        <span role="cell" className="insight-label">{group === 'days' ? row.label : vehicleLabel(row.label)}</span>
        <span role="cell">{row.summary.battles}</span><span role="cell" className="positive">{row.summary.wins}</span><span role="cell" className="negative">{row.summary.losses}</span><span role="cell">{row.summary.draws}</span>
        <span role="cell">{formatNumber(row.summary.win_rate, 1)}</span><span role="cell">{formatNumber(row.summary.avg_damage)}</span>
      </div>)}
    </div>
    <div className="page-controls"><button type="button" aria-label="Предыдущая страница сводки" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</button>
      <span>{String(current + 1) + ' / ' + pages}</span><button type="button" aria-label="Следующая страница сводки" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</button></div>
    <p className="trend-note">{group === 'days' ? 'До 14 последних дней по местному времени получения результатов, не начала боя.' : 'До 20 машин с наибольшим числом записанных боёв.'} Процент побед — среди известных исходов, средний урон — среди известных значений.</p>
  </section>;
}

function GoalCard({ goals, selected }: { goals: Goal[]; selected: string }) {
  const goal = goals.find(item => item.vehicle === selected) || goals[0];
  if (!goal) return <section className="goal-card">
    <div className="section-heading"><h2>Личная цель</h2><span className="subtle-tag">ПО ТЕХНИКЕ</span></div>
    <div className="goal-empty"><span className="target-symbol">◎</span><strong>Цель пока не задана</strong><p>Добавьте цель по среднему урону в локальный файл goals.json.</p></div>
  </section>;
  const percent = Math.max(0, Math.min(100, (goal.avg_damage || 0) * 100 / goal.target));
  const achieved = goal.status === 'achieved';
  return <section className="goal-card">
    <div className="section-heading"><h2>Личная цель</h2><span className="subtle-tag">{goal.window} БОЁВ</span></div>
    <div className="goal-vehicle"><span className="target-symbol">◎</span><strong>{vehicleLabel(goal.vehicle)}</strong></div>
    <div className="goal-values"><strong>{formatNumber(goal.avg_damage)}</strong><span>{'/ ' + formatNumber(goal.target)}</span></div>
    <span className="small muted">средний урон за серию</span>
    <div className="progress-track" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100} aria-label="Прогресс среднего урона">
      <div className={'progress-fill' + (achieved ? ' progress-done' : '')} style={{ width: percent + '%' }} />
    </div>
    <div className="goal-status"><span className={achieved ? 'positive' : 'muted'}>{goalLabels[goal.status]}</span><span>{goal.battles + '/' + goal.window}</span></div>
    <span className="tiny muted">Урон известен в {goal.known_damage} боях. Достижение учитывает полноту серии.</span>
  </section>;
}

function Comparison({ snapshot }: { snapshot: Snapshot }) {
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

function BattleHistory({ history }: { history: Snapshot['history'] }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(history.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  return <section className="history-section">
    <div className="section-heading"><h2>Последние бои</h2><span className="small muted">До 12 последних результатов</span></div>
    <div role="table" aria-label="Последние бои" className="history-table">
      <div role="row" className="history-row history-head"><span role="columnheader" className="col-time">Получен результат</span><span role="columnheader" className="col-vehicle">Техника</span><span role="columnheader" className="col-result">Исход</span><span role="columnheader" className="col-damage">Урон</span><span role="columnheader" className="col-xp" title="Значение из результата может учитывать бонусы; в разборе прогресса не используется.">Опыт из результата</span></div>
      <div className="history-scroll">
        {history.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map((battle, index) => <div role="row" className="history-row" key={battle.timestamp + ':' + index}>
          <span role="cell" className="col-time muted">{timeLabel(battle.timestamp)}</span>
          <span role="cell" className="col-vehicle" title={battle.vehicle}>{vehicleLabel(battle.vehicle)}</span>
          <span role="cell" className={'col-result result-' + (battle.outcome || 'unknown')}><span className="result-dot" />{outcomeLabel[battle.outcome || 'unknown'] || 'Неизвестно'}</span>
          <span role="cell" className="col-damage numeric">{formatNumber(battle.damage)}</span>
          <span role="cell" className="col-xp numeric muted">{formatNumber(battle.xp)}</span>
        </div>)}
      </div>
    </div>
    <div className="page-controls history-pages">
      <button type="button" aria-label="Предыдущая страница боёв" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</button>
      <span data-testid="history-page">{String(current + 1) + ' / ' + pages}</span>
      <button type="button" aria-label="Следующая страница боёв" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</button>
    </div>
  </section>;
}

export function SnapshotView({ snapshot, onSelectVehicle, section = 'all' }: { snapshot: Snapshot; onSelectVehicle?: (vehicle: string) => void; section?: PanelSection | 'all' }) {
  if (snapshot.status === 'account_unavailable') return <div className="empty-state" role="status"><span className="large-symbol">◎</span><h2>Аккаунт ещё не определён</h2><p>Данные появятся после входа в ангар. История других аккаунтов здесь не отображается.</p></div>;
  if (snapshot.status === 'empty') return <div className="empty-state" role="status"><span className="large-symbol">＋</span><h2>В этой выборке ещё нет боёв</h2><p>Завершите бой или выберите другую технику. История обновляется по полученным результатам.</p></div>;
  const summary = snapshot.summary;
  const quality = snapshot.quality;
  return <>
    {(section === 'all' || section === 'progress') && <><div className="metrics-row">
      <Metric label="БОЁВ В ВЫБОРКЕ" value={formatNumber(summary.battles)} detail="По выбранной технике" testId="battle-count" />
      <Metric label="ПОБЕДЫ" value={summary.win_rate === null ? '—' : formatNumber(summary.win_rate, 1) + '%'}
        detail={summary.wins + ' побед · ' + summary.losses + ' пораж. · ' + summary.draws + ' ничьих'} testId="win-rate" />
      <Metric label="СРЕДНИЙ УРОН" value={formatNumber(summary.avg_damage)} detail={'Известен в ' + summary.damage_samples + ' из ' + summary.battles + ' боёв'} emphasis testId="average-damage" />
    </div>
    {snapshot.coach && <CoachCard coach={snapshot.coach} latestVehicle={snapshot.history[0]?.vehicle} onSelectVehicle={onSelectVehicle} />}</>}
    {(section === 'all' || section === 'trend') && <div className="analysis-row">
      <DamagePanel snapshot={snapshot} />
      <GoalCard goals={snapshot.goals} selected={snapshot.selection.vehicle} />
    </div>}
    {section === 'summary' && <InsightsView snapshot={snapshot} />}
    {(section === 'all' || section === 'history') && <><BattleHistory history={snapshot.history} />
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
  useEffect(() => {
    vehicles.current = [];
    const instance = new SnapshotController(createBridge(), next => {
      if (next.snapshot) vehicles.current = next.snapshot.vehicles;
      else if (next.phase === 'error') vehicles.current = [];
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
  const choose = (selection: Selection) => control.current?.request(selection);
  const busy = state.phase === 'connecting' || state.phase === 'loading';
  const inactive = state.phase === 'connecting' || state.phase === 'closed';
  if (state.phase === 'closed') return <main className="page"><div className="closed-panel"><span className="brand-mark">TS</span><h1>Панель закрыта</h1>
    {mode !== 'gameface' && <button className="primary-button" type="button" onClick={() => { vehicles.current = []; setGeneration(generation + 1); }}>Открыть снова</button>}</div></main>;
  return <main className="page"><div className="panel" aria-busy={busy}>
    <header className="panel-header"><div className="brand"><span className="brand-mark">TS</span><div><h1>TankSession<span className="brand-sub">ANALYTICS</span></h1><p>История боёв и личный прогресс</p></div></div>
      <div className="header-actions"><SourceBadge mode={mode} /><button type="button" className="icon-button refresh" aria-label="Обновить статистику" disabled={inactive || busy} onClick={() => control.current?.request()}>Обновить</button>
        <button type="button" className="icon-button close" aria-label="Закрыть панель" onClick={() => control.current?.close()}>×</button></div></header>
    <div className="panel-content"><div className="toolbar"><VehiclePicker vehicles={vehicles.current} selected={state.selection.vehicle} disabled={inactive} onSelect={vehicle => choose({ ...state.selection, vehicle })} />
      <div className="period-control"><span className="field-label">ПЕРИОД СРАВНЕНИЯ</span><div className="period-buttons" role="group" aria-label="Размер периода">
        {([10, 30, 100] as WindowSize[]).map(size => <button key={size} type="button" aria-label={size + ' боёв'} aria-pressed={state.selection.window === size} disabled={inactive}
          className={state.selection.window === size ? 'active' : ''} onClick={() => choose({ ...state.selection, window: size })}>{size + ' боёв'}</button>)}
      </div></div><span className="local-note"><span className="status-dot" />Данные на вашем компьютере</span></div>
      <div className="section-tabs" role="group" aria-label="Разделы статистики">
        {SECTIONS.map(item => <button type="button" key={item.id} aria-pressed={section === item.id} className={section === item.id ? 'active' : ''} disabled={inactive} onClick={() => setSection(item.id)}>{item.label}</button>)}
      </div>
      {state.phase === 'ready' && state.snapshot ? <><PendingNotice snapshot={state.snapshot} /><SnapshotView snapshot={state.snapshot} section={section} onSelectVehicle={vehicle => choose({ ...state.selection, vehicle })} /></> : state.phase === 'error' ? <div className="empty-state error-state" role="alert">
        <span className="large-symbol">!</span><h2>Данные сейчас недоступны</h2><p>{state.message}</p><button className="primary-button" type="button" onClick={() => setGeneration(generation + 1)}>Повторить подключение</button>
      </div> : <div className="empty-state loading-state" role="status"><span className="loading-bar" /><h2>{state.phase === 'connecting' ? 'Подключаем панель' : 'Обновляем статистику'}</h2><p>Показатели появятся после получения данных.</p></div>}
    </div>
    <footer className="panel-footer"><span>{mode === 'demo' ? 'Демонстрация интерфейса · данные вымышлены' : 'Только собственные завершённые бои'}</span>
      <span>{state.snapshot ? 'Обновлено ' + timeLabel(state.snapshot.updated_at) : 'TankSession Analytics'}</span></footer>
  </div></main>;
}
