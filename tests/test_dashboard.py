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


if __name__ == '__main__':
    unittest.main()
