import { Button } from './Button';
import { useState } from 'react';
import { Coach, GoalDefinition } from './contracts';
import { formatNumber, signed } from './format';

const observationLabels = { damage_average: 'Средний урон', damage_median: 'Медиана урона', damage_spread: 'Разброс урона (IQR)', net_credits: 'Итог кредитов за бой' };

export function CoachEvidence({ coach, onSaveGoal, busy = false }: { coach: Coach; onSaveGoal?: (goal: GoalDefinition) => void; busy?: boolean }) {
  const [confirm, setConfirm] = useState(false);
  const consistency = coach.consistency;
  const suggestion = coach.goal_suggestions?.[0];
  return <div className="coach-evidence-view" aria-label="Наблюдения по результатам">
    {coach.observations && coach.observations.length > 0 && <div className="observation-grid">
      {coach.observations.map(item => <article className="observation-card" key={item.kind}><span>{observationLabels[item.kind]}</span><strong>{formatNumber(item.current, 1)}</strong>
        <p>{item.previous === null ? 'Текущее окно' : 'Ранее ' + formatNumber(item.previous, 1) + ' · разница ' + signed(item.delta)}</p>
        <small>{item.samples + '/' + item.window + ' известных боёв' + (item.previous === null ? '' : ' · ранее ' + item.previous_samples + '/' + item.window)}</small></article>)}
    </div>}
    {consistency && <section className="consistency-card" aria-label="Разброс урона">
      <div className="section-heading"><h3>Насколько различаются результаты</h3><span className="small muted">{consistency.samples + '/' + consistency.required + ' известных боёв'}</span></div>
      {consistency.status === 'ready' ? <><div className="consistency-values"><div><span>Средние 50% результатов</span><strong>{formatNumber(consistency.lower_quartile, 1) + ' — ' + formatNumber(consistency.upper_quartile, 1)}</strong></div>
        <div><span>Размах этой половины, IQR</span><strong>{formatNumber(consistency.interquartile_range, 1)}</strong></div><div><span>Медианное отклонение, MAD</span><strong>{formatNumber(consistency.median_absolute_deviation, 1)}</strong></div></div>
        <p>Медиана урона: {formatNumber(consistency.median, 1)}. IQR описывает середину распределения; MAD — типичное расстояние от медианы. Меньший разброс не означает лучший результат.</p></>
        : <p>{consistency.status === 'not_comparable' ? 'Для этой выборки разброс не интерпретируется: техника или условия сравнения не определены достаточно надёжно.' : 'Для разброса нужно полное окно известного урона. Пропуски не заменяются нулями.'}</p>}
    </section>}
    {(!coach.observations || coach.observations.length === 0) && <p className="coach-observation-empty">Новых числовых наблюдений пока нет. Недостаток данных — ограничение выборки, а не оценка вашей игры.</p>}
    {suggestion && <section className="goal-suggestion" aria-label="Ориентир личной цели"><div><span className="eyebrow">ОРИЕНТИР, КОТОРЫЙ МОЖНО ИЗМЕНИТЬ</span><h3>{formatNumber(suggestion.target_avg_damage) + ' среднего урона за ' + suggestion.window + ' боёв'}</h3>
      <p>{'Основа: ' + formatNumber(suggestion.baseline_avg_damage, 1) + ' в ' + suggestion.samples + ' известных боях. Прибавка 5%, округление вверх до 50. Это простая эвристика, не прогноз успеха.'}</p></div>
      {onSaveGoal ? !confirm ? <Button type="button" disabled={busy} onClick={() => setConfirm(true)}>Рассмотреть цель</Button>
        : <div className="goal-confirmation" role="group" aria-label="Подтверждение предлагаемой цели"><p>Сохранить этот ориентир для выбранной машины? Цель с таким же окном будет заменена.</p><div>
          <Button type="button" className="primary-button" disabled={busy} onClick={() => { onSaveGoal({ vehicle: suggestion.vehicle, window: suggestion.window, target_avg_damage: suggestion.target_avg_damage }); setConfirm(false); }}>Сохранить эту цель</Button>
          <Button type="button" disabled={busy} onClick={() => setConfirm(false)}>Отмена</Button></div></div>
        : <p className="muted small">Этот источник доступен только для чтения. Цель не сохранена.</p>}
    </section>}
    <p className="chart-footnote">Наблюдения описывают полученные значения. Состав боёв и условия не контролируются; причинные выводы о навыке не делаются.</p>
  </div>;
}
