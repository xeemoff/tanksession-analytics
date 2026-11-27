import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_report as native


def row(number, account='own', vehicle='Tank', vehicle_id='type:257', **metrics):
    result = {'schema': 1, 'arena_id': str(number), 'account_id': account,
              'vehicle': vehicle, 'vehicle_id': vehicle_id, 'timestamp': 1_700_000_000 + number,
              'mode': '1', 'outcome': 'win', 'damage': 100, 'xp': 200}
    result.update(metrics)
    return result


class NativeAdapterTests(unittest.TestCase):
    def test_account_scope_precedes_identity_inference_and_identifiers_never_cross_wire(self):
        rows = [row(1, vehicle='Shared', vehicle_id=None),
                row(2, account='other-secret-account', vehicle='Shared'),
                row(3, account='local', vehicle='Legacy')]
        prepared = native.prepare_records(rows, 'own')
        self.assertEqual(prepared.groups[0]['selector'], 'Shared')
        self.assertEqual(prepared.source['selected_records'], 1)
        self.assertEqual(prepared.source['excluded_other_account_records'], 1)
        self.assertEqual(prepared.source['excluded_other_accounts'], 1)
        self.assertEqual(prepared.source['excluded_unowned_records'], 1)
        wire = native.encode_input(prepared)
        for private in (b'own', b'other-secret-account', b'Shared', b'type:', b'account', b'arena'):
            self.assertNotIn(private, wire)
        self.assertEqual(wire, b'TSA_NATIVE\t1\t1\t1\n0\t1\t100\t200\t?\t?\t?\n')

    def test_same_account_legacy_identity_projection_does_not_mutate_input(self):
        rows = [row(1, vehicle='Alias', vehicle_id=None), row(2, vehicle='Alias')]
        original = copy.deepcopy(rows)
        prepared = native.prepare_records(rows, 'own')
        self.assertEqual(len(prepared.groups), 1)
        self.assertEqual(prepared.groups[0]['selector'], 'type:257')
        self.assertEqual(rows, original)

    def test_ambiguous_and_reserved_legacy_labels_remain_separate(self):
        rows = [row(1, vehicle='Alias', vehicle_id=None), row(2, vehicle='Alias'),
                row(3, vehicle='Alias', vehicle_id='type:513'),
                row(4, vehicle='type:257', vehicle_id=None)]
        prepared = native.prepare_records(rows, 'own')
        groups = {group['selector']: group for group in prepared.groups}
        self.assertEqual(len(groups), 4)
        self.assertTrue(groups['Alias']['identity_ambiguous'])
        self.assertFalse(groups['type:257']['identity_ambiguous'])
        self.assertEqual(sum(key.startswith('legacy:') for key in groups), 1)

    def test_latest_label_and_order_are_deterministic(self):
        rows = [row(2, vehicle='Новое имя'), row(1, vehicle='Old name')]
        first = native.prepare_records(rows, 'own')
        second = native.prepare_records(list(reversed(rows)), 'own')
        self.assertEqual(first.groups[0]['label'], 'Новое имя')
        self.assertEqual(native.encode_input(first), native.encode_input(second))

    def test_known_zero_missing_negative_income_and_independent_reference_statistics(self):
        rows = [row(1, damage=0, xp=None, outcome='win', credits_net=-10),
                row(2, damage=10, xp=0, outcome='loss', credits_net=0),
                row(3, damage=20, xp=None, outcome='draw', credits_net=10),
                row(4, damage=30, xp=None, outcome='unknown', credits_net=None)]
        prepared = native.prepare_records(rows, 'own')
        report = native.run_report(prepared, engine='python')
        summary = report['overall']
        self.assertAlmostEqual(summary['win_rate'], 100.0 / 3)
        damage = summary['metrics']['damage']
        self.assertEqual(damage['sum'], '60')
        self.assertEqual(damage['p50'], 15)
        self.assertEqual(damage['p90'], 27)
        self.assertAlmostEqual(damage['sample_variance'], 500.0 / 3)
        self.assertEqual(summary['metrics']['xp']['sum'], '0')
        self.assertEqual(summary['metrics']['xp']['known'], 1)
        self.assertIsNone(summary['metrics']['xp_base']['sum'])
        self.assertEqual(summary['metrics']['credits_net']['sum'], '0')
        self.assertIsNone(summary['metrics']['credits_net']['coefficient_of_variation'])

    def test_empty_account_and_single_sample_have_no_invented_variance(self):
        empty = native.run_report(native.prepare_records([row(1, account='other')], 'own'), engine='python')
        self.assertIsNone(empty['overall']['win_rate'])
        self.assertIsNone(empty['overall']['metrics']['damage']['mean'])
        single = native.run_report(native.prepare_records([row(1)], 'own'), engine='python')
        self.assertIsNone(single['overall']['metrics']['damage']['sample_variance'])
        self.assertIsNone(single['overall']['metrics']['damage']['coefficient_of_variation'])

    def test_dates_filter_unknown_timestamps_only_when_requested(self):
        rows = [row(1, timestamp=None), row(2)]
        all_rows = native.prepare_records(rows, 'own')
        self.assertEqual(len(all_rows.rows), 2)
        day = native.utc_record_date(rows[1])
        filtered = native.prepare_records(rows, 'own', from_day=day, to_day=day)
        self.assertEqual(len(filtered.rows), 1)
        self.assertEqual(filtered.source['filtered_records'], 1)
        for start, end in (('2026-02-30', ''), ('2026-12-01', '2026-11-01')):
            with self.assertRaises(native.NativeReportError):
                native.prepare_records(rows, 'own', from_day=start, to_day=end)

    @unittest.skipUnless(hasattr(time, 'tzset'), 'TZ simulation requires time.tzset')
    def test_receipt_date_filters_are_utc_and_independent_of_machine_timezone(self):
        rows = [row(1, timestamp=1_704_067_200)]  # 2024-01-01T00:00:00Z
        original = os.environ.get('TZ')
        try:
            for zone in ('UTC0', 'EST5', 'JST-9'):
                os.environ['TZ'] = zone
                time.tzset()
                prepared = native.prepare_records(rows, 'own', from_day='2024-01-01', to_day='2024-01-01')
                self.assertEqual(len(prepared.rows), 1)
                self.assertEqual(prepared.source['date_basis'], 'received_at_utc')
        finally:
            if original is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = original
            time.tzset()

    def test_bounds_and_invalid_scope_fail_explicitly(self):
        for account in ('local', 'unknown', '', None, False):
            with self.subTest(account=account), self.assertRaises(native.NativeReportError):
                native.prepare_records([row(1)], account)
        for field in native.METRICS:
            with self.subTest(field=field), self.assertRaisesRegex(native.NativeReportError, 'companion bound'):
                native.prepare_records([row(1, **{field: native.MAX_METRIC + 1})], 'own')
        with self.assertRaisesRegex(native.NativeReportError, 'Duplicate own battles'):
            native.prepare_records([row(1), row(1)], 'own')
        with mock.patch.object(native, 'MAX_ROWS', 1):
            with self.assertRaisesRegex(native.NativeReportError, 'row limit'):
                native.prepare_records([row(1), row(2)], 'own')
        with mock.patch.object(native, 'MAX_GROUPS', 1):
            with self.assertRaisesRegex(native.NativeReportError, 'group limit'):
                native.prepare_records([row(1), row(2, vehicle_id='type:513')], 'own')

    def test_native_execution_is_blocked_inside_game_process(self):
        with mock.patch.dict(sys.modules, {'BigWorld': mock.Mock()}):
            with self.assertRaisesRegex(native.NativeReportError, 'outside the game'):
                native.prepare_records([], 'own')

    def test_journal_revisions_validation_diagnostics_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'battles.jsonl'
            first = row(1, xp=None)
            revised = row(1, xp=500)
            invalid = row(2, damage=-1)
            text = '\n'.join(json.dumps(item) for item in (first, revised, revised, invalid)) + '\nbad JSON\n'
            path.write_text(text, encoding='utf-8')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            prepared = native.load_journal(path, 'own')
            self.assertEqual(len(prepared.rows), 1)
            self.assertEqual(prepared.rows[0][2][1], 500)
            self.assertEqual(prepared.source['journal']['revisions'], 1)
            self.assertEqual(prepared.source['journal']['duplicates'], 1)
            self.assertEqual(prepared.source['journal']['invalid'], 1)
            self.assertEqual(prepared.source['journal']['malformed'], 1)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_missing_journal_does_not_look_like_empty_valid_history(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(native.NativeReportError):
                native.load_journal(Path(directory) / 'missing.jsonl', 'own')

    def test_native_failure_timeout_and_missing_binary_do_not_fall_back(self):
        prepared = native.prepare_records([row(1)], 'own')
        for result in (subprocess.CompletedProcess([], 2, b'', b'private-details'),
                       subprocess.TimeoutExpired([], 1)):
            options = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with mock.patch.object(native, 'find_binary', return_value=Path('fake-binary')), \
                    mock.patch.object(native.subprocess, 'run', **options), \
                    mock.patch.object(native, 'reference_report') as reference:
                with self.assertRaisesRegex(native.NativeReportError, 'no fallback'):
                    native.run_report(prepared)
                reference.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(native.NativeReportError, 'not found'):
                native.run_report(prepared, binary=Path(directory) / 'missing-binary')

    def test_native_output_requires_exact_schema_finite_values_and_reconciled_groups(self):
        prepared = native.prepare_records([row(1)], 'own')
        valid = native.reference_report(prepared)
        self.assertEqual(native.validate_native_output(json.dumps(valid).encode(), prepared), valid)
        malformed = [b'{}', b'{"protocol":1,"protocol":1}', b'NaN', b'\xff']
        mutations = []
        for mutate in (
            lambda value: value.update(protocol=2),
            lambda value: value['overall'].update(battles=True),
            lambda value: value['groups'][0].update(id=1),
            lambda value: value['overall']['metrics']['damage'].update(mean=float('nan')),
            lambda value: value['overall']['metrics']['damage'].update(mean=10 ** 500),
            lambda value: value['overall']['metrics']['damage'].update(sum='100.0'),
            lambda value: value['groups'][0]['statistics']['metrics']['damage'].update(sum='101'),
        ):
            value = copy.deepcopy(valid)
            mutate(value)
            mutations.append(json.dumps(value).encode())
        for data in malformed + mutations:
            with self.subTest(data=data[:90]), self.assertRaises(native.NativeReportError):
                native.validate_native_output(data, prepared)

    def test_cli_explicit_reference_json_file_output_cannot_overwrite_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'battles.jsonl'
            output = Path(directory) / 'report.json'
            source.write_text(json.dumps(row(1)) + '\n', encoding='utf-8')
            original = source.read_bytes()
            args = ['--data', str(source), '--account', 'own', '--engine', 'python', '--json']
            self.assertEqual(native.main(args + ['--output', str(output)]), 0)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['engine'], 'python_reference')
            self.assertEqual(result['overall']['battles'], 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(native.main(args + ['--output', str(source)]), 2)
            self.assertEqual(source.read_bytes(), original)


class NativeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get('TANKSESSION_NATIVE_BINARY')
        if not configured:
            raise unittest.SkipTest('Set TANKSESSION_NATIVE_BINARY after the CMake build for executable parity tests')
        cls.binary = native.find_binary(configured)

    def assert_parity(self, prepared):
        actual = native.run_report(prepared, binary=self.binary)
        expected = native.run_report(prepared, engine='python')
        actual.pop('engine')
        expected.pop('engine')

        def compare(left, right, path='report'):
            if isinstance(right, dict):
                self.assertEqual(set(left), set(right), path)
                for key in right:
                    compare(left[key], right[key], path + '.' + key)
            elif isinstance(right, list):
                self.assertEqual(len(left), len(right), path)
                for index, value in enumerate(right):
                    compare(left[index], value, path + '[%d]' % index)
            elif isinstance(right, float):
                self.assertTrue(math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-8),
                                '%s: %r != %r' % (path, left, right))
            else:
                self.assertEqual(left, right, path)
        compare(actual, expected)

    def test_randomized_missing_values_outcomes_and_groups_match_independent_python(self):
        rng = random.Random(20261127)
        rows = []
        for number in range(1500):
            fields = {field: None if rng.randrange(7) == 0 else rng.randrange(20_000)
                      for field in native.METRICS}
            if fields['credits_net'] is not None:
                fields['credits_net'] -= 10_000
            rows.append(row(number + 1, vehicle_id='type:%d' % (257 + 256 * (number % 11)),
                            outcome=rng.choice(tuple(native.OUTCOMES)), **fields))
        self.assert_parity(native.prepare_records(rows, 'own'))

    def test_large_nearby_values_exact_sums_and_signed_cancellation_match_python(self):
        rows = [row(number + 1, damage=native.MAX_METRIC - number % 17,
                    credits_net=native.MAX_METRIC if number % 2 else -native.MAX_METRIC)
                for number in range(1000)]
        self.assert_parity(native.prepare_records(rows, 'own'))

    def test_empty_single_and_fully_unknown_batches_match_python(self):
        for rows in ([], [row(1)], [row(1, damage=None, xp=None, outcome='unknown')]):
            with self.subTest(rows=len(rows)):
                self.assert_parity(native.prepare_records(rows, 'own'))

    def test_cli_rejects_truncated_input_with_no_partial_report(self):
        result = subprocess.run([str(self.binary)], input=b'TSA_NATIVE\t1\t1\t1\n',
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertIn(b'truncated input', result.stderr)

    def test_windows_control_z_cannot_hide_trailing_payload(self):
        result = subprocess.run([str(self.binary)], input=b'TSA_NATIVE\t1\t0\t0\n\x1aextra\n',
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')


if __name__ == '__main__':
    unittest.main()
