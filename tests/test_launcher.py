import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from launch_dashboard import journal_for_game, main


class LauncherTests(unittest.TestCase):
    def test_game_selection_requires_marker_and_does_not_create_data(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                journal_for_game(folder)
            (Path(folder) / 'paths.xml').write_text('<paths/>', encoding='utf-8')
            journal = journal_for_game(folder)
            self.assertEqual(Path(journal).relative_to(folder).as_posix(),
                             'mods/configs/tanksession_analytics/battles.jsonl')
            self.assertFalse(Path(journal).exists())

    def test_browser_opens_only_after_successful_bind_and_server_is_closed(self):
        calls = []
        server = Mock(server_port=12345)
        server.serve_forever.side_effect = KeyboardInterrupt
        def bind(*args, **kwargs):
            calls.append('bound')
            return server
        def open_browser(url, **kwargs):
            calls.append(url)
            return True
        with patch('launch_dashboard.create_server', side_effect=bind), \
             patch('launch_dashboard.webbrowser.open', side_effect=open_browser), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--demo']), 0)
        self.assertEqual(calls, ['bound', 'http://127.0.0.1:12345/'])
        server.server_close.assert_called_once()

    def test_failed_bind_does_not_open_browser(self):
        with patch('launch_dashboard.create_server', side_effect=OSError), \
             patch('launch_dashboard.webbrowser.open') as browser, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--demo']), 1)
        browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
