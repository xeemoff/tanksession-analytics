import { Button } from './Button';
import { useState } from 'react';
import { AnalysisGroup, Analytics, Snapshot, TotalMetric } from './contracts';
import { formatNumber } from './format';
import { vehicleLabel } from './vehicleLabel';
import { nationLabels, VehicleCollection } from './VehicleCards';

export type GroupMetric = 'battles' | 'damage' | 'wins' | 'credits';
const metricLabels: Record<GroupMetric, string> = { battles: 'Бои', damage: 'Средний урон', wins: 'Победы, %', credits: 'Кредиты за бой' };
const dimensionLabels: Record<keyof Analytics['dimensions'], string> = { maps: 'Карты', tiers: 'Уровни', classes: 'Классы', nations: 'Нации' };
const dimensionCoverage: Record<keyof Analytics['dimensions'], keyof Analytics['coverage']> = {
  maps: 'map_label', tiers: 'vehicle_tier', classes: 'vehicle_class', nations: 'vehicle_nation'
};
export function groupValue(group: AnalysisGroup, metric: GroupMetric): number | null {
  return metric === 'battles' ? group.summary.battles : metric === 'damage' ? group.summary.avg_damage
    : metric === 'wins' ? group.summary.win_rate : group.credits_net.average;
}
export function sortGroups(groups: AnalysisGroup[], metric: GroupMetric, order: 'battles' | 'metric'): AnalysisGroup[] {
  return [...groups].sort((a, b) => {
    const left = groupValue(a, order === 'battles' ? 'battles' : metric);
    const right = groupValue(b, order === 'battles' ? 'battles' : metric);
    if (left === null && right !== null) return 1;
    if (right === null && left !== null) return -1;
    if (left !== null && right !== null && left !== right) return right - left;
    return a.key === b.key ? 0 : a.key < b.key ? -1 : 1;
  });
}
function groupCaption(group: AnalysisGroup, vehicles: boolean): string {
  return vehicles ? vehicleLabel(group.key, group.vehicle_label || group.label) : group.label;
}

export function Coverage({ samples, total, label = 'Известно' }: { samples: number; total: number; label?: string }) {
  return <div className="coverage-line"><span>{label + ' в ' + samples + ' из ' + total + ' боёв'}</span>
    <span className="coverage-track" aria-hidden="true"><span style={{ width: (total ? samples * 100 / total : 0) + '%' }} /></span></div>;
}

export function GroupChart({ groups, title, vehicles = false, initialMetric = 'battles' }: {
  groups: AnalysisGroup[]; title: string; vehicles?: boolean; initialMetric?: GroupMetric;
}) {
  const [metric, setMetric] = useState<GroupMetric>(initialMetric);
  const [order, setOrder] = useState<'battles' | 'metric'>('battles');
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(groups.length / 6));
  const current = Math.min(page, pages - 1);
  const ordered = sortGroups(groups, metric, order);
  const rows = ordered.slice(current * 6, current * 6 + 6);
  const active = groups.find(item => item.key === selected) || rows[0];
  const values = groups.map(item => groupValue(item, metric)).filter((value): value is number => value !== null);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = Math.max(1, max - min);
  const zero = -min / range * 100;
  const caption = (group: AnalysisGroup) => groupCaption(group, vehicles);
  const describe = (group: AnalysisGroup) => caption(group) + ' · ' + metricLabels[metric] + ': ' + formatNumber(groupValue(group, metric), metric === 'battles' ? 0 : 1);
  return <section className="group-chart" aria-label={title}>
    <div className="group-chart-toolbar"><h3>{title}</h3><div className="insight-switch chart-metrics" role="group" aria-label="Показатель графика">
      {(Object.keys(metricLabels) as GroupMetric[]).map(key => <Button type="button" key={key} aria-pressed={metric === key} className={metric === key ? 'active' : ''} onClick={() => { setMetric(key); setPage(0); setSelected(null); }}>{metricLabels[key]}</Button>)}
    </div></div>
    <div className="group-order" role="group" aria-label="Порядок групп"><span>Порядок:</span>{([['battles', 'По числу боёв'], ['metric', 'По показателю']] as const).map(([key, label]) => <Button type="button" key={key} aria-pressed={order === key} className={order === key ? 'active' : ''} onClick={() => { setOrder(key); setPage(0); setSelected(null); }}>{label}</Button>)}</div>
    {groups.length ? <div className="group-chart-layout"><div className="group-chart-bars" role="group" aria-label="Группы на графике">
      {rows.map(group => {
        const value = groupValue(group, metric);
        const position = value === null ? zero : (value - min) / range * 100;
        return <Button type="button" key={group.key} className={'group-bar-row' + (active?.key === group.key ? ' selected' : '')}
          aria-label={describe(group)} aria-pressed={active?.key === group.key} title={describe(group)}
          onClick={() => setSelected(group.key)} onFocus={() => setSelected(group.key)} onKeyDown={event => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            event.preventDefault();
            const siblings = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('button'));
            siblings[(siblings.indexOf(event.currentTarget) + (event.key === 'ArrowDown' ? 1 : siblings.length - 1)) % siblings.length]?.focus();
          }}>
          <span className="group-bar-label">{caption(group)}</span><span className="group-bar-track" aria-hidden="true">
            <span className="group-bar-zero" style={{ left: zero + '%' }} />
            {value !== null && <span className={'group-bar-fill' + (value < 0 ? ' negative-bar' : '')} style={{ left: Math.min(zero, position) + '%', width: Math.max(0.5, Math.abs(position - zero)) + '%' }} />}
          </span><strong className={value !== null && value < 0 ? 'negative' : ''}>{formatNumber(value, metric === 'battles' ? 0 : 1)}</strong>
        </Button>;
      })}
    </div>{active && <aside className="group-selection" aria-live="polite" aria-label="Выбранная группа">
      <span className="eyebrow">ВЫБРАННАЯ ГРУППА</span><h3>{caption(active)}</h3>
      <dl><div><dt>Бои</dt><dd>{formatNumber(active.summary.battles)}</dd></div><div><dt>Средний урон</dt><dd>{formatNumber(active.summary.avg_damage, 1)}</dd></div>
        <div><dt>Побед</dt><dd>{formatNumber(active.summary.win_rate, 1) + (active.summary.win_rate === null ? '' : '%')}</dd></div><div><dt>Кредитов за бой</dt><dd>{formatNumber(active.credits_net.average, 1)}</dd></div></dl>
      <Coverage samples={active.summary.damage_samples} total={active.summary.battles} label="Урон известен" />
      <Coverage samples={active.credits_net.samples} total={active.summary.battles} label="Итог кредитов известен" />
    </aside>}</div> : <div className="chart-empty"><strong>Для этого среза пока нет записей</strong><span>Сохранённые результаты появятся здесь после получения данных.</span></div>}
    {pages > 1 && <div className="page-controls"><Button type="button" disabled={current === 0} onClick={() => { setPage(current - 1); setSelected(null); }} aria-label="Предыдущая страница графика">Назад</Button><span>{String(current + 1) + ' / ' + pages}</span><Button type="button" disabled={current + 1 >= pages} onClick={() => { setPage(current + 1); setSelected(null); }} aria-label="Следующая страница графика">Далее</Button></div>}
    <p className="chart-footnote">Нажмите на строку или выберите её клавиатурой. Тире — неизвестное значение. Разница показателей сама по себе не объясняет её причину.</p>
  </section>;
}

export function ActivityGrid({ groups, unit }: { groups: AnalysisGroup[]; unit: keyof Analytics['activity'] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const active = groups.find(group => group.key === selected) || groups[groups.length - 1];
  const max = Math.max(1, ...groups.map(group => group.summary.battles));
  if (!active) return <div className="chart-empty"><strong>Нет данных об активности</strong></div>;
  const caption = (group: AnalysisGroup) => unit === 'days' ? group.label.slice(5) : unit === 'hours' ? group.label.slice(0, 2) : group.label.slice(0, 3);
  const description = (group: AnalysisGroup) => group.label + ' · ' + group.summary.battles + ' боёв';
  return <div className="activity-grid-wrap"><div className={'activity-grid activity-grid-' + unit} role="group" aria-label={unit === 'days' ? 'Календарь активности' : unit === 'hours' ? 'Часы активности' : 'Дни недели активности'}>
    {groups.map((group, index) => <Button type="button" key={group.key} className={'activity-cell' + (active.key === group.key ? ' selected' : '') + (group.summary.battles === 0 ? ' empty' : '')}
      aria-label={description(group)} title={description(group)} aria-pressed={active.key === group.key} tabIndex={active.key === group.key ? 0 : -1}
      onClick={() => setSelected(group.key)} onFocus={() => setSelected(group.key)} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const buttons = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('button'));
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : buttons.length - 1)) % buttons.length;
        buttons[next]?.focus();
      }}><span className="activity-intensity" aria-hidden="true" style={{ height: Math.max(0, group.summary.battles * 100 / max) + '%' }} /><span className="activity-label">{caption(group)}</span><strong>{group.summary.battles}</strong></Button>)}
  </div><div className="activity-selection" aria-live="polite" data-testid="activity-selection"><strong>{description(active)}</strong><span>{'Средний урон: ' + formatNumber(active.summary.avg_damage, 1) + ' · известен в ' + active.summary.damage_samples + '/' + active.summary.battles}</span><span>{'Итог кредитов: ' + formatNumber(active.credits_net.total) + ' · известен в ' + active.credits_net.samples + '/' + active.summary.battles}</span></div>
    <p className="chart-footnote">Число в ячейке — бои, фон показывает их количество. Ноль означает отсутствие записей за интервал. Выбор: щелчок или стрелки влево и вправо.</p>
  </div>;
}

export function ActivityView({ snapshot }: { snapshot: Snapshot }) {
  const [group, setGroup] = useState<keyof Analytics['activity']>('days');
  const analytics = snapshot.analytics;
  if (!analytics) return <FeatureUnavailable name="Активность" />;
  return <section className="activity-view">
    <div className="section-heading"><div><h2>Ритм сохранённых боёв</h2><p className="section-description">Получение результата · UTC, не местное время</p></div>
      <div className="insight-switch" role="group" aria-label="Группировка активности">
        {([['days', 'По датам'], ['weekdays', 'Дни недели'], ['hours', 'Часы']] as const).map(([key, label]) => <Button key={key} type="button" className={group === key ? 'active' : ''} aria-pressed={group === key} onClick={() => setGroup(key)}>{label}</Button>)}
      </div></div>
    <ActivityGrid key={group} groups={analytics.activity[group]} unit={group} />
    <p className="trend-note">Поздний результат относится к моменту его получения. Часы и дни описывают вашу историю; это не рекомендация о времени игры.</p>
  </section>;
}

export function EconomyTotal({ label, value, battles, signed = false, detail }: { label: string; value: TotalMetric; battles: number; signed?: boolean; detail?: string }) {
  return <article className="economy-total"><span className="eyebrow">{label}</span><strong className={signed && value.total !== null && value.total < 0 ? 'negative' : ''}>{formatNumber(value.total)}</strong>
    <span className="economy-average">{value.average === null ? 'Среднее пока неизвестно' : formatNumber(value.average, 1) + ' в среднем за известный бой'}</span>
    <Coverage samples={value.samples} total={battles} />{detail && <p>{detail}</p>}
  </article>;
}

export function EconomyView({ snapshot, compact = false }: { snapshot: Snapshot; compact?: boolean }) {
  const data = snapshot.analytics?.economy;
  if (!data) return <FeatureUnavailable name="Экономика истории" />;
  return <section className="economy-view" aria-label="Экономика сохранённых боёв">
    <div className="section-heading"><div><h2>Экономика истории</h2><p className="section-description">Суммы известных значений в выбранной истории</p></div><span className="subtle-tag">{snapshot.summary.battles + ' БОЁВ'}</span></div>
    <div className="economy-totals"><EconomyTotal label="ИТОГ КРЕДИТОВ" value={data.credits_net} battles={snapshot.summary.battles} signed />
      <EconomyTotal label="НАЧИСЛЕНО КРЕДИТОВ" value={data.credits_gross} battles={snapshot.summary.battles} />
      <EconomyTotal label="БОНУСНЫЙ ОПЫТ" value={data.xp_bonus} battles={snapshot.summary.battles} /></div>
    {!compact && <GroupChart groups={data.vehicles} title="Итог кредитов по технике" vehicles initialMetric="credits" />}
    <p className="trend-note">Итог кредитов учитывает известные реальные списания. Запасы со склада не оцениваются. Пропуски не считаются нулём; сумма части истории не является полным итогом. Бонусный опыт — превышение базового после корректировок, без разбивки по источникам.</p>
  </section>;
}

export function FeatureUnavailable({ name }: { name: string }) {
  return <div className="chart-empty"><strong>Для этого раздела нужен обновлённый источник</strong><span>{name + '. Старая история остаётся доступной.'}</span></div>;
}

export function AnalyticsView({ snapshot, onSelectVehicle }: { snapshot: Snapshot; onSelectVehicle?: (key: string) => void }) {
  const [tab, setTab] = useState<'dimensions' | 'activity' | 'economy' | 'vehicles'>('dimensions');
  const [dimension, setDimension] = useState<keyof Analytics['dimensions']>('maps');
  const analytics = snapshot.analytics;
  return <section className="analytics-view" aria-label="Расширенная аналитика">
    <div className="insight-switch feature-tabs" role="group" aria-label="Разделы аналитики">
      {([['dimensions', 'Срезы результатов'], ['activity', 'Активность'], ['economy', 'Экономика'], ['vehicles', 'Техника']] as const).map(([key, label]) => <Button key={key} type="button" className={tab === key ? 'active' : ''} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</Button>)}
    </div>
    {tab === 'vehicles' ? <VehicleCollection snapshot={snapshot} onSelect={onSelectVehicle} />
      : tab === 'activity' ? <ActivityView snapshot={snapshot} /> : tab === 'economy' ? <EconomyView snapshot={snapshot} />
        : !analytics ? <FeatureUnavailable name="Расширенная аналитика" /> : <>
          <div className="section-heading"><div><h2>Результаты в контексте</h2><p className="section-description">Наблюдаемые группы внутри выбранной истории</p></div>
            <div className="insight-switch" role="group" aria-label="Срез результатов">{(Object.keys(dimensionLabels) as Array<keyof Analytics['dimensions']>).map(key => <Button type="button" key={key} aria-pressed={dimension === key} className={dimension === key ? 'active' : ''} onClick={() => setDimension(key)}>{dimensionLabels[key]}</Button>)}</div></div>
          <Coverage samples={analytics.coverage[dimensionCoverage[dimension]]} total={snapshot.summary.battles} label="Признак известен" />
          <GroupChart key={dimension} groups={analytics.dimensions[dimension].map(group => dimension === 'nations' && nationLabels[group.key] ? { ...group, label: nationLabels[group.key] } : group)} title={dimensionLabels[dimension]} />
          <p className="trend-note">Неизвестные характеристики сохранены отдельной группой. «Другие» объединяет группы за пределом списка. Состав техники, режимы и условия боёв могут отличаться.</p>
        </>}
  </section>;
}
