import { Button } from './Button';
import { useState } from 'react';
import { PeriodReport, Snapshot } from './contracts';
import { EconomyTotal, FeatureUnavailable, GroupChart } from './Analytics';
import { formatNumber, signed } from './format';

function utcTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const pad = (value: number) => value < 10 ? '0' + value : String(value);
  return pad(date.getUTCDate()) + '.' + pad(date.getUTCMonth() + 1) + '.' + date.getUTCFullYear()
    + ' ' + pad(date.getUTCHours()) + ':' + pad(date.getUTCMinutes()) + ':' + pad(date.getUTCSeconds());
}
export function reportRange(report: Pick<PeriodReport, 'start_at' | 'end_at'>): string {
  return (report.start_at === null ? 'С начала истории' : utcTime(report.start_at)) + ' — ' + utcTime(report.end_at - 1) + ' UTC';
}

export function ReportsView({ snapshot, compact = false }: { snapshot: Snapshot; compact?: boolean }) {
  const [period, setPeriod] = useState<PeriodReport['key']>('week');
  const [tab, setTab] = useState<'overview' | 'vehicles'>('overview');
  const reports = snapshot.reports;
  if (!reports) return <FeatureUnavailable name="Периодические отчёты" />;
  const report = reports.periods.find(item => item.key === period) || reports.periods[0];
  if (!report) return <div className="chart-empty"><strong>Пока нет отчётов</strong></div>;
  const previous = report.previous;
  const c = report.comparison;
  const comparisonRows = previous ? [
    { label: 'Средний урон', before: previous.summary.avg_damage, current: report.summary.avg_damage, delta: c.avg_damage_delta, suffix: '', previousSamples: previous.summary.damage_samples, samples: report.summary.damage_samples },
    { label: 'Победы', before: previous.summary.win_rate, current: report.summary.win_rate, delta: c.win_rate_delta_pp, suffix: ' п. п.', previousSamples: previous.summary.known_outcomes, samples: report.summary.known_outcomes },
    { label: 'Итог кредитов за бой', before: previous.credits_net.average, current: report.credits_net.average, delta: c.credits_net_average_delta, suffix: '', previousSamples: previous.credits_net.samples, samples: report.credits_net.samples }
  ] : [];
  return <section className="reports-view" aria-label="Периодический отчёт">
    <div className="section-heading"><div><h2>Ваш отчёт</h2><p className="section-description">По выбранной технике · время получения результатов</p></div>
      <div className="insight-switch report-periods" role="group" aria-label="Период отчёта">{([['week', '7 дней'], ['month', '30 дней'], ['all_time', 'Вся история']] as const).map(([key, label]) => <Button type="button" key={key} className={period === key ? 'active' : ''} aria-pressed={period === key} onClick={() => setPeriod(key)}>{label}</Button>)}</div></div>
    <p className="report-range" data-testid="report-range">{reportRange(report)}</p>
    {!compact && <div className="insight-switch" role="group" aria-label="Содержание отчёта"><Button type="button" className={tab === 'overview' ? 'active' : ''} aria-pressed={tab === 'overview'} onClick={() => setTab('overview')}>Кратко</Button><Button type="button" className={tab === 'vehicles' ? 'active' : ''} aria-pressed={tab === 'vehicles'} onClick={() => setTab('vehicles')}>По технике</Button></div>}
    {!compact && tab === 'vehicles' ? <GroupChart key={period} groups={report.vehicles} title="Техника за период" vehicles /> : <>
      <div className="report-totals"><article><span>БОЁВ</span><strong data-testid="report-battles">{formatNumber(report.summary.battles)}</strong></article>
        <article><span>ПОБЕДЫ</span><strong>{formatNumber(report.summary.win_rate, 1) + (report.summary.win_rate === null ? '' : '%')}</strong><small>{report.summary.known_outcomes + ' известных исходов'}</small></article>
        <article><span>СРЕДНИЙ УРОН</span><strong>{formatNumber(report.summary.avg_damage, 1)}</strong><small>{report.summary.damage_samples + ' известных результатов'}</small></article></div>
      {!compact && previous && <div className="report-comparison"><div className="section-heading"><h3>К предыдущему равному периоду</h3><span className={'report-status report-' + c.status}>{c.status === 'ready' ? 'Данные доступны' : c.status === 'partial_data' ? 'Есть пропуски' : 'Нет боёв в одном из периодов'}</span></div>
        <p className="report-previous-range">{reportRange(previous)}</p>
        <div className="history-table report-table" role="table" aria-label="Сравнение периодов отчёта">
          <div className="history-row history-head" role="row"><span role="columnheader">Показатель</span><span role="columnheader">Ранее</span><span role="columnheader">Сейчас</span><span role="columnheader">Разница</span></div>
          {comparisonRows.map(row => <div className="history-row" role="row" key={row.label}><span role="rowheader">{row.label}</span>
            <span role="cell">{formatNumber(row.before, 1)}<small>{row.previousSamples + '/' + previous.summary.battles + ' боёв'}</small></span>
            <span role="cell">{formatNumber(row.current, 1)}<small>{row.samples + '/' + report.summary.battles + ' боёв'}</small></span>
            <span role="cell" className={row.delta === null || row.delta === 0 ? 'muted' : row.delta > 0 ? 'positive' : 'negative'}>{signed(row.delta, row.suffix)}</span></div>)}
        </div>
      </div>}
      <div className="economy-totals report-economy"><EconomyTotal label="ИТОГ КРЕДИТОВ" value={report.credits_net} battles={report.summary.battles} signed />
        <EconomyTotal label="БОНУСНЫЙ ОПЫТ" value={report.xp_bonus} battles={report.summary.battles} /></div>
      {!compact && <p className="chart-footnote">{previous ? 'Разница показана только при полной известности соответствующего поля в обоих периодах. ' : 'Вся история — общий итог без предыдущего периода. '}Суммы относятся к известным значениям. Изменение состава боёв может влиять на показатели.</p>}
    </>}
    {reports.excluded_future > 0 && <p className="report-warning" role="status">{'Записей с временем в будущем: ' + reports.excluded_future + '. Они сохранены в истории, но не включены в отчёт.'}</p>}
  </section>;
}
