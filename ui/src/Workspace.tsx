import { useState } from 'react';
import { GoalDefinition, PanelSection, Preferences, Snapshot, UserCommand } from './contracts';
import { formatNumber } from './format';
import { VehiclePicker } from './VehiclePicker';
import { vehicleLabel } from './vehicleLabel';

const sectionLabels: Record<PanelSection, string> = { progress: 'Прогресс', dynamics: 'Динамика и цели', history: 'История боёв', summary: 'Сводка', settings: 'Настройки' };
const operationLabels: Record<string, string> = {
  preferences_saved: 'Вид и фильтры сохранены для текущего аккаунта.',
  goal_saved: 'Цель сохранена.', goal_deleted: 'Цель удалена.',
  csv_exported: 'CSV сохранён.', write_failed: 'Не удалось сохранить изменения. Проверьте доступ к папке мода и повторите.',
  read_failed: 'Не удалось прочитать настройки. Проверьте локальный файл настроек.',
  invalid_goal: 'Проверьте технику, число боёв и целевой урон.', no_data: 'В выбранной истории нет записей для экспорта.',
  export_too_large: 'История слишком велика для экспорта из окна. Используйте локальную панель.',
  too_many_profiles: 'Достигнут предел локальных профилей настроек.'
};

export function OperationNotice({ snapshot }: { snapshot: Snapshot }) {
  const op = snapshot.workspace?.operation;
  if (!op) return null;
  return <div className={'operation-notice ' + (op.status === 'error' ? 'operation-error' : '')} role={op.status === 'error' ? 'alert' : 'status'} data-testid="operation-result">
    <span>{operationLabels[op.code] || (op.status === 'error' ? 'Действие не выполнено. Проверьте журнал TankSession.' : 'Действие выполнено.')}</span>
    {op.status === 'exported' && <span>{'Строк: ' + (op.rows ?? 0) + '. ' + (op.filename || '') + '. ' +
      (snapshot.source === 'demo' ? 'Демонстрационный CSV во временной папке локального сервера.' : 'CSV в подпапке exports рядом с журналом боёв. В игре: mods/configs/tanksession_analytics/exports.')}</span>}
  </div>;
}

function AppearanceForm({ snapshot, busy, onCommand }: { snapshot: Snapshot; busy: boolean; onCommand: (command: UserCommand) => void }) {
  const initial = snapshot.workspace!.preferences;
  const [density, setDensity] = useState<Preferences['density']>(initial.density);
  const [contrast, setContrast] = useState<Preferences['contrast']>(initial.contrast);
  const [tab, setTab] = useState<PanelSection>(initial.tab);
  return <div className="settings-card">
    <div className="section-heading"><h2>Вид и стартовые фильтры</h2><span className="subtle-tag">ТЕКУЩИЙ АККАУНТ</span></div>
    <div className="settings-two-column">
      <div className="settings-field"><span className="field-label">ПЛОТНОСТЬ</span><div className="insight-switch">
        <button type="button" className={density === 'normal' ? 'active' : ''} aria-pressed={density === 'normal'} disabled={busy} onClick={() => setDensity('normal')}>Обычная</button>
        <button type="button" className={density === 'compact' ? 'active' : ''} aria-pressed={density === 'compact'} disabled={busy} onClick={() => setDensity('compact')}>Компактная</button>
      </div></div>
      <div className="settings-field"><span className="field-label">КОНТРАСТ</span><div className="insight-switch">
        <button type="button" className={contrast === 'standard' ? 'active' : ''} aria-pressed={contrast === 'standard'} disabled={busy} onClick={() => setContrast('standard')}>Стандартный</button>
        <button type="button" className={contrast === 'high' ? 'active' : ''} aria-pressed={contrast === 'high'} disabled={busy} onClick={() => setContrast('high')}>Повышенный</button>
      </div></div>
    </div>
    <span className="field-label">РАЗДЕЛ ПРИ ОТКРЫТИИ</span>
    <div className="insight-switch startup-tabs" role="group" aria-label="Стартовый раздел">
      {(Object.keys(sectionLabels) as PanelSection[]).map(key => <button type="button" key={key} disabled={busy} className={key === tab ? 'active' : ''} aria-pressed={key === tab} onClick={() => setTab(key)}>{sectionLabels[key]}</button>)}
    </div>
    <p className="settings-description">{'Будут сохранены фильтры сверху: ' + (snapshot.selection.vehicle ? vehicleLabel(snapshot.selection.vehicle) : 'вся техника') + ', окно ' + snapshot.selection.window + ' боёв.'}</p>
    <button type="button" className="primary-button" disabled={busy} onClick={() => onCommand({ action: 'save_preferences', preferences: {
      vehicle: snapshot.selection.vehicle, window: snapshot.selection.window, tab, density, contrast
    } })}>Сохранить вид и фильтры</button>
    <p className="trend-note">Настройки применяются после сохранения и восстанавливаются при следующем открытии окна. Для другого аккаунта используется отдельный профиль.</p>
  </div>;
}

function GoalEditor({ snapshot, busy, onCommand }: { snapshot: Snapshot; busy: boolean; onCommand: (command: UserCommand) => void }) {
  const goals = snapshot.workspace!.goals;
  const firstVehicle = snapshot.selection.vehicle || snapshot.vehicles.find(item => item.name !== 'unknown')?.name || '';
  const [vehicle, setVehicle] = useState(firstVehicle);
  const [target, setTarget] = useState('1000');
  const [windowSize, setWindowSize] = useState('10');
  const [page, setPage] = useState(0);
  const [editor, setEditor] = useState(goals.length === 0);
  const pages = Math.max(1, Math.ceil(goals.length / 3));
  const current = Math.min(page, pages - 1);
  const selected = vehicle && vehicle !== 'unknown';
  const targetValue = /^\d{1,5}$/.test(target) ? Number(target) : 0;
  const windowValue = /^\d{1,4}$/.test(windowSize) ? Number(windowSize) : 0;
  const valid = !!selected && targetValue >= 1 && targetValue <= 50000 && windowValue >= 10 && windowValue <= 1000;
  const edit = (goal: GoalDefinition) => { setVehicle(goal.vehicle); setTarget(String(goal.target_avg_damage)); setWindowSize(String(goal.window)); setEditor(true); };
  return <section className="settings-card" aria-label="Настройка целей">
    <div className="section-heading"><h2>{editor ? 'Задать личную цель' : 'Личные цели'}</h2>
      <button type="button" disabled={busy} onClick={() => setEditor(!editor)}>{editor ? 'К списку целей' : 'Добавить цель'}</button></div>
    {editor ? <>
      <div className="goal-editor-row"><VehiclePicker vehicles={snapshot.vehicles.filter(v => v.name !== 'unknown')} selected={vehicle} disabled={busy} onSelect={setVehicle} />
        <label className="settings-input"><span>Средний урон</span><input type="text" inputMode="numeric" maxLength={5} value={target} disabled={busy} aria-label="Целевой средний урон" onChange={event => setTarget(event.target.value)} /></label>
        <label className="settings-input"><span>Боёв в серии</span><input type="text" inputMode="numeric" maxLength={4} value={windowSize} disabled={busy} aria-label="Боёв для цели" onChange={event => setWindowSize(event.target.value)} /></label>
      </div>
      <p className="settings-description">Выберите одну машину. Урон: от 1 до 50 000; серия: от 10 до 1 000 боёв. Сохранение заменит цель этой машины с таким же размером серии.</p>
      <button type="button" className="primary-button" disabled={busy || !valid} onClick={() => onCommand({ action: 'save_goal', goal: { vehicle, window: windowValue, target_avg_damage: targetValue } })}>Сохранить цель</button>
      <p className="trend-note">Цель применяется только к вашему текущему аккаунту. Пропуски не превращаются в нули; полнота серии видна во вкладке «Динамика и цели».</p>
    </> : <>
      {goals.length === 0 ? <div className="chart-empty"><strong>Цели пока не заданы</strong><span>Добавьте цель по среднему урону для выбранной машины.</span></div> : <div className="editable-goals">
        {goals.slice(current * 3, (current + 1) * 3).map(goal => <div className="editable-goal" key={goal.vehicle + ':' + goal.window}>
          <div><strong>{vehicleLabel(goal.vehicle)}</strong><span>{formatNumber(goal.target_avg_damage) + ' урона · ' + goal.window + ' боёв'}</span></div>
          <button type="button" disabled={busy} aria-label={'Изменить цель ' + vehicleLabel(goal.vehicle) + ' ' + goal.window} onClick={() => edit(goal)}>Изменить</button>
          <button type="button" disabled={busy} aria-label={'Удалить цель ' + vehicleLabel(goal.vehicle) + ' ' + goal.window} onClick={() => onCommand({ action: 'delete_goal', goal: { vehicle: goal.vehicle, window: goal.window } })}>Удалить</button>
        </div>)}
      </div>}
      <div className="page-controls"><button type="button" disabled={busy || current === 0} aria-label="Предыдущая страница целей" onClick={() => setPage(current - 1)}>Назад</button><span>{current + 1} / {pages}</span><button type="button" disabled={busy || current + 1 >= pages} aria-label="Следующая страница целей" onClick={() => setPage(current + 1)}>Далее</button></div>
    </>}
  </section>;
}

export function SettingsView({ snapshot, busy, onCommand }: { snapshot: Snapshot; busy: boolean; onCommand: (command: UserCommand) => void }) {
  const [tab, setTab] = useState<'appearance' | 'goals' | 'export'>('appearance');
  if (!snapshot.workspace?.can_edit) return <div className="chart-empty"><strong>Этот источник доступен только для чтения</strong><span>Настройки и команды появятся при подключении поддерживаемой версии мода.</span></div>;
  return <section className="workspace-view" aria-label="Настройки TankSession">
    <div className="insight-switch" role="group" aria-label="Раздел настроек">
      <button type="button" className={tab === 'appearance' ? 'active' : ''} aria-pressed={tab === 'appearance'} disabled={busy} onClick={() => setTab('appearance')}>Вид и фильтры</button>
      <button type="button" className={tab === 'goals' ? 'active' : ''} aria-pressed={tab === 'goals'} disabled={busy} onClick={() => setTab('goals')}>Цели</button>
      <button type="button" className={tab === 'export' ? 'active' : ''} aria-pressed={tab === 'export'} disabled={busy} onClick={() => setTab('export')}>Экспорт CSV</button>
    </div>
    {tab === 'appearance' ? <AppearanceForm snapshot={snapshot} busy={busy} onCommand={onCommand} /> : tab === 'goals' ? <GoalEditor snapshot={snapshot} busy={busy} onCommand={onCommand} /> : <div className="settings-card">
      <div className="section-heading"><h2>Экспорт сохранённой истории</h2><span className="subtle-tag">CSV · UTF-8</span></div>
      <p className="settings-description">{'Выборка: ' + (snapshot.selection.vehicle ? vehicleLabel(snapshot.selection.vehicle) : 'вся техника') + ' · ' + snapshot.summary.battles + ' записей текущего аккаунта.'}</p>
      <p className="settings-description">Будет сохранена вся выбранная история, включая старые страницы. Окно сравнения 10/30/100 не ограничивает экспорт.</p>
      <button type="button" className="primary-button" disabled={busy || snapshot.summary.battles === 0} onClick={() => onCommand({ action: 'export_csv' })}>Сохранить CSV</button>
      <p className="trend-note">{snapshot.source === 'demo' ? 'Демонстрационный CSV создаётся во временной папке локального сервера.' : 'Файл создаётся в подпапке exports рядом с журналом боёв. В игре: mods/configs/tanksession_analytics/exports.'} Идентификаторы аккаунта и арены в экспорт не включаются. Существующая история остаётся на месте.</p>
      {snapshot.source === 'demo' && <p className="settings-description">В демонстрации экспортируются только вымышленные данные.</p>}
    </div>}
  </section>;
}
