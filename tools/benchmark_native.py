#!/usr/bin/env python3
"""Reproducible companion benchmark on synthetic records, without user data."""
import argparse
import hashlib
import json
import platform
import statistics
import time

from native_report import MAX_ROWS, find_binary, prepare_records, run_report


def synthetic_records(count):
    return [{'schema': 1, 'arena_id': str(index + 1), 'account_id': 'native-benchmark',
             'timestamp': 1_720_000_000 + index, 'vehicle': 'Synthetic %d' % (index % 32),
             'vehicle_id': 'type:%d' % (257 + 256 * (index % 32)), 'mode': '1',
             'outcome': ('unknown', 'win', 'loss', 'draw')[index % 4],
             'damage': None if index % 23 == 0 else index * 13 % 7000,
             'xp': index * 7 % 1500,
             'xp_base': None if index % 13 == 0 else index * 5 % 900,
             'xp_bonus': None if index % 13 == 0 else index * 3 % 500,
             'credits_net': None if index % 17 == 0 else index * 103 % 60000 - 15000}
            for index in range(count)]


def benchmark(count, repeats, binary):
    records = synthetic_records(count)
    started = time.perf_counter()
    prepared = prepare_records(records, 'native-benchmark')
    preparation = time.perf_counter() - started
    del records
    measurements = {}
    for engine in ('native', 'python'):
        durations = []
        for iteration in range(repeats + 1):
            started = time.perf_counter()
            report = run_report(prepared, engine=engine, binary=binary)
            elapsed = time.perf_counter() - started
            if report['overall']['battles'] != count:
                raise RuntimeError('Benchmark result did not reconcile')
            if iteration:
                durations.append(elapsed)
        measurements[engine] = {'median_seconds': statistics.median(durations),
                                 'min_seconds': min(durations)}
    return {'rows': count, 'groups': len(prepared.groups), 'repeats': repeats,
            'preparation_seconds': preparation,
            'native_subprocess_and_protocol': measurements['native'],
            'python_exact_reference': measurements['python'],
            'reference_over_native_ratio': measurements['python']['median_seconds'] /
                                           measurements['native']['median_seconds']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', help='Path to tanksession-native executable')
    parser.add_argument('--sizes', type=int, nargs='+', default=[1000, 10000, 100000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 20 or any(not 100 <= count <= MAX_ROWS for count in args.sizes):
        parser.error('Use 1..20 repeats and sizes 100..1000000')
    binary = find_binary(args.binary)
    result = {'scope': 'synthetic_account_scoped_companion_report',
              'native_timing_includes': ['input_encoding', 'process_start', 'native_parse_and_analytics',
                                         'output_json_validation', 'label_attachment'],
              'excluded_from_engine_timings': ['journal_io', 'shared_validation_and_identity_preparation'],
              'platform': platform.platform(), 'python': platform.python_version(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'results': [benchmark(count, args.repeats, binary) for count in args.sizes]}
    if args.json:
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        print('Synthetic companion report: native subprocess versus independent Python reference')
        print('Rows        Prepare(s)  Native(s)  Reference(s)  Reference/native')
        for entry in result['results']:
            print('%-11d %-11.4f %-10.4f %-13.4f %.2f' %
                  (entry['rows'], entry['preparation_seconds'],
                   entry['native_subprocess_and_protocol']['median_seconds'],
                   entry['python_exact_reference']['median_seconds'], entry['reference_over_native_ratio']))
        print('These timings do not measure in-game FPS or the existing dashboard.')


if __name__ == '__main__':
    main()
