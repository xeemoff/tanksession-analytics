import { Button } from './Button';
import { useState } from 'react';
import { dashboardModules, DashboardModule, GoalDefinition, PanelSection, Preferences, Snapshot, Theme, UserCommand } from './contracts';
import { formatNumber } from './format';
import { VehiclePicker } from './VehiclePicker';
import { vehicleLabel, vehicleLabelFor } from './vehicleLabel';
import { moduleLabels, sectionLabels, themeLabels } from './preferences';

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
  const [page, setPage] = useState<'layout' | 'theme' | 'modules'>('layout');
  const [theme, setTheme] = useState<Theme>(initial.theme || 'hangar');
  const [motion, setMotion] = useState<'system' | 'reduced'>(initial.motion || 'system');
  const [modules, setModules] = useState<DashboardModule[]>(initial.modules || ['metrics', 'coach']);
  const advanced = 'theme' in initial || !!snapshot.analytics;
  const toggle = (key: DashboardModule) => setModules(current => current.includes(key) ? current.filter(item => item !== key)
    : key === 'metrics' ? [key, ...current] : [...current, key]);
  const move = (key: DashboardModule, step: number) => {
    const panels: DashboardModule[] = modules.filter(item => item !== 'metrics');
    const index = panels.indexOf(key);
    const next = index + step;
    if (index < 0 || next < 0 || next >= panels.length) return;
    [panels[index], panels[next]] = [panels[next], panels[index]];
    setModules(modules.includes('metrics') ? ['metrics', ...panels] : panels);
  };
  const orderedModules = [...modules, ...dashboardModules.filter(key => !modules.includes(key))];
  return <div className="settings-card">
    <div className="section-heading"><h2>Вид и стартовые фильтры</h2><span className="subtle-tag">ТЕКУЩИЙ АККАУНТ</span></div>
    {advanced && <div className="insight-switch appearance-pages" role="group" aria-label="Настройка вида">
      {([['layout', 'Вид и фильтры'], ['theme', 'Темы и движение'], ['modules', 'Модули панели']] as const).map(([key, label]) => <Button type="button" key={key} className={page === key ? 'active' : ''} aria-pressed={page === key} onClick={() => setPage(key)}>{label}</Button>)}
    </div>}
    {page === 'layout' ? <><div className="settings-two-column">
      <div className="settings-field"><span className="field-label">ПЛОТНОСТЬ</span><div className="insight-switch">
        <Button type="button" className={density === 'normal' ? 'active' : ''} aria-pressed={density === 'normal'} disabled={busy} onClick={() => setDensity('normal')}>Обычная</Button>
        <Button type="button" className={density === 'compact' ? 'active' : ''} aria-pressed={density === 'compact'} disabled={busy} onClick={() => setDensity('compact')}>Компактная</Button>
      </div></div>
      <div className="settings-field"><span className="field-label">КОНТРАСТ</span><div className="insight-switch">
        <Button type="button" className={contrast === 'standard' ? 'active' : ''} aria-pressed={contrast === 'standard'} disabled={busy} onClick={() => setContrast('standard')}>Стандартный</Button>
        <Button type="button" className={contrast === 'high' ? 'active' : ''} aria-pressed={contrast === 'high'} disabled={busy} onClick={() => setContrast('high')}>Повышенный</Button>
      </div></div>
    </div>
    <span className="field-label">РАЗДЕЛ ПРИ ОТКРЫТИИ</span>
    <div className="insight-switch startup-tabs" role="group" aria-label="Стартовый раздел">
      {(Object.keys(sectionLabels) as PanelSection[]).filter(key => advanced || (key !== 'analytics' && key !== 'reports')).map(key => <Button type="button" key={key} disabled={busy} className={key === tab ? 'active' : ''} aria-pressed={key === tab} onClick={() => setTab(key)}>{sectionLabels[key]}</Button>)}
    </div>
    <p className="settings-description">{'Будут сохранены фильтры сверху: ' + (snapshot.selection.vehicle ? vehicleLabelFor(snapshot.selection.vehicle, snapshot.vehicles) : 'вся техника') + ', окно ' + snapshot.selection.window + ' боёв.'}</p></>
      : page === 'theme' ? <><div className="theme-options" role="group" aria-label="Цветовая тема">{(Object.keys(themeLabels) as Theme[]).map(key => <Button type="button" key={key} disabled={busy} className={'theme-choice theme-choice-' + key + (theme === key ? ' selected' : '')} aria-pressed={theme === key} onClick={() => setTheme(key)}><span className="theme-swatches" aria-hidden="true"><span /><span /><span /></span><strong>{themeLabels[key]}</strong><span>{key === 'hangar' ? 'Оливковая и тёплая' : key === 'slate' ? 'Холодная и нейтральная' : 'Светлая с тёмным текстом'}</span></Button>)}</div>
        <span className="field-label motion-label">ДВИЖЕНИЕ</span><div className="insight-switch" role="group" aria-label="Анимация интерфейса"><Button type="button" disabled={busy} className={motion === 'system' ? 'active' : ''} aria-pressed={motion === 'system'} onClick={() => setMotion('system')}>Как в системе</Button><Button type="button" disabled={busy} className={motion === 'reduced' ? 'active' : ''} aria-pressed={motion === 'reduced'} onClick={() => setMotion('reduced')}>Уменьшить движение</Button></div><p className="settings-description">Системное ограничение движения учитывается всегда. Повышенный контраст доступен во вкладке «Вид и фильтры».</p></>
        : <><p className="settings-description">Выберите содержимое «Прогресса». Основные показатели закреплены сверху, остальные модули открываются переключателями в заданном порядке.</p>
          <div className="module-settings" role="group" aria-label="Состав личной панели">{orderedModules.map(key => {
            const enabled = modules.includes(key);
            const panels: DashboardModule[] = modules.filter(item => item !== 'metrics');
            const index = panels.indexOf(key);
            return <div className={'module-setting' + (enabled ? ' enabled' : '')} key={key}><Button type="button" className="module-toggle" aria-pressed={enabled} aria-label={'Модуль ' + moduleLabels[key]} disabled={busy || (enabled && modules.length === 1)} onClick={() => toggle(key)}><span aria-hidden="true">{enabled ? '✓' : '+'}</span><strong>{moduleLabels[key]}</strong><small>{enabled ? 'Включён' : 'Выключен'}</small></Button>
              {key !== 'metrics' && enabled && <div className="module-order"><Button type="button" disabled={busy || index === 0} aria-label={'Выше: ' + moduleLabels[key]} onClick={() => move(key, -1)}>↑</Button><Button type="button" disabled={busy || index === panels.length - 1} aria-label={'Ниже: ' + moduleLabels[key]} onClick={() => move(key, 1)}>↓</Button></div>}</div>;
          })}</div><p className="chart-footnote">Оставьте хотя бы один модуль. Остальные разделы статистики доступны независимо от этой настройки.</p></>}
    <Button type="button" className="primary-button" disabled={busy} onClick={() => onCommand({ action: 'save_preferences', preferences: {
      vehicle: snapshot.selection.vehicle, window: snapshot.selection.window, tab, density, contrast,
      ...(advanced ? { theme, motion, modules } : {})
    } })}>Сохранить вид и фильтры</Button>
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
  const label = (goal: GoalDefinition) => vehicleLabel(goal.vehicle,
    goal.vehicle_label || snapshot.vehicles.find(item => item.name === goal.vehicle)?.label);
  return <section className="settings-card" aria-label="Настройка целей">
    <div className="section-heading"><h2>{editor ? 'Задать личную цель' : 'Личные цели'}</h2>
      <Button type="button" disabled={busy} onClick={() => setEditor(!editor)}>{editor ? 'К списку целей' : 'Добавить цель'}</Button></div>
    {editor ? <>
      <div className="goal-editor-row"><VehiclePicker vehicles={snapshot.vehicles.filter(v => v.name !== 'unknown')} selected={vehicle} disabled={busy} onSelect={setVehicle} />
        <label className="settings-input"><span>Средний урон</span><input type="text" inputMode="numeric" maxLength={5} value={target} className={busy ? 'is-disabled' : ''} disabled={busy} aria-label="Целевой средний урон" onChange={event => setTarget(event.target.value)} /></label>
        <label className="settings-input"><span>Боёв в серии</span><input type="text" inputMode="numeric" maxLength={4} value={windowSize} className={busy ? 'is-disabled' : ''} disabled={busy} aria-label="Боёв для цели" onChange={event => setWindowSize(event.target.value)} /></label>
      </div>
      <p className="settings-description">Выберите одну машину. Урон: от 1 до 50 000; серия: от 10 до 1 000 боёв. Сохранение заменит цель этой машины с таким же размером серии.</p>
      <Button type="button" className="primary-button" disabled={busy || !valid} onClick={() => onCommand({ action: 'save_goal', goal: { vehicle, window: windowValue, target_avg_damage: targetValue } })}>Сохранить цель</Button>
      <p className="trend-note">Цель применяется только к вашему текущему аккаунту. Пропуски не превращаются в нули; полнота серии видна во вкладке «Динамика и цели».</p>
    </> : <>
      {goals.length === 0 ? <div className="chart-empty"><strong>Цели пока не заданы</strong><span>Добавьте цель по среднему урону для выбранной машины.</span></div> : <div className="editable-goals">
        {goals.slice(current * 3, (current + 1) * 3).map(goal => <div className="editable-goal" key={goal.vehicle + ':' + goal.window}>
          <div><strong>{label(goal)}</strong><span>{formatNumber(goal.target_avg_damage) + ' урона · ' + goal.window + ' боёв'}</span></div>
          <Button type="button" disabled={busy} aria-label={'Изменить цель ' + label(goal) + ' ' + goal.window} onClick={() => edit(goal)}>Изменить</Button>
          <Button type="button" disabled={busy} aria-label={'Удалить цель ' + label(goal) + ' ' + goal.window} onClick={() => onCommand({ action: 'delete_goal', goal: { vehicle: goal.vehicle, window: goal.window } })}>Удалить</Button>
        </div>)}
      </div>}
      <div className="page-controls"><Button type="button" disabled={busy || current === 0} aria-label="Предыдущая страница целей" onClick={() => setPage(current - 1)}>Назад</Button><span>{String(current + 1) + ' / ' + pages}</span><Button type="button" disabled={busy || current + 1 >= pages} aria-label="Следующая страница целей" onClick={() => setPage(current + 1)}>Далее</Button></div>
    </>}
  </section>;
}

export function SettingsView({ snapshot, busy, onCommand }: { snapshot: Snapshot; busy: boolean; onCommand: (command: UserCommand) => void }) {
  const [tab, setTab] = useState<'appearance' | 'goals' | 'export'>('appearance');
  if (!snapshot.workspace?.can_edit) return <div className="chart-empty"><strong>Этот источник доступен только для чтения</strong><span>Настройки и команды появятся при подключении поддерживаемой версии мода.</span></div>;
  return <section className="workspace-view" aria-label="Настройки TankSession">
    <div className="insight-switch" role="group" aria-label="Раздел настроек">
      <Button type="button" className={tab === 'appearance' ? 'active' : ''} aria-pressed={tab === 'appearance'} disabled={busy} onClick={() => setTab('appearance')}>Вид и фильтры</Button>
      <Button type="button" className={tab === 'goals' ? 'active' : ''} aria-pressed={tab === 'goals'} disabled={busy} onClick={() => setTab('goals')}>Цели</Button>
      <Button type="button" className={tab === 'export' ? 'active' : ''} aria-pressed={tab === 'export'} disabled={busy} onClick={() => setTab('export')}>Экспорт CSV</Button>
    </div>
    {tab === 'appearance' ? <AppearanceForm snapshot={snapshot} busy={busy} onCommand={onCommand} /> : tab === 'goals' ? <GoalEditor snapshot={snapshot} busy={busy} onCommand={onCommand} /> : <div className="settings-card">
      <div className="section-heading"><h2>Экспорт сохранённой истории</h2><span className="subtle-tag">CSV · UTF-8</span></div>
      <p className="settings-description">{'Выборка: ' + (snapshot.selection.vehicle ? vehicleLabelFor(snapshot.selection.vehicle, snapshot.vehicles) : 'вся техника') + ' · ' + snapshot.summary.battles + ' записей текущего аккаунта.'}</p>
      <p className="settings-description">Будет сохранена вся выбранная история, включая старые страницы. Окно сравнения 10/30/100 не ограничивает экспорт.</p>
      <Button type="button" className="primary-button" disabled={busy || snapshot.summary.battles === 0} onClick={() => onCommand({ action: 'export_csv' })}>Сохранить CSV</Button>
      <p className="trend-note">{snapshot.source === 'demo' ? 'Демонстрационный CSV создаётся во временной папке локального сервера.' : 'Файл создаётся в подпапке exports рядом с журналом боёв. В игре: mods/configs/tanksession_analytics/exports.'} Идентификаторы аккаунта и арены в экспорт не включаются. Существующая история остаётся на месте.</p>
      {snapshot.source === 'demo' && <p className="settings-description">В демонстрации экспортируются только вымышленные данные.</p>}
    </div>}
  </section>;
}
