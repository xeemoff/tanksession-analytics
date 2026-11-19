import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from diagnose_log import summarize_log


class DiagnosticsTests(unittest.TestCase):
    def test_revision_and_paused_states_have_dedicated_counters(self):
        data = summarize_log([
            '[TankSession] Updated battle: complete',
            '[TankSession] Battle result conflict: known fields differ',
            '[TankSession] Collection paused: replay status unavailable',
            '[TankSession] Account identity unavailable',
        ])
        self.assertEqual(data['battle_updated'], 1)
        self.assertEqual(data['battle_conflict'], 1)
        self.assertEqual(data['replay_api_unavailable'], 1)
        self.assertEqual(data['identity_unavailable'], 1)
        self.assertEqual(data['other_mod_messages'], 0)

    def test_count_and_not_echo_sensitive_values(self):
        lines = [
            'INFO: [TankSession] Started; local data path: C:/Users/User/private.jsonl',
            'INFO: [TankSession] Staged own battle for delayed-result recovery',
            'INFO: [TankSession] Saved battle: 9223372036854775807',
            'INFO: [TankSession] Skipped battle due to account identity: account_mismatch',
            'INFO: [TankSession] Startup failed: private@example.com',
            'Other mod name and user ID 12345',
        ]
        data = summarize_log(lines)
        self.assertEqual(data['mod_started'], 1)
        self.assertEqual(data['battle_staged'], 1)
        self.assertEqual(data['battle_saved'], 1)
        self.assertEqual(data['account_mismatch'], 1)
        self.assertEqual(data['startup_error'], 1)
        self.assertNotIn('9223372036854775807', str(data))
        self.assertNotIn('private@example.com', str(data))
        self.assertNotIn('C:/Users', str(data))


if __name__ == '__main__':
    unittest.main()
