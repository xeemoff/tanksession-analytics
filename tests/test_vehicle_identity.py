# -*- coding: utf-8 -*-
"""Vehicle selectors, account boundaries and append-only identity migration."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics import storage
from tanksession_analytics.storage import BattleStore, PendingJournal
from tanksession_analytics.vehicles import (
    identity_from_type_descr, identity_from_internal_name, normalize_vehicle_id,
    resolve_records, resolve_selector, selector_for, revision_identity,
)

INTERNAL = 'ussr:R04_T-34'
NAME_ID = 'name:' + INTERNAL
TYPE_ID = 'type:257'


def row(**updates):
    value = {'schema': 1, 'account_id': 'A', 'arena_id': '99',
             'timestamp': 1720000000, 'vehicle': INTERNAL, 'mode': '1',
             'outcome': 'win', 'damage': 1000, 'xp': 550}
    value.update(updates)
    return value


class VehicleIdentityTests(unittest.TestCase):
    def test_descriptor_is_type_not_entity_number(self):
        self.assertEqual(identity_from_type_descr(257), TYPE_ID)
        self.assertEqual(identity_from_type_descr('00000257'), TYPE_ID)
        self.assertEqual(identity_from_type_descr(1), 'type:1')
        maximum = (65535 << 8) + (11 << 4) + 1
        self.assertEqual(identity_from_type_descr(maximum), 'type:%d' % maximum)
        for value in (None, True, False, 0, -1, 42, 258, 257.0, 257.5,
                      (12 << 4) + 1, (1 << 24) + 1, '257x', '2.57e2',
                      '+257', [], {}, 10 ** 100):
            self.assertIsNone(identity_from_type_descr(value), repr(value))

    def test_internal_name_is_exact_and_never_a_localized_guess(self):
        self.assertEqual(identity_from_internal_name(INTERNAL), NAME_ID)
        self.assertEqual(identity_from_internal_name('usa:A01_T1_Cunningham'),
                         'name:usa:A01_T1_Cunningham')
        for value in ('T-34', u'Т-34', 'IS-7', 'unknown', 'ussr', 'russia:R04_T-34',
                      'USSR:R04_T-34', 'ussr:R04_T-34\n', ' ussr:R04_T-34',
                      'ussr:../R04_T-34', 'ussr:two tanks', 'ussr:' + 'R' * 200,
                      None, 257, True, b'ussr:\xff'):
            self.assertIsNone(identity_from_internal_name(value), repr(value))
        self.assertNotEqual(identity_from_internal_name(INTERNAL),
                            identity_from_internal_name('ussr:R04_t-34'))

    def test_explicit_identity_has_its_own_namespace(self):
        self.assertEqual(normalize_vehicle_id('type:00000257'), TYPE_ID)
        self.assertEqual(normalize_vehicle_id(NAME_ID), NAME_ID)
        for value in (257, '257', INTERNAL, 'T-34', 'type:42', 'type:true',
                      'name:T-34', 'legacy:257', [], None):
            self.assertIsNone(normalize_vehicle_id(value), repr(value))

    def test_projection_is_read_only_and_account_scoped(self):
        records = [row(), row(account_id='B', arena_id='100', vehicle_id=TYPE_ID),
                   row(account_id='local', arena_id='101')]
        original = json.dumps(records, sort_keys=True)
        own = resolve_records(records, 'A')
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]['vehicle_id'], NAME_ID)
        own[0]['damage'] = 0
        self.assertEqual(json.dumps(records, sort_keys=True), original)
        for account in (None, 'local', 'unknown', False, 0):
            self.assertEqual(resolve_records(records, account), [])

    def test_exact_internal_name_evidence_promotes_only_within_account(self):
        records = [row(), row(arena_id='100', vehicle_id=TYPE_ID),
                   row(arena_id='101', vehicle='T-34', vehicle_id=TYPE_ID),
                   row(arena_id='102', vehicle='T-34'),
                   row(account_id='B', vehicle='T-34')]
        own = resolve_records(records, 'A')
        self.assertEqual([value['vehicle_id'] for value in own], [TYPE_ID] * 4)
        self.assertIsNone(resolve_records(records, 'B')[0]['vehicle_id'])
        self.assertEqual(own[0]['vehicle'], INTERNAL)

    def test_conflicting_internal_mapping_keeps_legacy_name_separate(self):
        records = [row(), row(arena_id='100', vehicle_id=TYPE_ID),
                   row(arena_id='101', vehicle_id='type:513')]
        own = resolve_records(records, 'A')
        self.assertEqual([value['vehicle_id'] for value in own],
                         [NAME_ID, TYPE_ID, 'type:513'])
        self.assertEqual(resolve_selector(INTERNAL, records), NAME_ID)

    def test_wrong_nation_cannot_establish_an_internal_mapping(self):
        own = resolve_records([row(), row(arena_id='100', vehicle_id='type:273')], 'A')
        self.assertEqual(own[0]['vehicle_id'], NAME_ID)
        self.assertEqual(own[1]['vehicle_id'], 'type:273')

    def test_similar_names_and_unknown_are_not_alias_evidence(self):
        records = [row(vehicle='IS-7', vehicle_id=TYPE_ID),
                   row(arena_id='100', vehicle=u'ИС-7'),
                   row(arena_id='101', vehicle='is-7'),
                   row(arena_id='102', vehicle='unknown', vehicle_id=TYPE_ID),
                   row(arena_id='103', vehicle='unknown')]
        own = resolve_records(records, 'A')
        self.assertEqual([value['vehicle_id'] for value in own],
                         [TYPE_ID, None, None, TYPE_ID, None])

    def test_two_known_types_do_not_absorb_an_ambiguous_display_label(self):
        records = [row(vehicle='T-34'), row(arena_id='100', vehicle='T-34', vehicle_id=TYPE_ID),
                   row(arena_id='101', vehicle='T-34', vehicle_id='type:513')]
        own = resolve_records(records, 'A')
        self.assertIsNone(own[0]['vehicle_id'])
        self.assertEqual(resolve_selector('T-34', own), 'T-34')
        self.assertEqual(len(set(selector_for(value) for value in own)), 3)

    def test_reserved_legacy_label_and_real_identity_have_separate_selectors(self):
        records = [row(vehicle=TYPE_ID), row(arena_id='100', vehicle='T-34', vehicle_id=TYPE_ID)]
        own = resolve_records(records, 'A')
        escaped = selector_for(own[0])
        self.assertTrue(escaped.startswith('legacy:'))
        self.assertEqual(len(escaped), 71)
        self.assertNotEqual(escaped, selector_for(own[1]))
        self.assertEqual(resolve_selector(TYPE_ID, own), TYPE_ID)
        self.assertEqual(resolve_selector(escaped, own), escaped)
        self.assertEqual(resolve_selector(TYPE_ID, [records[0]]), escaped)
        for label in (NAME_ID, 'legacy:abc', 'legacy:' + 'x' * 240):
            self.assertEqual(len(selector_for(row(vehicle=label))), 71)

    def test_saved_alias_and_name_id_resolve_to_a_single_current_selector(self):
        records = [row(vehicle_id=TYPE_ID),
                   row(arena_id='100', vehicle='T-34', vehicle_id=TYPE_ID)]
        self.assertEqual(resolve_selector(INTERNAL, records), TYPE_ID)
        self.assertEqual(resolve_selector(NAME_ID, records), TYPE_ID)
        self.assertEqual(resolve_selector('T-34', records), TYPE_ID)
        self.assertEqual(resolve_selector('257', records), '257')
        self.assertEqual(resolve_selector('', records), '')
        mixed = records + [row(account_id='B', vehicle='T-34', vehicle_id='type:513')]
        self.assertEqual(resolve_selector('T-34', mixed), 'T-34')

    def test_numeric_identity_is_not_replaced_by_another_numeric_identity(self):
        with self.assertRaises(ValueError):
            revision_identity(row(vehicle_id=TYPE_ID), row(vehicle_id='type:513'))

    def test_name_promotion_requires_same_known_battle_and_agreeing_names(self):
        old = row(vehicle_id=NAME_ID)
        new = row(vehicle='T-34', vehicle_id=TYPE_ID)
        self.assertEqual(revision_identity(old, new), (TYPE_ID, True))
        for patch in ({'account_id': 'B'}, {'arena_id': '100'},
                      {'vehicle_id': 'type:273'}, {'vehicle': 'ussr:R01_IS'}):
            different = dict(new, **patch)
            with self.assertRaises(ValueError):
                revision_identity(old, different)
        with self.assertRaises(ValueError):
            revision_identity(dict(old, account_id='local'), dict(new, account_id='local'))


class VehicleJournalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='tanksession-identity-')
        self.path = os.path.join(self.folder, 'battles.jsonl')

    def tearDown(self):
        shutil.rmtree(self.folder)

    def read_bytes(self):
        with open(self.path, 'rb') as stream:
            return stream.read()

    def test_old_jsonl_is_not_rewritten_when_projecting_or_reopening(self):
        original = (json.dumps(row(), sort_keys=True) + '\n').encode('utf-8')
        with open(self.path, 'wb') as stream:
            stream.write(original)
        store = BattleStore(self.path)
        projected = resolve_records(store.records, 'A')
        self.assertEqual(projected[0]['vehicle_id'], NAME_ID)
        self.assertIsNone(store.records[0].get('vehicle_id'))
        self.assertEqual(self.read_bytes(), original)
        self.assertIsNone(BattleStore(self.path).records[0].get('vehicle_id'))
        self.assertEqual(self.read_bytes(), original)

    def test_explicit_identity_appends_revision_preserving_known_numbers_and_label(self):
        store = BattleStore(self.path)
        self.assertEqual(store.upsert(row()), 'saved')
        original = self.read_bytes()
        self.assertEqual(store.upsert(row(vehicle='T-34', vehicle_id=TYPE_ID,
                                          timestamp=1720000500, assistance_track=50)), 'updated')
        self.assertTrue(self.read_bytes().startswith(original))
        reopened = BattleStore(self.path)
        self.assertEqual(len(reopened.records), 1)
        record = reopened.records[0]
        self.assertEqual(record['vehicle_id'], TYPE_ID)
        self.assertEqual(record['vehicle'], INTERNAL)
        self.assertEqual((record['damage'], record['xp'], record['timestamp']),
                         (1000, 550, 1720000000))
        self.assertEqual(record['assistance_track'], 50)
        self.assertEqual(reopened.diagnostics['lines'], 2)
        self.assertEqual(reopened.diagnostics['revisions'], 1)

    def test_name_identity_promotes_and_later_alias_does_not_erase_original_label(self):
        store = BattleStore(self.path)
        store.upsert(row(vehicle_id=NAME_ID))
        self.assertEqual(store.upsert(row(vehicle_id=TYPE_ID, vehicle=u'Т-34')), 'updated')
        self.assertEqual(store.upsert(row(vehicle_id=TYPE_ID, vehicle='T-34', assistance_radio=0)), 'updated')
        record = BattleStore(self.path).records[0]
        self.assertEqual((record['vehicle_id'], record['vehicle']), (TYPE_ID, INTERNAL))
        self.assertEqual(record['assistance_radio'], 0)

    def test_legacy_free_label_can_be_anchored_only_by_the_exact_battle(self):
        store = BattleStore(self.path)
        store.upsert(row(vehicle='old localized name'))
        store.upsert(row(arena_id='100', vehicle='unrelated old label'))
        self.assertEqual(store.upsert(row(vehicle_id=TYPE_ID, vehicle='current label')), 'updated')
        own = resolve_records(BattleStore(self.path).records, 'A')
        self.assertEqual(own[0]['vehicle_id'], TYPE_ID)
        self.assertIsNone(own[1]['vehicle_id'])
        self.assertEqual(own[0]['vehicle'], 'old localized name')

    def test_identity_conflict_rejects_whole_revision_and_preserves_missing_metrics(self):
        store = BattleStore(self.path)
        store.upsert(row(vehicle_id=TYPE_ID, xp=None))
        original = self.read_bytes()
        self.assertEqual(store.upsert(row(vehicle_id='type:513', xp=550)), 'conflict')
        self.assertEqual(self.read_bytes(), original)
        self.assertEqual(store.records[0]['vehicle_id'], TYPE_ID)
        self.assertIsNone(store.records[0]['xp'])

    def test_metric_conflict_cannot_commit_an_identity_promotion(self):
        store = BattleStore(self.path)
        store.upsert(row(vehicle_id=NAME_ID))
        original = self.read_bytes()
        self.assertEqual(store.upsert(row(vehicle_id=TYPE_ID, damage=2000)), 'conflict')
        self.assertEqual(self.read_bytes(), original)
        self.assertEqual(store.records[0]['vehicle_id'], NAME_ID)
        self.assertEqual(store.records[0]['damage'], 1000)

    def test_other_account_never_enriches_an_old_accounts_identity(self):
        store = BattleStore(self.path)
        store.upsert(row())
        self.assertEqual(store.upsert(row(account_id='B', vehicle_id=TYPE_ID)), 'saved')
        self.assertIsNone(store.records[0].get('vehicle_id'))
        self.assertEqual(store.records[1]['vehicle_id'], TYPE_ID)
        self.assertEqual(resolve_records(store.records, 'A')[0]['vehicle_id'], NAME_ID)

    def test_failed_durable_revision_does_not_advance_identity(self):
        store = BattleStore(self.path)
        store.upsert(row())
        original = self.read_bytes()
        previous_append = storage._durable_append
        def fail(path, record):
            raise IOError('simulated identity write failure')
        storage._durable_append = fail
        try:
            with self.assertRaises(IOError):
                store.upsert(row(vehicle_id=TYPE_ID))
        finally:
            storage._durable_append = previous_append
        self.assertIsNone(store.records[0].get('vehicle_id'))
        self.assertEqual(self.read_bytes(), original)
        self.assertEqual(store.diagnostics['lines'], 1)

    def test_pending_preserves_valid_identity_and_omits_invalid_identity(self):
        path = self.path + '.pending.jsonl'
        pending = PendingJournal(path)
        pending.start('99', {'account_id': 'A', 'vehicle_id': TYPE_ID,
                             'vehicle_name': INTERNAL}, 1720000000)
        pending.start('100', {'account_id': 'A', 'vehicle_id': 'type:42'}, 1720000000)
        reopened = PendingJournal(path)
        self.assertEqual(reopened.context('99')['vehicle_id'], TYPE_ID)
        self.assertNotIn('vehicle_id', reopened.context('100'))

    def test_late_xp_bonus_is_fill_missing_and_conflicts_do_not_replace_it(self):
        store = BattleStore(self.path)
        store.upsert(row())
        self.assertEqual(store.upsert(row(xp_bonus=50)), 'updated')
        self.assertEqual(store.upsert(row(xp_bonus=70)), 'conflict')
        self.assertEqual(BattleStore(self.path).records[0]['xp_bonus'], 50)


if __name__ == '__main__':
    unittest.main()
