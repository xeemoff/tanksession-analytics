// Display-only aliases. Raw keys remain unchanged for storage and filtering.
export function vehicleLabel(key: string): string {
  if (key === 'ussr:R04_T-34') return 'Т-34';
  if (key === 'unknown') return 'Неизвестная техника';
  return key;
}
