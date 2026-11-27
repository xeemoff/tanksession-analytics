# -*- coding: utf-8 -*-
"""Optional metadata is evidence-bound and cannot damage the battle journal."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src/res/scripts/client/gui/mods'))
from tanksession_analytics.core import normalize_result, validate_record
from tanksession_analytics.recorder import ResultRecorder
from tanksession_analytics.storage import BattleStore, PendingJournal
from tanksession_analytics.vehicles import metadata_from_vehicle_type


class VehicleType(object):
    compactDescr = 257
    id = (0, 1)
    level = 6
    classTag = 'mediumTank'
    tags = frozenset(['mediumTank', 'premium'])


def payload():
    return {'arenaUniqueID': 99, 'common': {'winnerTeam': 1, 'bonusType': 1, 'arenaTypeID': 65547},
            'personal': {42: {'typeCompDescr': 257, 'team': 1, 'damageDealt': 1000, 'xp': 500}}}


def context():
    return {'account_id': '88', 'player_vehicle_id': 42, 'vehicle_id': 'type:257',
            'vehicle_name': 'ussr:R04_T-34', 'vehicle_tier': 6,
            'vehicle_class': 'mediumTank', 'vehicle_nation': 'ussr'}


class MetadataTests(unittest.TestCase):
    def test_type_descriptor_is_required_and_cross_checks_nation_and_class(self):
        self.assertEqual(metadata_from_vehicle_type(VehicleType()), {
            'vehicle_id': 'type:257', 'vehicle_tier': 6,
            'vehicle_class': 'mediumTank', 'vehicle_nation': 'ussr'})
        unknown = VehicleType()
        unknown.compactDescr = 42
        self.assertEqual(metadata_from_vehicle_type(unknown), {})
        contradictory = VehicleType()
        contradictory.id = (1, 1)
        self.assertEqual(metadata_from_vehicle_type(contradictory), {})
        ambiguous = VehicleType()
        ambiguous.tags = ['heavyTank', 'mediumTank']
        self.assertIsNone(metadata_from_vehicle_type(ambiguous)['vehicle_class'])
        future = VehicleType()
        future.level = 12
        self.assertIsNone(metadata_from_vehicle_type(future)['vehicle_tier'])

    def test_normalization_accepts_only_identity_bound_captured_metadata(self):
        record = normalize_result(payload(), context(), 1700000000)
        self.assertEqual((record['vehicle_tier'], record['vehicle_class'], record['vehicle_nation']),
                         (6, 'mediumTank', 'ussr'))
        unbound = context()
        del unbound['vehicle_id']
        record = normalize_result(payload(), unbound, 1700000000)
        self.assertIsNone(record['vehicle_tier'])
        self.assertIsNone(record['vehicle_class'])
        # The nation is encoded in the verified personal type descriptor itself.
        self.assertEqual(record['vehicle_nation'], 'ussr')
        self.assertIsNone(record['map_label'])

    def test_validation_preserves_unknown_and_rejects_conflicting_metadata(self):
        record = normalize_result(payload(), context(), 1700000000)
        for field, invalid in (('vehicle_tier', True), ('vehicle_tier', 12),
                               ('vehicle_tier', '6'), ('vehicle_class', 'a guessed class'),
                               ('vehicle_nation', 'germany')):
            self.assertIsNone(validate_record(dict(record, **{field: invalid})))
        clean = validate_record(dict(record, vehicle_tier=None, vehicle_class=None,
                                     vehicle_nation=None, map_label=u'Название карты'))
        self.assertIsNotNone(clean)
        self.assertIsNone(clean['vehicle_tier'])
        self.assertEqual(clean['map_label'], u'Название карты')
        self.assertIsNone(validate_record(dict(clean, map=None)))

    def test_pending_restart_and_catalog_fill_missing_preserve_captured_values(self):
        folder = tempfile.mkdtemp(prefix='tanksession-metadata-')
        try:
            path = os.path.join(folder, 'battles.jsonl')
            pending_path = path + '.pending.jsonl'
            pending = PendingJournal(pending_path)
            pending.start(99, context(), 1700000000)
            pending = PendingJournal(pending_path)
            calls = []
            def enrich(record):
                calls.append(record)
                return {'vehicle_tier': 7, 'vehicle_class': 'heavyTank',
                        'map_label': u'Название карты', 'account_id': 'foreign', 'damage': 9999}
            recorder = ResultRecorder(BattleStore(path), pending, require_account=True,
                                      metadata_provider=enrich)
            status, record = recorder.receive(payload(), {'account_id': '88'}, 1700000001,
                                               confirmed_own=True)
            self.assertEqual(status, 'saved')
            self.assertEqual(len(calls), 1)
            restored = BattleStore(path).records[0]
            self.assertEqual(restored['vehicle_tier'], 6)
            self.assertEqual(restored['vehicle_class'], 'mediumTank')
            self.assertEqual(restored['map_label'], u'Название карты')
            self.assertEqual((restored['account_id'], restored['damage']), ('88', 1000))
            self.assertEqual(PendingJournal(pending_path).pending, {})
        finally:
            shutil.rmtree(folder)

    def test_failed_or_invalid_catalog_cannot_drop_primary_battle_or_cross_account(self):
        folder = tempfile.mkdtemp(prefix='tanksession-metadata-failure-')
        try:
            for index, invalid in enumerate(({'vehicle_tier': 999}, None)):
                def enrich(record):
                    if invalid is None:
                        raise RuntimeError('Unavailable catalog')
                    return invalid
                path = os.path.join(folder, '%d.jsonl' % index)
                recorder = ResultRecorder(BattleStore(path), require_account=True, metadata_provider=enrich)
                status, record = recorder.receive(payload(), {'account_id': '88', 'player_vehicle_id': 42},
                                                   1700000000)
                self.assertEqual((status, record['damage']), ('saved', 1000))
                self.assertIsNone(record['vehicle_tier'])
            pending = PendingJournal(os.path.join(folder, 'pending.jsonl'))
            pending.start(99, context(), 1700000000)
            def never_called(record):
                self.fail('Metadata was read for a conflicting account')
            recorder = ResultRecorder(BattleStore(os.path.join(folder, 'other.jsonl')), pending,
                                      require_account=True, metadata_provider=never_called)
            self.assertEqual(recorder.receive(payload(), {'account_id': '99'})[0], 'account_mismatch')
        finally:
            shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()
