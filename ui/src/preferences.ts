import type { DashboardModule, PanelSection, Theme } from './contracts';

export const sectionLabels: Record<PanelSection, string> = {
  progress: 'Прогресс', dynamics: 'Динамика и цели', history: 'История боёв', summary: 'Сводка',
  analytics: 'Аналитика', reports: 'Отчёты', settings: 'Настройки'
};
export const moduleLabels: Record<DashboardModule, string> = {
  metrics: 'Основные показатели', coach: 'Разбор прогресса', vehicle: 'Карточка техники', chart: 'Динамика урона',
  goals: 'Личная цель', activity: 'Активность', economy: 'Экономика', reports: 'Отчёт'
};
export const themeLabels: Record<Theme, string> = { hangar: 'Ангар', slate: 'Графит', light: 'Светлая' };
