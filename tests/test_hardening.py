import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client/gui/mods'))
sys.path.insert(0, str(ROOT / 'tools'))
from tanksession_analytics.storage import discover_game_root, default_path
from tanksession_analytics.analytics import rolling_damage, sort_records
from tanksession_analytics.core import summarize
from tanksession_analytics.goals import validate_goals, evaluate_goals
from maintain_data import inspect, compact


class RootTests(unittest.TestCase):
    def test_selects_game_root_from_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'paths.xml').write_text('<paths/>', encoding='utf-8')
            self.assertEqual(discover_game_root(cwd=temp), temp)
            self.assertTrue(default_path(game_root=temp).endswith('battles.jsonl'))

    def test_resmgr_parent_win64(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'paths.xml').write_text('<paths/>', encoding='utf-8')
            bin_dir = Path(temp, 'win64')
            bin_dir.mkdir()
            self.assertEqual(discover_game_root(cwd='/does/not/exist',
                                               app_directory=str(bin_dir)), temp)

    def test_rejects_unverified_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(IOError):
                discover_game_root(cwd=temp)


class RollingTests(unittest.TestCase):
    def test_optimized_equals_reference(self):
        rng = random.Random(416)
        for n in (10, 12, 30, 101, 400):
            rows = [{'arena_id': str(i), 'timestamp': 1700000000 + i,
                     'damage': None if rng.randrange(5) == 0 else rng.randrange(7000)}
                    for i in range(n)]
            for window in (10, 30, 100):
                original = []
                ordered = sort_records(rows)
                for end in range(window, len(ordered) + 1):
                    stats = summarize(ordered[end - window:end])
                    known = stats['damage_samples']
                    minimum = (7 * window + 9) // 10
                    original.append((end, stats['avg_damage'] if known >= minimum else None, known))
                self.assertEqual(rolling_damage(rows, window=window), original[-80:])


class GoalTests(unittest.TestCase):
    def test_progress_and_achievement(self):
        goals = validate_goals([{'vehicle': 'IS-7', 'target_avg_damage': 2000, 'window': 10}])
        rows = [{'arena_id': str(i), 'timestamp': 1700000000 + i,
                 'vehicle': 'IS-7', 'damage': 2500} for i in range(9)]
        self.assertEqual(evaluate_goals(rows, goals)[0]['status'], 'in_progress')
        rows.append({'arena_id': '10', 'timestamp': 1700000020,
                     'vehicle': 'IS-7', 'damage': 2500})
        self.assertEqual(evaluate_goals(rows, goals)[0]['status'], 'achieved')
        for row in rows[:4]:
            row['damage'] = None
        self.assertEqual(evaluate_goals(rows, goals)[0]['status'], 'insufficient_data')

    def test_invalid_targets_fail_closed(self):
        for invalid in ({}, [{'vehicle': 'x', 'window': 0, 'target_avg_damage': 1}],
                        [{'vehicle': '=FORMULA', 'window': 10, 'target_avg_damage': -1}]):
            with self.assertRaises(ValueError):
                validate_goals(invalid)


class MaintenanceTests(unittest.TestCase):
    def test_compaction_preserves_first_unique_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp, 'battles.jsonl')
            rows = [{'arena_id': '1', 'account_id': 'A', 'timestamp': 1700000000,
                     'damage': 1000},
                    {'arena_id': '1', 'account_id': 'A', 'timestamp': 1700000000,
                     'damage': 2000},
                    {'arena_id': '2', 'account_id': 'A', 'timestamp': 1700000001,
                     'damage': 3000}]
            journal.write_bytes(b''.join((json.dumps(r) + '\n').encode() for r in rows) + b'{garbage}\n')
            before = inspect(str(journal))
            self.assertEqual(before['valid_unique'], 2)
            self.assertEqual(before['malformed'], 1)
            info = compact(str(journal))
            self.assertEqual(info['records'], 2)
            self.assertEqual(inspect(str(journal))['lines'], 2)
            self.assertEqual(len(list(Path(temp).glob('battles.jsonl.backup-*'))), 1)
            self.assertEqual(inspect(info['backup'])['lines'], 4)

    def test_does_not_compact_a_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            real = Path(temp, 'data.jsonl')
            real.write_text('', encoding='utf-8')
            link = Path(temp, 'link.jsonl')
            try:
                link.symlink_to(real)
            except (NotImplementedError, OSError):
                self.skipTest('No symlink support')
            with self.assertRaises(ValueError):
                compact(str(link))

class WebCacheTests(unittest.TestCase):
    def test_cache_invalidates_after_change(self):
        from dashboard import CachedJournal, render, load_goals
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp, 'battles.jsonl')
            cache = CachedJournal(str(journal))
            self.assertEqual(cache.records(), [])
            journal.write_text('{"arena_id":"1","timestamp":1700000000}\n', encoding='utf-8')
            self.assertEqual(len(cache.records()), 1)
            self.assertEqual(len(cache.records()), 1)
            journal.write_text(journal.read_text() + '{"arena_id":"2","timestamp":1700000001}\n', encoding='utf-8')
            self.assertEqual(len(cache.records()), 2)
            self.assertIn('Персональные цели', render(cache.records()))
            goals_path = Path(temp, 'goals.json')
            goals_path.write_text('[{"vehicle":"IS-7","target_avg_damage":2500,"window":10}]')
            self.assertEqual(len(load_goals(str(goals_path))), 1)
