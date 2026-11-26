// Display-only labels. Selectors remain unchanged in requests and saved goals.
export function vehicleLabel(key: string, label?: string): string {
  const value = label || key;
  const name = value.startsWith('name:') ? value.slice(5) : value;
  if (name === 'ussr:R04_T-34') return 'Т-34';
  if (name === 'unknown') return 'Неизвестная техника';
  const type = /^type:(\d+)$/.exec(name);
  return type ? 'Техника #' + type[1] : name;
}

export function vehicleLabelFor(key: string, vehicles: ReadonlyArray<{ name: string; label?: string }>): string {
  return vehicleLabel(key, vehicles.find(item => item.name === key)?.label);
}
