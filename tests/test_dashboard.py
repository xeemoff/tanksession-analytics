import copy
import csv
import io
import os
import sys
import unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from dashboard import render, export_csv


def row(i, vehicle='IS-7', account='local'):
    return {'arena_id': str(i), 'account_id': account, 'timestamp': 1720000000 + i*3600,
            'vehicle': vehicle, 'outcome': 'win', 'damage': 999, 'xp': 500}


class DashboardTests(unittest.TestCase):
    def test_renders_empty_dashboard(self):
        page = render([], source_label='demo')
        self.assertIn('TankSession', page)
        self.assertIn('Боёв пока нет', page)
        self.assertIn('Не хватает боёв', page)

    def test_escapes_player_controlled_text(self):
        item = row(1, '<script>alert(1)</script>')
        page = render([item], vehicle_filter='', source_label='<img src=x onerror=alert(1)>')
        self.assertNotIn('<script>', page)
        self.assertNotIn('<img', page)
        self.assertIn('&lt;script&gt;', page)

    def test_filters_account_and_window(self):
        page = render([row(1), row(2, account='alt')], account_filter='alt', window=30)
        self.assertIn('name="account"', page)
        self.assertIn('value="alt" selected', page)
        self.assertIn('value="30" selected', page)
        self.assertIn('href="/export.csv?', page)
        self.assertIn('Эффективность по танкам', page)

    def test_csv_only_selected_account(self):
        result = export_csv([row(1), row(2, account='alt')], account_filter='alt')
        parsed = list(csv.DictReader(io.StringIO(result.decode('utf-8-sig'))))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['account_id'], 'alt')
        self.assertEqual(parsed[0]['damage'], '999')

    def test_export_protects_against_formula_injection(self):
        result = export_csv([row(1, '=HYPERLINK("bad")')]).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", result)
        parsed = list(csv.DictReader(io.StringIO(result)))
        self.assertTrue(parsed[0]['vehicle'].startswith("'="))

    def test_vehicle_options_use_canonical_values_and_separate_source_labels(self):
        items = [dict(row(1, 'Т-34', 'A'), vehicle_id='type:257'),
                 row(2, 'Т-34', 'A'), dict(row(3, 'Other caption', 'A'), vehicle_id='type:257'),
                 dict(row(4, 'Private B caption', 'B'), vehicle_id='type:513')]
        original = copy.deepcopy(items)
        page = render(items, account_filter='A', vehicle_filter='Т-34')
        self.assertIn('<option value="type:257" selected>Т-34</option>', page)
        self.assertNotIn('<option value="type:513"', page)
        self.assertIn('vehicle=type%3A257', page)
        self.assertEqual(items, original)

    def test_csv_selector_keeps_original_labels_and_scoped_identity_column(self):
        items = [dict(row(1, 'First caption', 'A'), vehicle_id='type:257'),
                 row(2, 'First caption', 'A'), dict(row(3, 'Second caption', 'A'), vehicle_id='type:257'),
                 row(4, 'First caption', 'B')]
        original = copy.deepcopy(items)
        for key in ('type:257', 'First caption'):
            data = export_csv(items, vehicle_filter=key, account_filter='A').decode('utf-8-sig')
            parsed = list(csv.DictReader(io.StringIO(data)))
            self.assertEqual([item['vehicle'] for item in parsed],
                             ['First caption', 'First caption', 'Second caption'])
            self.assertEqual([item['vehicle_id'] for item in parsed], ['type:257'] * 3)
        self.assertEqual(items, original)

    def test_legacy_readonly_labels_are_retained_and_never_promoted_from_another_account(self):
        items = [dict(row(1, 'Shared', 'A'), vehicle_id='type:257'), row(2, 'Shared', 'local')]
        page = render(items, vehicle_filter='Shared', account_filter='local')
        self.assertIn('<option value="Shared" selected>Shared</option>', page)
        self.assertNotIn('<option value="type:257"', page)
        data = export_csv(items, vehicle_filter='Shared', account_filter='local').decode('utf-8-sig')
        parsed = list(csv.DictReader(io.StringIO(data)))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['vehicle_id'], '')

    def test_ambiguous_legacy_selection_keeps_history_without_period_comparison(self):
        items = ([row(i, 'Shared', 'A') for i in range(1, 21)]
                 + [dict(row(i, 'Shared', 'A'), vehicle_id='type:257') for i in range(21, 41)]
                 + [dict(row(41, 'Shared', 'A'), vehicle_id='type:513')])
        original = copy.deepcopy(items)
        page = render(items, vehicle_filter='Shared', account_filter='A')
        self.assertIn('<option value="Shared" selected>Shared · старая запись</option>', page)
        self.assertIn('<option value="type:257">Shared · #257</option>', page)
        self.assertIn('<option value="type:513">Shared · #513</option>', page)
        self.assertIn('Название связано с разной техникой', page)
        self.assertIn('Старая история сохранена', page)
        self.assertNotIn('class="stats compare"', page)
        self.assertNotIn('изменение:', page)
        data = export_csv(items, vehicle_filter='Shared', account_filter='A').decode('utf-8-sig')
        self.assertEqual(len(list(csv.DictReader(io.StringIO(data)))), 20)
        confirmed = render(items, vehicle_filter='type:257', account_filter='A')
        self.assertIn('class="stats compare"', confirmed)
        self.assertNotIn('Название связано с разной техникой', confirmed)
        self.assertEqual(items, original)


if __name__ == '__main__':
    unittest.main()
