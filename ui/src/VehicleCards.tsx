import { Button } from './Button';
import { useState } from 'react';
import { Snapshot, VehicleClass, VehicleEntry, VehicleMetadata } from './contracts';
import { formatNumber } from './format';
import { vehicleLabel } from './vehicleLabel';

export const classLabels: Record<VehicleClass, string> = {
  lightTank: 'Лёгкий танк', mediumTank: 'Средний танк', heavyTank: 'Тяжёлый танк', 'AT-SPG': 'ПТ-САУ', SPG: 'САУ'
};
export const nationLabels: Record<string, string> = {
  ussr: 'СССР', germany: 'Германия', usa: 'США', china: 'Китай', france: 'Франция', uk: 'Великобритания',
  japan: 'Япония', czech: 'Чехословакия', sweden: 'Швеция', poland: 'Польша', italy: 'Италия', intunion: 'Интернациональная'
};
export function metadataLabel(value: VehicleMetadata): string {
  return [value.vehicle_tier ? value.vehicle_tier + ' уровень' : 'Уровень неизвестен',
    value.vehicle_class ? classLabels[value.vehicle_class] : 'Класс неизвестен',
    value.vehicle_nation ? nationLabels[value.vehicle_nation] || value.vehicle_nation : 'Нация неизвестна'].join(' · ');
}

/** Original class silhouettes. They deliberately do not depict a named vehicle. */
export function VehicleArt({ vehicleClass }: { vehicleClass?: VehicleClass | null }) {
  const cls = vehicleClass || 'unknown';
  const heavy = cls === 'heavyTank';
  const light = cls === 'lightTank';
  const artillery = cls === 'SPG';
  const destroyer = cls === 'AT-SPG';
  const wheels = light ? [65, 91, 117, 143, 169] : [51, 77, 103, 129, 155, 181];
  return <svg className={'vehicle-art vehicle-art-' + cls} viewBox="0 0 240 112" role="img"
    aria-label={vehicleClass ? 'Схематичная иллюстрация класса: ' + classLabels[vehicleClass] : 'Схематичная иллюстрация техники'}>
    <title>{'Иллюстрация класса, не изображение конкретной модели'}</title>
    <path className="vehicle-art-grid" d="M20 98H222 M30 18V103 M77 18V103 M124 18V103 M171 18V103 M218 18V103 M20 35H222 M20 65H222" />
    <path className="vehicle-art-track" d={light ? 'M60 73H174L185 87L173 100H61L49 87Z' : 'M43 70H190L207 85L191 102H43L29 87Z'} />
    {wheels.map(x => <circle key={x} className="vehicle-art-wheel" cx={x} cy="87" r={heavy ? 11 : 9} />)}
    <path className="vehicle-art-hull" d={light ? 'M57 70L80 59H157L179 72L171 80H63Z' : heavy ? 'M35 69L60 49H174L201 68L190 79H43Z' : 'M37 70L62 56H176L198 70L188 79H45Z'} />
    {destroyer ? <path className="vehicle-art-turret" d="M70 57L86 32H147L163 57Z M143 39H222V46H147Z" />
      : artillery ? <path className="vehicle-art-turret" d="M71 56V38H119L142 56Z M111 40L188 12L193 20L119 49Z" />
      : <path className="vehicle-art-turret" d={heavy ? 'M76 50L85 29H139L155 50Z M139 35H224V43H148Z' : light ? 'M89 59L97 42H128L143 59Z M128 46H193V52H137Z' : 'M80 56L91 34H139L156 56Z M138 40H215V47H147Z'} />}
    <path className="vehicle-art-detail" d="M58 71H178 M89 87H155" />
    {!vehicleClass && <text x="202" y="33" className="vehicle-art-unknown">?</text>}
  </svg>;
}

export function VehicleCard({ vehicle, selected = false, onSelect }: { vehicle: VehicleEntry; selected?: boolean; onSelect?: (key: string) => void }) {
  return <article className={'vehicle-card' + (selected ? ' vehicle-card-selected' : '')}>
    <div className="vehicle-card-heading"><span className="eyebrow">{vehicle.vehicle_tier ? 'УРОВЕНЬ ' + vehicle.vehicle_tier : 'УРОВЕНЬ НЕИЗВЕСТЕН'}</span>
      <span className="vehicle-class-tag">{vehicle.vehicle_class ? classLabels[vehicle.vehicle_class] : 'Класс неизвестен'}</span></div>
    <VehicleArt vehicleClass={vehicle.vehicle_class} />
    <div className="vehicle-card-name"><h3>{vehicleLabel(vehicle.name, vehicle.label)}</h3><span>{vehicle.vehicle_nation ? nationLabels[vehicle.vehicle_nation] || vehicle.vehicle_nation : 'Нация неизвестна'}</span></div>
    <div className="vehicle-card-footer"><span><strong>{formatNumber(vehicle.battles)}</strong> сохранённых боёв</span>
      {onSelect && <Button type="button" disabled={selected} onClick={() => onSelect(vehicle.name)} aria-label={'Выбрать ' + vehicleLabel(vehicle.name, vehicle.label)}>{selected ? 'Выбрано' : 'Выбрать'}</Button>}</div>
    <p className="vehicle-art-note">Схема класса, не модель машины. Характеристики — только из сохранённых данных.</p>
  </article>;
}

export function VehicleCollection({ snapshot, onSelect }: { snapshot: Snapshot; onSelect?: (key: string) => void }) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const needle = query.trim().toLocaleLowerCase();
  const vehicles = snapshot.vehicles.filter(item => (vehicleLabel(item.name, item.label) + ' ' + metadataLabel(item)).toLocaleLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(vehicles.length / 3));
  const current = Math.min(page, pages - 1);
  return <section className="vehicle-collection" aria-label="Карточки техники">
    <div className="section-heading"><div><h2>Техника в вашей истории</h2><p className="section-description">{vehicles.length + ' машин · характеристики без догадок по названию'}</p></div>
      <label className="search-field"><span className="sr-only">Найти карточку техники</span><input type="search" value={query} maxLength={64} placeholder="Название, класс, нация" onChange={event => { setQuery(event.target.value); setPage(0); }} /></label></div>
    <div className="vehicle-card-grid">{vehicles.slice(current * 3, current * 3 + 3).map(vehicle => <VehicleCard key={vehicle.name} vehicle={vehicle} selected={snapshot.selection.vehicle === vehicle.name} onSelect={onSelect} />)}</div>
    {vehicles.length === 0 && <div className="chart-empty"><strong>Техника не найдена</strong><span>Попробуйте другое название или очистите поиск.</span></div>}
    <div className="page-controls"><Button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Предыдущие карточки техники">Назад</Button><span>{String(current + 1) + ' / ' + pages}</span><Button type="button" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)} aria-label="Следующие карточки техники">Далее</Button></div>
  </section>;
}
