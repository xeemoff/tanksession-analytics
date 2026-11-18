#!/usr/bin/env python3
"""Demo an early-exit result recovery without game files or an account.

Requires Python 3.9+. Runs with a fake client cache and a temporary folder.
Does NOT claim actual Lesta API compatibility.
"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.storage import BattleStore, PendingJournal
from tanksession_analytics.recorder import ResultRecorder
from tanksession_analytics.recovery import CacheRecovery
from tanksession_analytics.core import summarize


class FakeCache:
    def get(self, arena_id, callback):
        print('Simulated cache lookup: arena %s' % arena_id)
        callback(0, {
            'arenaUniqueID': arena_id, 'common': {'winnerTeam': 1},
            'personal': {42: {'team': 1, 'xp': 800, 'damageDealt': 2250}},
        })


def main():
    with tempfile.TemporaryDirectory() as folder:
        store = BattleStore(os.path.join(folder, 'battles.jsonl'))
        pending = PendingJournal(os.path.join(folder, 'pending.jsonl'))
        pending.start(12345, {'account_id': 7, 'player_vehicle_id': 42,
                              'vehicle_name': 'IS-7', 'team': 1}, 1795000000)
        print('Battle started; no result event was received.')
        print('Pending:', len(pending.pending), '| Saved:', len(store.records))
        collector = ResultRecorder(store, pending)
        recovery = CacheRecovery(pending, collector)
        recovery.poll(FakeCache(), account_id=7, now=1795000010)
        print('Pending:', len(pending.pending), '| Saved:', len(store.records))
        print('Summary:', summarize(store.records))
        print('This is a FAKE game event. A real client has not been tested.')


if __name__ == '__main__':
    main()
