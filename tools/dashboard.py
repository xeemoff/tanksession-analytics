#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, local dashboard and CSV export for own post-battle history.

Python 3 standard library only. The dashboard never connects to Lesta or
interacts with the game: it reads a JSONL journal produced by the adapter.
"""
import argparse
import csv
import html
import json
import io
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from string import Template
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.storage import BattleStore
from tanksession_analytics.goals import evaluate_goals, validate_goals
from tanksession_analytics.core import summarize, by_day, _non_negative_int
from tanksession_analytics.analytics import (record_date, select_records,
    vehicle_table, window_comparison, rolling_damage, safe_window, valid_date)


CSV_FIELDS = ('arena_id', 'account_id', 'timestamp', 'date', 'vehicle', 'mode',
              'outcome', 'damage', 'assistance_radio', 'assistance_track', 'xp')


class CachedJournal:
    """Reload only when journal identity/size/mtime changes (single-process server)."""
    def __init__(self, path):
        self.path = path
        self.signature = object()
        self.data = []

    def records(self):
        try:
            stat = os.stat(self.path)
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except FileNotFoundError:
            signature = None
        if signature != self.signature:
            self.data = BattleStore(self.path).records if signature else []
            self.signature = signature
        return self.data


def load_goals(path):
    if not path:
        return []
    if os.path.getsize(path) > 8192:
        raise ValueError('Goals configuration is too large')
    with open(path, 'r', encoding='utf-8') as stream:
        return validate_goals(json.load(stream))


def escape(value):
    return html.escape(str(value), quote=True)


def fmt(value, suffix=''):
    if value is None:
        return '—'
    if isinstance(value, float):
        value = ('%.1f' % value).replace('.0', '')
    return '%s%s' % (value, suffix)


def stats_card(label, value, note=''):
    return ('<div class="stat"><span>%s</span><strong>%s</strong><small>%s</small></div>'
            % (escape(label), escape(value), escape(note)))


def daily_chart(records):
    entries = sorted(by_day(records).items())[-12:]
    if not entries:
        return '<p class="hint">Данных за выбранный период пока нет.</p>'
    height, margin, step, bar_width = 236, 45, 68, 42
    width = max(780, margin + (len(entries) - 1) * step + 90)
    vals = [row['avg_damage'] for day, row in entries if row['avg_damage'] is not None]
    max_damage = max(vals + [1])
    parts = ['<line x1="36" y1="178" x2="%d" y2="178" stroke="#385369"/>' % (width - 20)]
    for i, (day, values) in enumerate(entries):
        avg = values['avg_damage']
        x = margin + i * step
        bar_height = round(140.0 * avg / max_damage) if avg is not None else 0
        y = 178 - bar_height
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s"/>' %
                     (x, y, bar_width, bar_height, '#33bca7' if avg is not None else '#526b7c'))
        parts.append('<text x="%d" y="%d" text-anchor="middle" fill="#e9f5f5" font-size="12">%s</text>' %
                     (x + 21, max(y - 8, 14), escape(fmt(avg))))
        parts.append('<text x="%d" y="205" text-anchor="middle" fill="#a1b6c9" font-size="11">%s</text>' %
                     (x + 21, escape(day[5:])))
    return ('<svg role="img" aria-label="Средний урон по дням" viewBox="0 0 %d %d">%s</svg>'
            % (width, height, ''.join(parts)))


def rolling_chart(records, window):
    points = rolling_damage(records, window=window, max_points=80)
    valid = [(i, val) for i, val, n in points if val is not None]
    if not valid:
        return '<p class="hint">Не хватает боёв с известным уроном для скользящего среднего по %d боям.</p>' % window
    width, height = 800, 240
    left, right, top, bottom = 55, 775, 24, 195
    min_x, max_x = points[0][0], points[-1][0]
    max_y = max(1, max(v for _, v in valid) * 1.08)

    def xy(index, value):
        x = left + (index - min_x) * (right - left) / max(1, max_x - min_x)
        y = bottom - value / max_y * (bottom - top)
        return x, y

    chunks = []
    current = []
    for index, avg, _ in points:
        if avg is None:
            if current:
                chunks.append(current)
                current = []
        else:
            current.append(xy(index, avg))
    if current:
        chunks.append(current)
    segments = []
    for chunk in chunks:
        if len(chunk) >= 2:
            segments.append('<polyline points="%s" fill="none" stroke="#3ad3b6" stroke-width="3" stroke-linejoin="round"/>' %
                            ' '.join('%.1f,%.1f' % pair for pair in chunk))
        else:
            x, y = chunk[0]
            segments.append('<circle cx="%.1f" cy="%.1f" r="4" fill="#3ad3b6"/>' % (x, y))
    latest_x, latest_y = xy(*valid[-1])
    segments.append('<circle cx="%.1f" cy="%.1f" r="4" fill="#a8fff0"/>' % (latest_x, latest_y))
    return ('''<svg role="img" aria-label="Скользящий средний урон за %d боёв" viewBox="0 0 %d %d">
<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#426074"/>
<text x="%d" y="17" fill="#a1b6c9" font-size="12">Макс. шкалы: %d</text>
<text x="%d" y="222" fill="#a1b6c9" font-size="12">Бой № %d</text>
<text x="%d" y="222" text-anchor="end" fill="#a1b6c9" font-size="12">Бой № %d</text>%s</svg>''' %
            (window, width, height, left, bottom, right, bottom, left, int(max_y),
             left, min_x, right, max_x, ''.join(segments)))


def comparison_html(records, window):
    c = window_comparison(records, window)
    current, previous = c['current'], c['previous']
    if not c['enough_current']:
        return '<p class="hint">Для сравнения %d последних боёв нужно минимум %d боёв. Сейчас: %d.</p>' % (
            window, window * 2, len(records))
    if not c['enough_previous']:
        return '<p class="hint">Есть %d последних боёв, но для честного сравнения с предыдущими %d нужно %d боёв. Сейчас: %d.</p>' % (
            window, window, window * 2, len(records))
    left = stats_card('Средний урон', fmt(current['avg_damage']),
                      'Раньше: %s · изменение: %s' % (fmt(previous['avg_damage']),
                      fmt(c['damage_delta'], ' ед.')))
    right = stats_card('Процент побед', fmt(current['win_rate'], '%'),
                       'Раньше: %s · изменение: %s' % (fmt(previous['win_rate'], '%'),
                       fmt(c['win_rate_delta_pp'], ' п.п.')))
    return ('<div class="stats compare">%s%s</div><p class="hint">Только собственные завершённые бои. '
            'Пропущенные исходы и урон не приравниваются к нулю; для побед учтено %d/%d и %d/%d боёв.</p>' %
            (left, right, current['known_outcomes'], window, previous['known_outcomes'], window))


def vehicle_html(records):
    entries = vehicle_table(records)
    rows = []
    for name, s in entries:
        rows.append('<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td>'
                    '<td class="num">%s</td><td class="num">%d/%d</td></tr>' %
                    (escape(name), s['battles'], escape(fmt(s['win_rate'], '%')),
                     escape(fmt(s['avg_damage'])), s['damage_samples'], s['battles']))
    if not rows:
        rows.append('<tr><td colspan="5" class="hint">По выбранным фильтрам нет боёв.</td></tr>')
    return ''.join(rows)


def battle_html(records):
    labels = {'win': 'Победа', 'loss': 'Поражение', 'draw': 'Ничья', 'unknown': 'Неизвестно'}
    rows = []
    for record in reversed(records[-150:]):
        day = record_date(record) or '—'
        outcome = record.get('outcome')
        css_class = outcome if outcome in labels else 'unknown'
        rows.append('<tr><td>%s</td><td>%s</td><td><span class="result %s">%s</span></td>'
                    '<td class="num">%s</td><td class="num">%s</td></tr>' %
                    (escape(day), escape(record.get('vehicle') or 'unknown'), css_class,
                     escape(labels.get(outcome, 'Неизвестно')),
                     escape(fmt(_non_negative_int(record.get('damage')))),
                     escape(fmt(_non_negative_int(record.get('xp'))))))
    return ''.join(rows) or '<tr><td colspan="5" class="hint">Боёв пока нет. Попробуйте демоданные.</td></tr>'


def goals_html(records, goals):
    if not goals:
        return '<p class="hint">Цели не заданы. Используйте --goals путь/к/goals.json для персональных целей.</p>'
    labels = {'in_progress': 'Нужно больше боёв',
              'insufficient_data': 'Недостаточно известных значений урона',
              'achieved': 'Цель достигнута', 'not_achieved': 'Цель пока не достигнута'}
    rows = []
    for item in evaluate_goals(records, goals):
        rows.append('<tr><td>%s</td><td class="num">%d</td><td class="num">%d/%d</td>'
                    '<td class="num">%s</td><td>%s</td></tr>' % (
                        escape(item['vehicle']), item['target'], item['battles'], item['window'],
                        escape(fmt(item['avg_damage'])), escape(labels[item['status']])))
    return ('<div class="scroll"><table><thead><tr><th>Танк</th><th class="num">Цель по урону</th>'
            '<th class="num">Боёв</th><th class="num">Текущий средний</th><th>Статус</th></tr>'
            '</thead><tbody>%s</tbody></table></div>' % ''.join(rows))


def render(records, vehicle_filter='', from_day='', to_day='', source_label='',
           account_filter='', window=10, goals=None):
    """Render an escaped, script-free HTML page from local data only."""
    window = safe_window(window)
    from_day, to_day = valid_date(from_day), valid_date(to_day)
    vehicles = sorted(set(str(r.get('vehicle') or 'unknown') for r in records if isinstance(r, dict)))
    accounts = sorted(set(str(r.get('account_id') or 'local') for r in records if isinstance(r, dict)))
    selected = select_records(records, vehicle_filter, account_filter, from_day, to_day)
    totals = summarize(selected)
    filters = {'vehicle': vehicle_filter, 'account': account_filter,
               'from': from_day, 'to': to_day, 'window': str(window)}
    opts = ['<option value="">Все танки</option>']
    for name in vehicles:
        opts.append('<option value="%s"%s>%s</option>' %
                    (escape(name), ' selected' if name == vehicle_filter else '', escape(name)))
    account_opts = ['<option value="">Все аккаунты</option>']
    for name in accounts:
        account_opts.append('<option value="%s"%s>%s</option>' %
                            (escape(name), ' selected' if name == account_filter else '', escape(name)))
    wopts = []
    for n in (10, 30, 100):
        wopts.append('<option value="%d"%s>%d боёв</option>' %
                     (n, ' selected' if n == window else '', n))
    cards = ''.join((
        stats_card('Всего боёв', totals['battles'], 'По выбранным фильтрам'),
        stats_card('Победы', fmt(totals['win_rate'], '%'),
                   '%d боёв с известным исходом' % totals['known_outcomes']),
        stats_card('Средний урон', fmt(totals['avg_damage']),
                   '%d боёв с известным уроном' % totals['damage_samples']),
        stats_card('Средний опыт', fmt(totals['avg_xp']), 'Только известные значения'),
    ))
    query = urlencode(filters)
    return Template('''<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TankSession Analytics v0.3</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b1420;color:#edf5f7;font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1200px;margin:auto;padding:38px 20px 75px}.eyebrow{color:#42d8c2;letter-spacing:.12em;font-weight:700;font-size:12px;text-transform:uppercase}
h1{font-size:clamp(30px,5vw,48px);margin:6px 0 5px;letter-spacing:-.04em}h2{font-size:21px;margin:0 0 14px}
.intro,.hint{color:#a2bac9}.intro{margin:8px 0 26px}.hint{font-size:13px}.panel{background:#152637;border:1px solid #294053;border-radius:16px;padding:23px;margin:20px 0}
form{display:flex;flex-wrap:wrap;align-items:end;gap:11px}label{display:flex;flex-direction:column;gap:5px;min-width:140px;color:#a2bac9;font-size:12px}
select,input{min-height:41px;max-width:230px;background:#0b1825;color:#f6ffff;border:1px solid #42596b;border-radius:8px;padding:0 10px;font-size:14px}
button,.btn{display:inline-flex;align-items:center;justify-content:center;padding:0 15px;height:41px;background:#35ccb4;color:#0b1920;border:0;border-radius:9px;text-decoration:none;font-weight:700;cursor:pointer}
.btn.secondary{background:#294253;color:#ebf5f6}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.stats.compare{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{padding:18px;border:1px solid #315066;border-radius:13px;background:#1c3445}
.stat span,.stat small{display:block;color:#a2bac9}.stat strong{display:block;font-size:31px;margin:7px 0}.stat small{font-size:12px}
svg{width:100%;height:auto;min-width:550px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:520px}
th,td{padding:12px 10px;border-bottom:1px solid #30485b;text-align:left}th{color:#a2bac9;font-weight:600;font-size:12px}
.num{text-align:right;font-variant-numeric:tabular-nums}.result{padding:3px 9px;border-radius:99px;background:#30485b;font-size:12px}
.result.win{background:#104d40;color:#a3ffe6}.result.loss{background:#53303b;color:#ffc5ce}.result.draw{background:#4e4530;color:#f8e0a8}
footer{color:#a1b6c9;font-size:12px;margin-top:30px}code{overflow-wrap:anywhere;color:#bce9e5}
@media(max-width:800px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{padding:16px}}
@media(max-width:450px){.stats,.stats.compare{grid-template-columns:1fr}}
</style></head><body><main>
<div class="eyebrow">Неофициальный проект · только локальные данные</div>
<h1>TankSession <span style="color:#35ccb4">Analytics</span></h1>
<p class="intro">Личный журнал боёв: сравнение танков, скользящий средний урон, история и экспорт. Данные не покидают компьютер.</p>
<section class="panel"><form method="get" action="/"><label>Аккаунт<select name="account">$accounts</select></label>
<label>Танк<select name="vehicle">$vehicles</select></label>
<label>С даты<input type="date" name="from" value="$from_day"></label>
<label>По дату<input type="date" name="to" value="$to_day"></label>
<label>Период сравнения<select name="window">$windows</select></label>
<button type="submit">Показать</button><a class="btn secondary" href="/">Сбросить</a>
<a class="btn secondary" href="/export.csv?$query">Экспорт CSV</a></form></section>
<div class="stats">$cards</div>
<section class="panel"><h2>Сравнение двух последовательных периодов</h2>$comparison</section>
<section class="panel"><h2>Скользящий средний урон</h2><p class="hint">Последние 80 точек, окно — $window боёв. Пробелы означают недостаток данных, а не нулевой урон.</p><div class="scroll">$rolling</div></section>
<section class="panel"><h2>Средний урон по дням</h2><div class="scroll">$daily</div></section>
<section class="panel"><h2>Персональные цели</h2><p class="hint">Оценка по последним боям выбранной техники. Цель засчитывается только на полном окне с достаточным количеством известных значений.</p>$goals</section>
<section class="panel"><h2>Эффективность по танкам</h2><p class="hint">Сортировка по числу сыгранных боёв; прочерк означает отсутствие подтверждённой метрики.</p>
<div class="scroll"><table><thead><tr><th>Техника</th><th class="num">Боёв</th><th class="num">Победы</th><th class="num">Средний урон</th><th class="num">Есть урон</th></tr></thead><tbody>$vehicles_table</tbody></table></div></section>
<section class="panel"><h2>Последние 150 боёв</h2><div class="scroll"><table><thead><tr><th>Дата</th><th>Танк</th><th>Исход</th><th class="num">Урон</th><th class="num">Опыт</th></tr></thead><tbody>$battles</tbody></table></div></section>
<footer>Источник: <code>$source</code>. Результаты фиксируются по времени получения события. Неофициальный проект, не связан с Lesta Games. Совместимость с актуальным клиентом не подтверждена.</footer>
</main></body></html>''').substitute(
        accounts=''.join(account_opts), vehicles=''.join(opts), windows=''.join(wopts),
        from_day=escape(from_day), to_day=escape(to_day), query=escape(query),
        cards=cards, comparison=comparison_html(selected, window), window=window,
        goals=goals_html(selected, goals or []),
        daily=daily_chart(selected), rolling=rolling_chart(selected, window),
        vehicles_table=vehicle_html(selected), battles=battle_html(selected),
        source=escape(source_label))


def _csv_safe(value):
    """Prevent spreadsheet formula execution in free-form text columns."""
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    if value.lstrip().startswith(('=', '+', '-', '@')) or value[:1] in ('\t', '\r', '\n'):
        return "'" + value
    return value


def export_csv(records, vehicle_filter='', from_day='', to_day='',
               account_filter=''):
    """Return UTF-8 CSV of exactly the currently selected valid battles."""
    selected = select_records(records, vehicle_filter, account_filter, from_day, to_day)
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(CSV_FIELDS)
    for record in selected:
        row = []
        for field in CSV_FIELDS:
            raw = record_date(record) if field == 'date' else record.get(field)
            if field in ('arena_id', 'account_id', 'vehicle', 'mode', 'outcome'):
                row.append(_csv_safe(raw))
            elif field == 'date':
                row.append(raw or '')
            else:
                number = _non_negative_int(raw)
                row.append(number if number is not None else '')
        writer.writerow(row)
    # BOM improves display of Russian tank names in Windows Excel.
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description='TankSession Analytics (read-only localhost)')
    parser.add_argument('--data', default=os.path.join(ROOT, 'sample_data', 'battles.jsonl'),
                        help='Local JSONL data file (defaults to SYNTHETIC example data)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--goals', default='', help='Optional local JSON file with personal targets')
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost'):
        parser.error('For privacy, only 127.0.0.1/localhost is supported')
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    source = os.path.abspath(args.data)
    try:
        goals = load_goals(args.goals)
    except (OSError, ValueError, TypeError) as error:
        parser.error('Cannot load goals: %s' % error)
    journal = CachedJournal(source)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Reject hostile Host headers, including DNS rebinding aliases.
            if self.headers.get('Host', '') not in (
                    '127.0.0.1:%d' % args.port, 'localhost:%d' % args.port,
                    '127.0.0.1', 'localhost'):
                self.send_error(400, 'Unsupported Host')
                return
            parsed = urlsplit(self.path)
            if parsed.path not in ('/', '/index.html', '/export.csv'):
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            get = lambda key: params.get(key, [''])[0]
            records = journal.records()
            if parsed.path == '/export.csv':
                data = export_csv(records, get('vehicle'), get('from'), get('to'), get('account'))
                kind = 'text/csv; charset=utf-8'
            else:
                data = render(records, get('vehicle'), get('from'), get('to'), source,
                              get('account'), get('window'), goals).encode('utf-8')
                kind = 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            if parsed.path == '/export.csv':
                self.send_header('Content-Disposition', 'attachment; filename="tanksession_battles.csv"')
            self.end_headers()
            self.wfile.write(data)

    print('Dashboard: http://%s:%d/' % (args.host, args.port))
    print('Data file: %s' % source)
    print('Demo history is SYNTHETIC unless --data is provided. CTRL+C to stop.')
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
