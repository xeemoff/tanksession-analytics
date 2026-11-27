#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Account-scoped, read-only companion reports outside the game process.

Python owns journal validation, revisions and conservative vehicle identities.
The optional C++23 process receives only dense numeric group IDs and metrics.
The Python reference engine is selected explicitly; native errors never fall
back silently. No report operation modifies the source journal or profiles.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.analytics import valid_date
from tanksession_analytics.core import validate_record
from tanksession_analytics.recorder import _verified_account
from tanksession_analytics.storage import BattleStore
from tanksession_analytics.vehicles import resolve_records, resolve_selector, selector_for

PROTOCOL = 1
MAX_ROWS = 1_000_000
MAX_GROUPS = 4096
MAX_METRIC = 1_000_000_000_000
MAX_JOURNAL_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
METRICS = ('damage', 'xp', 'xp_base', 'xp_bonus', 'credits_net')
OUTCOMES = {'unknown': 0, 'win': 1, 'loss': 2, 'draw': 3}
DEFINITIONS = {'variance': 'sample', 'quantile': 'linear_r7',
               'win_rate': 'wins/known_outcomes', 'sum': 'exact_decimal_string'}
METRIC_KEYS = frozenset(('known', 'missing', 'coverage_pct', 'sum', 'mean',
                         'sample_variance', 'stddev', 'p50', 'p90',
                         'coefficient_of_variation', 'min', 'max'))
SUMMARY_KEYS = frozenset(('battles', 'wins', 'losses', 'draws', 'outcomes_known',
                          'outcome_coverage_pct', 'win_rate', 'metrics'))


class NativeReportError(ValueError):
    pass


@dataclass
class PreparedReport:
    rows: list
    groups: list
    source: dict


def _outside_game():
    if 'BigWorld' in sys.modules:
        raise NativeReportError('Companion reports must run outside the game process')


def utc_record_date(row):
    stamp = row.get('timestamp')
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m-%d')
    except (ValueError, OverflowError, OSError):
        return None


def prepare_records(records, account_id, vehicle='', from_day='', to_day='', diagnostics=None):
    """Project already deduplicated journal rows into a bounded numeric batch.

    Public callers must pass BattleStore.records, not raw physical JSONL lines.
    Validation is repeated at this boundary and duplicate own battle IDs reject
    the batch. No unknown or other-account rows can establish vehicle aliases.
    """
    _outside_game()
    account = _verified_account(account_id)
    if account is None or len(account) > 128:
        raise NativeReportError('Select one verified account with --account')
    if ((from_day and not valid_date(from_day)) or (to_day and not valid_date(to_day))
            or (from_day and to_day and from_day > to_day)):
        raise NativeReportError('Date bounds must be ordered YYYY-MM-DD dates')
    clean = []
    other_accounts = set()
    other_rows = unowned_rows = 0
    own_ids = set()
    for item in records:
        row = validate_record(item)
        if row is None:
            raise NativeReportError('Report input must contain validated journal records')
        owner = _verified_account(row['account_id'])
        if owner is None:
            unowned_rows += 1
        elif owner != account:
            other_rows += 1
            other_accounts.add(owner)
        else:
            if row['arena_id'] in own_ids:
                raise NativeReportError('Duplicate own battles: resolve revisions with BattleStore first')
            own_ids.add(row['arena_id'])
            clean.append(row)
            if len(clean) > MAX_ROWS:
                raise NativeReportError('Companion row limit exceeded (1,000,000)')
    scoped = resolve_records(clean, account)
    account_count = len(scoped)
    selected_vehicle = resolve_selector(vehicle, scoped) if vehicle else ''
    selected = []
    for row in scoped:
        if selected_vehicle and selector_for(row) != selected_vehicle:
            continue
        if from_day or to_day:
            day = utc_record_date(row)
            if day is None or (from_day and day < from_day) or (to_day and day > to_day):
                continue
        selected.append(row)
    # Stable order also makes repeated floating-point reductions reproducible.
    selected.sort(key=lambda row: (row['timestamp'] if row['timestamp'] is not None else -1,
                                   row['arena_id']))
    selectors = sorted({selector_for(row) for row in selected})
    if len(selectors) > MAX_GROUPS:
        raise NativeReportError('Companion group limit exceeded (4096)')
    indices = {selector: index for index, selector in enumerate(selectors)}
    groups = [{'id': index, 'selector': selector, 'label': selector,
               'identity_ambiguous': False} for index, selector in enumerate(selectors)]
    numeric = []
    for row in selected:
        group = indices[selector_for(row)]
        # Last observed label in chronological order; original journal is intact.
        groups[group]['label'] = row['vehicle']
        groups[group]['identity_ambiguous'] |= bool(row.get('_vehicle_ambiguous'))
        values = tuple(row.get(field) for field in METRICS)
        for field, value in zip(METRICS, values):
            if value is not None and abs(value) > MAX_METRIC:
                raise NativeReportError('Metric %s exceeds companion bound (+/-10^12); no report was produced' % field)
        numeric.append((group, OUTCOMES[row['outcome']], values))
    source = {'scope': 'one_verified_account', 'date_basis': 'received_at_utc', 'account_records': account_count,
              'selected_records': len(numeric), 'filtered_records': account_count - len(numeric),
              'excluded_other_account_records': other_rows,
              'excluded_other_accounts': len(other_accounts),
              'excluded_unowned_records': unowned_rows}
    if diagnostics is not None:
        source['journal'] = {name: diagnostics[name] for name in
                             ('lines', 'malformed', 'invalid', 'valid_unique',
                              'duplicates', 'revisions', 'conflicts')}
    return PreparedReport(numeric, groups, source)


def load_journal(path, account_id, **filters):
    _outside_game()
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_JOURNAL_BYTES:
            raise NativeReportError('Journal is missing or exceeds the 512 MiB companion limit')
        store = BattleStore(str(path))
    except OSError as error:
        raise NativeReportError('Journal cannot be read') from error
    return prepare_records(store.records, account_id, diagnostics=store.diagnostics, **filters)


def encode_input(prepared):
    lines = ['TSA_NATIVE\t1\t%d\t%d\n' % (len(prepared.rows), len(prepared.groups))]
    for group, outcome, values in prepared.rows:
        lines.append('%d\t%d\t%s\n' % (group, outcome,
                     '\t'.join('?' if value is None else str(value) for value in values)))
    return ''.join(lines).encode('ascii')


def _quantile(values, probability):
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (position - lower) * (values[upper] - values[lower])


def _reference_summary(rows):
    count = len(rows)
    outcomes = [sum(row[1] == value for row in rows) for value in (1, 2, 3)]
    known_outcomes = sum(outcomes)
    result = dict(zip(('wins', 'losses', 'draws'), outcomes))
    result.update(battles=count, outcomes_known=known_outcomes,
                  outcome_coverage_pct=100.0 * known_outcomes / count if count else None,
                  win_rate=100.0 * outcomes[0] / known_outcomes if known_outcomes else None,
                  metrics={})
    for index, field in enumerate(METRICS):
        values = sorted(row[2][index] for row in rows if row[2][index] is not None)
        known = len(values)
        # statistics.variance uses an independent exact-ratio implementation;
        # parity tests do not merely duplicate the C++ Welford loop.
        mean = float(statistics.mean(values)) if known else None
        variance = float(statistics.variance(values)) if known >= 2 else None
        stddev = math.sqrt(variance) if variance is not None else None
        result['metrics'][field] = {
            'known': known, 'missing': count - known,
            'coverage_pct': 100.0 * known / count if count else None,
            'sum': str(sum(values)) if known else None, 'mean': mean,
            'sample_variance': variance, 'stddev': stddev,
            'p50': _quantile(values, 0.5) if known else None,
            'p90': _quantile(values, 0.9) if known else None,
            'coefficient_of_variation': stddev / mean
                if field != 'credits_net' and stddev is not None and mean > 0 else None,
            'min': values[0] if known else None, 'max': values[-1] if known else None,
        }
    return result


def reference_report(prepared):
    buckets = [[] for _ in prepared.groups]
    for row in prepared.rows:
        buckets[row[0]].append(row)
    return {'protocol': PROTOCOL, 'definitions': dict(DEFINITIONS),
            'overall': _reference_summary(prepared.rows),
            'groups': [{'id': index, 'statistics': _reference_summary(rows)}
                       for index, rows in enumerate(buckets)]}


def find_binary(binary=None):
    name = 'tanksession-native.exe' if os.name == 'nt' else 'tanksession-native'
    explicit = binary or os.environ.get('TANKSESSION_NATIVE_BINARY')
    candidates = ([Path(explicit)] if explicit else
                  [ROOT / 'bin' / name, ROOT / 'native/bin' / name,
                   ROOT / 'native/build/bin' / name])
    if not explicit:
        installed = shutil.which(name)
        if installed:
            candidates.append(Path(installed))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise NativeReportError('Native binary not found; use --binary or build native/. Select --engine python explicitly for the reference engine')


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeReportError('Native output contains a duplicate JSON member')
        result[key] = value
    return result


def _reject_constant(value):
    raise NativeReportError('Native output contains a non-finite JSON number')


def _integer(value, minimum=0, maximum=MAX_ROWS):
    return type(value) is int and minimum <= value <= maximum


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _check_summary(summary, expected_count):
    if not isinstance(summary, dict) or set(summary) != SUMMARY_KEYS:
        raise NativeReportError('Native summary schema mismatch')
    counts = ('battles', 'wins', 'losses', 'draws', 'outcomes_known')
    if (not all(_integer(summary[name]) for name in counts) or summary['battles'] != expected_count
            or sum(summary[name] for name in ('wins', 'losses', 'draws')) != summary['outcomes_known']
            or summary['outcomes_known'] > expected_count):
        raise NativeReportError('Native outcome counts do not reconcile')
    for name, denominator, numerator in (
        ('win_rate', summary['outcomes_known'], summary['wins']),
        ('outcome_coverage_pct', expected_count, summary['outcomes_known']),
    ):
        expected = 100.0 * numerator / denominator if denominator else None
        actual = summary[name]
        if ((expected is None and actual is not None) or
                (expected is not None and (not _number(actual) or not math.isclose(actual, expected, abs_tol=1e-9)))):
            raise NativeReportError('Native outcome rates do not reconcile')
    metrics = summary['metrics']
    if not isinstance(metrics, dict) or set(metrics) != set(METRICS):
        raise NativeReportError('Native metric names do not match the protocol')
    for field, metric in metrics.items():
        if not isinstance(metric, dict) or set(metric) != METRIC_KEYS:
            raise NativeReportError('Native metric schema mismatch')
        known, missing = metric['known'], metric['missing']
        if not _integer(known) or not _integer(missing) or known + missing != expected_count:
            raise NativeReportError('Native metric counts do not reconcile')
        coverage = 100.0 * known / expected_count if expected_count else None
        actual = metric['coverage_pct']
        if ((coverage is None and actual is not None) or
                (coverage is not None and (not _number(actual) or not math.isclose(actual, coverage, abs_tol=1e-9)))):
            raise NativeReportError('Native metric coverage does not reconcile')
        for name in ('mean', 'p50', 'p90', 'min', 'max'):
            value = metric[name]
            if ((known == 0 and value is not None) or
                    (known > 0 and (not _number(value) or abs(value) > MAX_METRIC))):
                raise NativeReportError('Native metric value is invalid')
        total = metric['sum']
        if known == 0:
            if total is not None:
                raise NativeReportError('Native missing sum was invented')
        elif (not isinstance(total, str) or len(total) > 20 or total == '-0'
              or re.fullmatch(r'-?(0|[1-9][0-9]*)', total) is None
              or abs(int(total)) > known * MAX_METRIC):
            raise NativeReportError('Native sum is not an exact bounded integer')
        for name in ('sample_variance', 'stddev'):
            value = metric[name]
            if ((known < 2 and value is not None) or
                    (known >= 2 and (not _number(value) or value < 0))):
                raise NativeReportError('Native dispersion value is invalid')
        cv = metric['coefficient_of_variation']
        has_cv = field != 'credits_net' and known >= 2 and metric['mean'] > 0
        if ((not has_cv and cv is not None) or
                (has_cv and (not _number(cv) or cv < 0))):
            raise NativeReportError('Native coefficient of variation is invalid')


def validate_native_output(raw, prepared):
    if len(raw) > MAX_OUTPUT_BYTES:
        raise NativeReportError('Native output exceeds the size limit')
    try:
        report = json.loads(raw.decode('utf-8'), object_pairs_hook=_json_object,
                            parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise NativeReportError('Native output is not valid protocol JSON') from error
    if (not isinstance(report, dict) or set(report) != {'protocol', 'definitions', 'overall', 'groups'}
            or type(report['protocol']) is not int or report['protocol'] != PROTOCOL
            or report['definitions'] != DEFINITIONS or not isinstance(report['groups'], list)
            or len(report['groups']) != len(prepared.groups)):
        raise NativeReportError('Native output protocol mismatch')
    _check_summary(report['overall'], len(prepared.rows))
    counts = [0] * len(prepared.groups)
    for group, _, _ in prepared.rows:
        counts[group] += 1
    for index, group in enumerate(report['groups']):
        if (not isinstance(group, dict) or set(group) != {'id', 'statistics'}
                or type(group['id']) is not int or group['id'] != index):
            raise NativeReportError('Native output group mismatch')
        _check_summary(group['statistics'], counts[index])
    for name in ('battles', 'wins', 'losses', 'draws', 'outcomes_known'):
        if sum(group['statistics'][name] for group in report['groups']) != report['overall'][name]:
            raise NativeReportError('Native group totals do not reconcile')
    for field in METRICS:
        metrics = [group['statistics']['metrics'][field] for group in report['groups']]
        overall = report['overall']['metrics'][field]
        if (sum(metric['known'] for metric in metrics) != overall['known'] or
                (overall['known'] and sum(int(metric['sum']) for metric in metrics
                                         if metric['known']) != int(overall['sum']))):
            raise NativeReportError('Native group metric totals do not reconcile')
    return report


def run_report(prepared, engine='native', binary=None, timeout=60):
    _outside_game()
    if engine == 'native':
        executable = find_binary(binary)
        try:
            result = subprocess.run([str(executable)], input=encode_input(prepared),
                                    capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NativeReportError('Native execution failed or timed out; no fallback was used') from error
        if result.returncode != 0:
            raise NativeReportError('Native execution failed (exit %d); no fallback was used' % result.returncode)
        report = validate_native_output(result.stdout, prepared)
    elif engine == 'python':
        report = reference_report(prepared)
    else:
        raise NativeReportError('Engine must be native or python')
    report['engine'] = 'cpp23' if engine == 'native' else 'python_reference'
    report['source'] = dict(prepared.source)
    for statistics_group, metadata in zip(report['groups'], prepared.groups):
        statistics_group.update(metadata)
    return report


def readable_report(report, top=20):
    labels = {'damage': 'Урон', 'xp': 'Полученный опыт', 'xp_base': 'Базовый опыт',
              'xp_bonus': 'Бонусный опыт', 'credits_net': 'Чистые кредиты'}

    def number(value):
        return 'нет данных' if value is None else ('%.2f' % value)

    def section(summary):
        rate = number(summary['win_rate']) + '%' if summary['win_rate'] is not None else 'нет данных'
        lines = ['Бои: %d; известный исход: %d; победы: %s' %
                 (summary['battles'], summary['outcomes_known'], rate)]
        for field in METRICS:
            metric = summary['metrics'][field]
            lines.append('%s: %d/%d; сумма %s; среднее %s; p50 %s; p90 %s; σ %s' %
                         (labels[field], metric['known'], summary['battles'],
                          metric['sum'] if metric['sum'] is not None else 'нет данных',
                          number(metric['mean']), number(metric['p50']), number(metric['p90']),
                          number(metric['stddev'])))
        damage = summary['metrics']['damage']
        lines.append('Разброс урона относительно среднего (CV): %s' %
                     number(damage['coefficient_of_variation']))
        return lines

    source = report['source']
    lines = ['TankSession — локальный отчёт (%s)' % report['engine'],
             'Один выбранный аккаунт. Исключены: %d боёв других аккаунтов (%d аккаунтов), %d записей без владельца.' %
             (source['excluded_other_account_records'], source['excluded_other_accounts'],
              source['excluded_unowned_records']),
             'Фильтром исключено: %d. Пропуски не считаются нулём.' % source['filtered_records'], '']
    lines.extend(section(report['overall']))
    groups = sorted(report['groups'], key=lambda group: (-group['statistics']['battles'], group['id']))
    for group in groups[:top]:
        label = ''.join(char if char.isprintable() else ' ' for char in group['label'])
        selector = ''.join(char if char.isprintable() else ' ' for char in group['selector'])
        lines.extend(['', '%s [%s]' % (label, selector)])
        if group['identity_ambiguous']:
            lines.append('Неоднозначная старая группа: сводка не подтверждает одну машину.')
        lines.extend(section(group['statistics']))
    if len(groups) > top:
        lines.append('\nПоказано групп: %d/%d; --json содержит все группы.' % (top, len(groups)))
    lines.extend(['', 'σ — выборочное стандартное отклонение; p50/p90 — линейные перцентили R7.',
                  'CV описывает разброс наблюдений, а не оценивает навык. При малой выборке выводов о прогрессе нет.'])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='Read-only account-scoped C++23 analytics companion')
    parser.add_argument('--data', required=True, type=Path, help='Path to battles.jsonl')
    parser.add_argument('--account', required=True, help='One verified account ID; never included in output')
    parser.add_argument('--vehicle', default='', help='Stable selector or an unambiguous exact old label')
    parser.add_argument('--from', dest='from_day', default='', help='Inclusive UTC receipt date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_day', default='', help='Inclusive UTC receipt date YYYY-MM-DD')
    parser.add_argument('--engine', choices=('native', 'python'), default='native')
    parser.add_argument('--binary', type=Path, help='Explicit companion executable')
    parser.add_argument('--json', action='store_true', help='Output the complete versioned JSON report')
    parser.add_argument('--output', type=Path, help='Save the report to a file instead of stdout')
    parser.add_argument('--top', type=int, default=20, help='Maximum groups in readable output (1..4096)')
    args = parser.parse_args(argv)
    if not 1 <= args.top <= MAX_GROUPS:
        parser.error('--top must be 1..4096')
    try:
        prepared = load_journal(args.data, args.account, vehicle=args.vehicle,
                                from_day=args.from_day, to_day=args.to_day)
        report = run_report(prepared, engine=args.engine, binary=args.binary)
        text = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
                if args.json else readable_report(report, args.top))
        if args.output:
            # A report may replace another explicit output, never the journal.
            if args.output.resolve() == args.data.resolve():
                raise NativeReportError('Report output must not replace the source journal')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                                 dir=args.output.parent, delete=False) as temporary:
                    temporary_path = temporary.name
                    temporary.write(text)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, args.output)
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.unlink(temporary_path)
        else:
            sys.stdout.write(text)
        return 0
    except (NativeReportError, OSError) as error:
        print('Report stopped: %s' % error, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
