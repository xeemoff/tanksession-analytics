import { useState } from 'react';
import { HistoryBattle, Snapshot } from './contracts';
import { formatNumber, outcomeLabel, timeLabel } from './format';
import { vehicleLabel } from './vehicleLabel';

function BattleDetails({ battle, onBack }: { battle: HistoryBattle; onBack: () => void }) {
  const [tab, setTab] = useState<'battle' | 'economy'>('battle');
  const item = (label: string, value: string, detail?: string) => <div className="detail-metric" key={label}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
  return <section className="battle-detail" aria-label="Подробности боя">
    <div className="section-heading"><h2>{vehicleLabel(battle.vehicle, battle.vehicle_label) + ' · ' + timeLabel(battle.timestamp)}</h2><button type="button" onClick={onBack}>К списку боёв</button></div>
    <div className="insight-switch" role="group" aria-label="Показатели боя">
      <button type="button" aria-pressed={tab === 'battle'} className={tab === 'battle' ? 'active' : ''} onClick={() => setTab('battle')}>Бой и стрельба</button>
      <button type="button" aria-pressed={tab === 'economy'} className={tab === 'economy' ? 'active' : ''} onClick={() => setTab('economy')}>Опыт и экономика</button>
    </div>
    <div className="detail-grid">
      {tab === 'battle' ? <>
        {item('Исход', outcomeLabel[battle.outcome || 'unknown'] || 'Неизвестно')}
        {item('Урон', formatNumber(battle.damage))}
        {item('Карта', battle.map || '—')}
        {item('Уничтожено', formatNumber(battle.kills ?? null))}
        {item('Выжил', battle.survived === undefined || battle.survived === null ? '—' : battle.survived ? 'Да' : 'Нет')}
        {item('Выстрелы / попадания / пробития', [battle.shots, battle.direct_hits, battle.penetrations].map(v => formatNumber(v ?? null)).join(' / '))}
        {item('Помощь разведкой', formatNumber(battle.assistance_radio ?? null))}
        {item('Помощь по гусенице', formatNumber(battle.assistance_track ?? null))}
      </> : <>
        {item('Опыт из результата', formatNumber(battle.xp), 'Может включать бонусы')}
        {item('Базовый опыт', formatNumber(battle.xp_base ?? null), 'Если базовый опыт известен')}
        {item('Бонусный опыт', formatNumber(battle.xp_bonus ?? null), 'Сверх базового опыта после корректировок')}
        {item('Начислено кредитов', formatNumber(battle.credits_gross ?? null))}
        {item('Итог кредитов', formatNumber(battle.credits_net ?? null), 'Фактические списания в кредитах. Запасы со склада не оцениваются.')}
      </>}
    </div>
    <p className="trend-note">Время — получение результата. Тире означает, что поле не получено. Старые записи сохраняются без вымышленных значений.</p>
  </section>;
}

export function BattleHistory({ snapshot, onPage, busy = false }: { snapshot: Snapshot; onPage?: (page: number) => void; busy?: boolean }) {
  const [page, setPage] = useState(0);
  const [details, setDetails] = useState<HistoryBattle | null>(null);
  const history = snapshot.history;
  const pagination = snapshot.pagination;
  const pages = pagination ? pagination.pages : Math.max(1, Math.ceil(history.length / 5));
  const current = pagination ? pagination.page : Math.min(page, pages - 1);
  const rows = pagination ? history : history.slice(current * 5, (current + 1) * 5);
  const navigate = (next: number) => { setDetails(null); if (pagination) onPage?.(next); else setPage(next); };
  if (details) return <BattleDetails battle={details} onBack={() => setDetails(null)} />;
  return <section className="history-section">
    <div className="section-heading"><h2>{pagination ? 'История боёв' : 'Последние бои'}</h2><span className="small muted">{pagination ? pagination.total + ' записей · выбранная техника' : 'До 12 последних результатов'}</span></div>
    <div role="table" aria-label="Последние бои" className="history-table">
      <div role="row" className="history-row history-head"><span role="columnheader" className="col-time">Получен результат</span><span role="columnheader" className="col-vehicle">Техника</span><span role="columnheader" className="col-result">Исход</span><span role="columnheader" className="col-damage">Урон</span><span role="columnheader" className="col-xp" title="Опыт из результата может включать бонусы. Известные базовый и бонусный опыт доступны в подробностях.">Полученный опыт</span><span role="columnheader" className="col-details">Подробнее</span></div>
      <div className="history-scroll">
        {rows.map((battle, index) => <div role="row" className="history-row" key={battle.timestamp + ':' + index}>
          <span role="cell" className="col-time muted">{timeLabel(battle.timestamp)}</span>
          <span role="cell" className="col-vehicle" title={vehicleLabel(battle.vehicle, battle.vehicle_label)}>{vehicleLabel(battle.vehicle, battle.vehicle_label)}</span>
          <span role="cell" className={'col-result result-' + (battle.outcome || 'unknown')}><span className="result-dot" />{outcomeLabel[battle.outcome || 'unknown'] || 'Неизвестно'}</span>
          <span role="cell" className="col-damage numeric">{formatNumber(battle.damage)}</span>
          <span role="cell" className="col-xp numeric muted">{formatNumber(battle.xp)}</span>
          <span role="cell" className="col-details"><button type="button" className="detail-button" aria-label={'Подробности боя ' + (current * 5 + index + 1)} onClick={() => setDetails(battle)}>Открыть</button></span>
        </div>)}
      </div>
    </div>
    <div className="page-controls history-pages">
      <button type="button" aria-label="Первая страница боёв" disabled={busy || current === 0 || (!!pagination && !onPage)} onClick={() => navigate(0)}>В начало</button>
      <button type="button" aria-label="Предыдущая страница боёв" disabled={busy || current === 0 || (!!pagination && !onPage)} onClick={() => navigate(current - 1)}>Назад</button>
      <span data-testid="history-page">{String(current + 1) + ' / ' + pages}</span>
      <button type="button" aria-label="Следующая страница боёв" disabled={busy || current + 1 >= pages || (!!pagination && !onPage)} onClick={() => navigate(current + 1)}>Далее</button>
      <button type="button" aria-label="Последняя страница боёв" disabled={busy || current + 1 >= pages || (!!pagination && !onPage)} onClick={() => navigate(pages - 1)}>В конец</button>
    </div>
  </section>;
}
