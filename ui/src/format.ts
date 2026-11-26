export function formatNumber(value: number | null, digits = 0): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const fixed = value.toFixed(digits).split('.');
  return fixed[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (fixed.length > 1 ? ',' + fixed[1] : '');
}
export function signed(value: number | null, suffix = ''): string {
  if (value === null) return '—';
  return (value > 0 ? '+' : '') + formatNumber(value, 1) + suffix;
}
export function timeLabel(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const pad = (value: number) => value < 10 ? '0' + value : String(value);
  return pad(date.getDate()) + '.' + pad(date.getMonth() + 1) + ' · ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
}
export const outcomeLabel: Record<string, string> = { win: 'Победа', loss: 'Поражение', draw: 'Ничья', unknown: 'Неизвестно' };
