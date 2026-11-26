import { useState } from 'react';
import { Coach } from './contracts';
import { vehicleLabel } from './vehicleLabel';

function number(value: number | null, digits = 0): string {
  if (value === null) return '—';
  const parts = value.toFixed(digits).split('.');
  return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (parts.length > 1 ? ',' + parts[1] : '');
}
function delta(value: number): string { return (value > 0 ? '+' : '') + number(value, 1); }

function Records({ coach }: { coach: Coach }) {
  const records = coach.records;
  return <div className="coach-records">
    <div className="coach-record">
      <span className="coach-record-label">Лучший бой в локальной истории</span>
      <div className="coach-record-value"><strong data-testid="coach-best-damage">{number(records.best_damage)}</strong><span>урона</span>
        {records.new_damage_record && <span className="coach-record-badge">Новый рекорд</span>}</div>
      <p>{records.new_damage_record ? 'Последний сохранённый бой превысил прежний максимум: ' + number(records.previous_best_damage) + '.'
        : coach.battles === 1 ? 'Первая запись — точка отсчёта для будущих результатов.'
        : records.latest_damage === null ? 'Урон последнего полученного результата пока неизвестен.'
        : 'Последний сохранённый бой: ' + number(records.latest_damage) + ' урона.'}</p>
    </div>
    <div className="coach-record">
      <span className="coach-record-label">{'Лучшая серия из ' + coach.window + ' боёв'}</span>
      <div className="coach-record-value"><strong data-testid="coach-best-window">{number(records.best_window_avg, 1)}</strong><span>в среднем</span>
        {records.new_window_record && <span className="coach-record-badge">Новый рекорд</span>}</div>
      <p>{records.new_window_record ? 'Текущая серия превысила прежний максимум: ' + number(records.previous_best_window_avg, 1) + '.'
        : records.best_window_avg === null ? 'Нужны ' + coach.window + ' последовательных боёв с известным уроном.'
        : records.current_window_avg === null ? 'Текущая серия ещё не полна или содержит пропуски.'
        : 'Текущая серия: ' + number(records.current_window_avg, 1) + '. Сравниваются все полные серии в истории.'}</p>
    </div>
  </div>;
}

export function CoachCard({ coach, latestVehicle, onSelectVehicle }: {
  coach: Coach; latestVehicle?: string; onSelectVehicle?: (vehicle: string) => void;
}) {
  const [explain, setExplain] = useState(false);
  const comparison = coach.comparison;
  const choose = coach.status === 'choose_vehicle';
  const positive = comparison !== null && comparison.delta > 0;
  const negative = comparison !== null && comparison.delta < 0;
  return <section className={'coach-card coach-' + coach.status} aria-label="Разбор прогресса" data-testid="coach-card">
    <div className="section-heading"><h2>Разбор прогресса</h2><span className="subtle-tag">{choose ? 'ОДНА МАШИНА' : coach.window + ' + ' + coach.window + ' БОЁВ'}</span></div>
    {choose ? <div className="coach-choose">
      <div><strong>Выберите машину для личного сравнения</strong><p>Результаты разной или неизвестной техники не смешиваются. Выберите определённый танк в списке выше.</p></div>
      {latestVehicle && latestVehicle !== 'unknown' && onSelectVehicle && <button type="button" className="coach-select-button" onClick={() => onSelectVehicle(latestVehicle)} aria-label="Разобрать последнюю машину">{'Разобрать ' + vehicleLabel(latestVehicle)}</button>}
    </div> : <>
      {!explain && <><div className="coach-scope"><strong>{coach.vehicle ? vehicleLabel(coach.vehicle) : 'Машина ещё не выбрана'}</strong><span>{coach.battles + ' сохранённых боёв'}</span></div>
      {comparison ? <>
        <div className="coach-verdict">
          <strong className={positive ? 'positive' : negative ? 'negative' : ''}>{positive ? 'Средний урон в этой выборке выше' : negative ? 'Средний урон в этой выборке ниже' : 'Средний урон почти не изменился'}</strong>
          <span className={positive ? 'positive' : negative ? 'negative' : 'muted'} data-testid="coach-delta">{delta(comparison.delta) + ' урона' + (comparison.delta_percent !== null ? ' (' + delta(comparison.delta_percent) + '%)' : '')}</span>
        </div>
        <div className="coach-comparison" role="table" aria-label="Сравнение урона двух периодов">
          <div className="coach-comparison-row coach-comparison-head" role="row"><span role="columnheader">Показатель</span><span role="columnheader">{'Предыдущие ' + coach.window}</span><span role="columnheader">{'Последние ' + coach.window}</span><span role="columnheader">Изменение</span></div>
          <div className="coach-comparison-row" role="row"><strong role="rowheader">Средний урон</strong><span role="cell">{number(comparison.previous_avg, 1)}</span><span role="cell">{number(comparison.current_avg, 1)}</span><span role="cell">{delta(comparison.delta)}</span></div>
          <div className="coach-comparison-row" role="row"><strong role="rowheader">Медиана урона</strong><span role="cell">{number(comparison.previous_median, 1)}</span><span role="cell">{number(comparison.current_median, 1)}</span><span role="cell">{delta(comparison.median_delta)}</span></div>
        </div>
        {comparison.delta * comparison.median_delta < 0 && <p className="coach-evidence coach-divergence">Среднее и медиана изменились в разные стороны. По одному среднему нельзя судить обо всей серии.</p>}
        <p className="coach-evidence">{'Два непересекающихся периода. Урон известен в ' + coach.coverage.previous_damage + '/' + coach.window + ' предыдущих и ' + coach.coverage.current_damage + '/' + coach.window + ' последних боёв.'}</p>
      </> : <div className="coach-wait" role="status">
        <strong>{coach.status === 'mixed_modes' ? 'В этих периодах разные типы боёв' : coach.status === 'incomplete' ? 'Для вывода не хватает значений урона' : coach.status === 'empty' ? 'История для сравнения пока пуста' : 'Набираем историю для сравнения'}</strong>
        {coach.status === 'mixed_modes' || coach.status === 'incomplete' ? <p>{coach.status === 'mixed_modes' ? 'Сравнение скрыто: разные известные типы боёв. Рекорды ниже относятся ко всей сохранённой истории машины.' : 'Сравнение появится, когда урон будет известен во всех боях двух периодов.'}</p>
          : <div className="coach-count"><span>Нужно ещё</span><strong data-testid="coach-remaining">{coach.remaining_battles}</strong><span>{'боёв на этой машине (два периода по ' + coach.window + ')'}</span></div>}
        <div className="coach-coverage"><span>{'Последний период: ' + coach.coverage.current_battles + '/' + coach.window + ' · урон известен в ' + coach.coverage.current_damage}</span><span>{'Предыдущий: ' + coach.coverage.previous_battles + '/' + coach.window + ' · урон известен в ' + coach.coverage.previous_damage}</span></div>
      </div>}
      <Records coach={coach} /></>}
      <div className="coach-foot"><p>По сохранённым боям на этой машине. Карты и условия боёв могут различаться.</p><button type="button" className="coach-explain-button" aria-expanded={explain} aria-controls="coach-explanation" onClick={() => setExplain(!explain)}>{explain ? 'Скрыть пояснение' : 'Как рассчитано'}</button></div>
      {explain && <div id="coach-explanation" className="coach-explanation">
        <p>{'Сравнение: два последовательных периода по ' + coach.window + ' боёв. Нужен известный урон во всех ' + coach.required_battles + ' результатах; пропуски не считаются нулём.'}</p>
        <p>При разных известных типах боёв сравнение скрывается. Неизвестный тип не гарантирует одинаковые условия.</p>
        <p>Среднее учитывает каждый результат; медиана — середина отсортированного ряда. Разница не доказывает изменение навыка.</p>
        <p>{'Рекорды: только сохранённые бои этой машины и полные серии по ' + coach.window + ' боёв. Первая серия и равенство максимуму не являются новым рекордом.'}</p>
        <p>Опыт может учитывать бонусы и не используется в выводах. Порядок определяется временем получения результата.</p>
      </div>}
    </>}
  </section>;
}
