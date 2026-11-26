import { ReactNode, useState } from 'react';
import { Snapshot } from './contracts';
import { formatNumber, signed, timeLabel } from './format';

export function ExtendedMetricsView({ snapshot }: { snapshot: Snapshot }) {
  const [tab, setTab] = useState<'combat' | 'economy' | 'maps'>('combat');
  const [page, setPage] = useState(0);
  const metrics = snapshot.metrics;
  if (!metrics) return <div className="chart-empty"><strong>Дополнительные показатели недоступны</strong><span>Источник пока не передаёт эти поля.</span></div>;
  const metric = (label: string, value: string, samples: number, detail: string) => <div className="detail-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{'Известно в ' + samples + ' из ' + snapshot.summary.battles + ' боёв. ' + detail}</small></div>;
  const percent = (value: number | null) => value === null ? '—' : formatNumber(value, 1) + '%';
  const pages = Math.max(1, Math.ceil(metrics.maps.length / 5));
  const current = Math.min(page, pages - 1);
  return <section className="extended-metrics" aria-label="Дополнительные показатели">
    <div className="insight-switch" role="group" aria-label="Группа показателей">
      <button type="button" className={tab === 'combat' ? 'active' : ''} aria-pressed={tab === 'combat'} onClick={() => setTab('combat')}>Бой и стрельба</button>
      <button type="button" className={tab === 'economy' ? 'active' : ''} aria-pressed={tab === 'economy'} onClick={() => setTab('economy')}>Опыт и кредиты</button>
      <button type="button" className={tab === 'maps' ? 'active' : ''} aria-pressed={tab === 'maps'} onClick={() => setTab('maps')}>Карты</button>
    </div>
    {tab === 'combat' && <div className="detail-grid">
      {metric('Уничтожено в среднем', formatNumber(metrics.fields.kills.average, 2), metrics.fields.kills.samples, 'По известным значениям.')}
      {metric('Выживаемость', percent(metrics.survival.rate), metrics.survival.samples, 'Выжил в ' + metrics.survival.survived + ' боях.')}
      {metric('Попадания от выстрелов', percent(metrics.accuracy.rate), metrics.accuracy.samples, metrics.accuracy.hits + ' попаданий / ' + metrics.accuracy.shots + ' выстрелов.')}
      {metric('Пробития от попаданий', percent(metrics.penetration.rate), metrics.penetration.samples, metrics.penetration.penetrations + ' пробитий / ' + metrics.penetration.hits + ' попаданий.')}
    </div>}
    {tab === 'economy' && <div className="detail-grid">
      {metric('Средний базовый опыт', formatNumber(metrics.fields.xp_base.average), metrics.fields.xp_base.samples, 'Отдельное поле, без расчёта по бонусам.')}
      {metric('Кредиты начислены в среднем', formatNumber(metrics.fields.credits_gross.average), metrics.fields.credits_gross.samples, 'До расходов, если значение получено.')}
      {metric('Итог кредитов в среднем', formatNumber(metrics.fields.credits_net.average), metrics.fields.credits_net.samples, 'Может быть отрицательным.')}
    </div>}
    {tab === 'maps' && <>
      {metrics.maps.length === 0 ? <div className="chart-empty"><strong>Карты ещё не определены</strong><span>Записи без карты остаются в общей истории.</span></div> : <div className="history-table compact-summary" role="table" aria-label="Результаты по картам">
        <div className="history-row history-head" role="row"><span role="columnheader">Карта</span><span role="columnheader">Бои</span><span role="columnheader">Побед, %</span><span role="columnheader">Ср. урон</span></div>
        {metrics.maps.slice(current * 5, (current + 1) * 5).map(row => <div key={row.label} className="history-row" role="row"><span role="cell">{row.label}</span><span role="cell">{row.summary.battles}</span><span role="cell">{formatNumber(row.summary.win_rate, 1)}</span><span role="cell">{formatNumber(row.summary.avg_damage)}</span></div>)}
      </div>}
      <div className="page-controls"><button type="button" aria-label="Предыдущая страница карт" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</button><span>{current + 1} / {pages}</span><button type="button" aria-label="Следующая страница карт" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</button></div>
    </>}
    <p className="trend-note">У каждой метрики своя полнота данных. Тире — поле не получено; ноль — известное значение. Показатели не восстанавливаются по косвенным признакам.</p>
  </section>;
}

const sessionReasons = {
  choose_vehicle: 'Выберите одну машину для сравнения сессий.',
  insufficient_data: 'Для сравнения нужно не менее 10 боёв в каждой из двух последних сессий.',
  incomplete: 'Урон известен не во всех боях двух сессий. Сравнение пока недоступно.',
  mixed_modes: 'В двух сессиях различаются или смешаны игровые режимы. Сравнение не выполняется.',
  mode_unknown: 'Режим части боёв неизвестен. Сравнение пока недоступно.',
  ready: 'Сравнение двух последних сессий на одной машине.'
};

export function SessionsView({ snapshot }: { snapshot: Snapshot }) {
  const [tab, setTab] = useState<'compare' | 'list'>('compare');
  const [page, setPage] = useState(0);
  const sessions = snapshot.sessions;
  if (!sessions) return <div className="chart-empty"><strong>Сессии недоступны в этой версии источника</strong></div>;
  const c = sessions.comparison;
  const pages = Math.max(1, Math.ceil(sessions.items.length / 4));
  const current = Math.min(page, pages - 1);
  return <section className="sessions-view" aria-label="Сессии">
    <div className="insight-switch" role="group" aria-label="Режим сессий">
      <button type="button" className={tab === 'compare' ? 'active' : ''} aria-pressed={tab === 'compare'} onClick={() => setTab('compare')}>Сравнение сессий</button>
      <button type="button" className={tab === 'list' ? 'active' : ''} aria-pressed={tab === 'list'} onClick={() => setTab('list')}>Последние сессии</button>
    </div>
    {tab === 'compare' ? <>
      <p className="session-verdict" role="status">{sessionReasons[c.status]}</p>
      <p className="muted small">{'Бои: текущая ' + c.current_battles + ' · предыдущая ' + c.previous_battles + ' · минимум ' + c.minimum_battles + ' в каждой.'}</p>
      {c.status === 'ready' && <div className="history-table compact-summary session-comparison" role="table" aria-label="Сравнение двух сессий">
        <div className="history-row history-head" role="row"><span role="columnheader">Показатель</span><span role="columnheader">Предыдущая</span><span role="columnheader">Текущая</span><span role="columnheader">Разница</span></div>
        <div className="history-row" role="row"><span role="cell">Средний урон</span><span role="cell">{formatNumber(c.previous_average, 1)}</span><span role="cell">{formatNumber(c.current_average, 1)}</span><span role="cell">{signed(c.delta_average)}</span></div>
        <div className="history-row" role="row"><span role="cell">Медиана урона</span><span role="cell">{formatNumber(c.previous_median, 1)}</span><span role="cell">{formatNumber(c.current_median, 1)}</span><span role="cell">{signed(c.delta_median)}</span></div>
      </div>}
      <p className="trend-note">Разница описывает записанные результаты и сама по себе не доказывает изменение навыка. Состав противников и условия боёв здесь не учитываются.</p>
    </> : <>
      <div className="history-table compact-summary" role="table" aria-label="Последние сессии">
        <div className="history-row history-head" role="row"><span role="columnheader">Получение результатов</span><span role="columnheader">Бои</span><span role="columnheader">Ср. урон</span><span role="columnheader">Медиана</span></div>
        {sessions.items.slice(current * 4, (current + 1) * 4).map((item, index) => <div className="history-row" role="row" key={item.started_at + ':' + index}><span role="cell">{timeLabel(item.started_at) + ' — ' + timeLabel(item.ended_at)}</span><span role="cell">{item.summary.battles}</span><span role="cell">{formatNumber(item.summary.avg_damage)}</span><span role="cell">{formatNumber(item.median_damage)}</span></div>)}
      </div>
      {sessions.items.length === 0 && <p className="session-verdict">Сохранённых сессий пока нет.</p>}
      <div className="page-controls"><button type="button" disabled={current === 0} aria-label="Предыдущая страница сессий" onClick={() => setPage(current - 1)}>Назад</button><span>{current + 1} / {pages}</span><button type="button" disabled={current + 1 >= pages} aria-label="Следующая страница сессий" onClick={() => setPage(current + 1)}>Далее</button></div>
    </>}
    <p className="trend-note">Сессии разделены перерывом от 60 минут по времени получения результатов. Это условная группировка: поздний результат может попасть в следующую сессию.</p>
  </section>;
}

export function SummaryView({ snapshot, children }: { snapshot: Snapshot; children: ReactNode }) {
  const [tab, setTab] = useState<'overview' | 'metrics' | 'sessions'>('overview');
  return <>
    <div className="summary-tabs insight-switch" role="group" aria-label="Раздел сводки">
      <button type="button" className={tab === 'overview' ? 'active' : ''} aria-pressed={tab === 'overview'} onClick={() => setTab('overview')}>Обзор</button>
      <button type="button" className={tab === 'metrics' ? 'active' : ''} aria-pressed={tab === 'metrics'} onClick={() => setTab('metrics')}>Показатели</button>
      <button type="button" className={tab === 'sessions' ? 'active' : ''} aria-pressed={tab === 'sessions'} onClick={() => setTab('sessions')}>Сессии</button>
    </div>
    {tab === 'overview' ? children : tab === 'metrics' ? <ExtendedMetricsView snapshot={snapshot} /> : <SessionsView snapshot={snapshot} />}
  </>;
}
