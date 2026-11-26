import { useEffect, useRef, useState } from 'react';
import { Snapshot } from './contracts';
import { vehicleLabel, vehicleLabelFor } from './vehicleLabel';
const PAGE_SIZE = 5;

export function VehiclePicker({ vehicles, selected, disabled, onSelect }: {
  vehicles: Snapshot['vehicles']; selected: string; disabled: boolean; onSelect: (vehicle: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(vehicles.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!wrap.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', outside);
    return () => document.removeEventListener('mousedown', outside);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  const choose = (name: string) => { setOpen(false); onSelect(name); };
  return <div className="vehicle-picker" ref={wrap} onKeyDown={event => {
    if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false);
      wrap.current?.querySelector<HTMLButtonElement>('.picker-trigger')?.focus();
      return;
    }
    if (open && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      const options = Array.from(wrap.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') || []);
      if (!options.length) return;
      event.preventDefault();
      const currentIndex = options.indexOf(document.activeElement as HTMLButtonElement);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
        : event.key === 'ArrowDown' ? (currentIndex + 1) % options.length : (currentIndex + options.length - 1) % options.length;
      options[index].focus();
    }
  }}>
    <span className="field-label">ТЕХНИКА</span>
    <button className="picker-trigger" type="button" aria-haspopup="listbox" aria-expanded={open}
      aria-label="Выбрать танк" disabled={disabled} onClick={() => { setPage(0); setOpen(!open); }}>
      <span className="picker-label">{selected ? vehicleLabelFor(selected, vehicles) : 'Вся техника'}</span><span className="chevron">v</span>
    </button>
    {open && <div className="picker-menu" role="listbox" aria-label="Техника">
      <button type="button" role="option" aria-selected={!selected} onClick={() => choose('')}>Вся техника</button>
      {vehicles.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(vehicle => <button type="button" role="option" aria-selected={selected === vehicle.name}
        key={vehicle.name} title={vehicleLabel(vehicle.name, vehicle.label)} onClick={() => choose(vehicle.name)}><span className="picker-label">{vehicleLabel(vehicle.name, vehicle.label)}</span><span className="muted">{vehicle.battles}</span></button>)}
      {pages > 1 && <div className="page-controls picker-pages">
        <button type="button" aria-label="Предыдущая страница техники" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</button>
        <span>{String(current + 1) + ' / ' + pages}</span>
        <button type="button" aria-label="Следующая страница техники" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Далее</button>
      </div>}
    </div>}
  </div>;
}
