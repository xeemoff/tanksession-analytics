# -*- coding: utf-8 -*-
"""Identity boundaries through normalization, public snapshots and local files.

These scenarios exercise the public services together and run on CPython 2.7.
They use temporary files, never the user's journal or the game client.
"""
import copy
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'res', 'scripts', 'client', 'gui', 'mods'))
from tanksession_analytics.core import normalize_result, validate_record
from tanksession_analytics.presentation import build_snapshot
from tanksession_analytics.workspace import DEFAULT_PREFERENCES, Workspace

ACCOUNT = 'private-owner-account'
FOREIGN_ACCOUNT = 'private-foreign-account'
INTERNAL = 'ussr:R04_T-34'
TYPE_ID = 'type:257'
OTHER_TYPE_ID = 'type:513'
DISPLAY = u'Т-34'
LATEST_DISPLAY = u'Т-34; "новое имя"'
EPOCH = 1700000000
NOW = EPOCH + 10000


def row(index, **updates):
    value = {'schema': 1, 'account_id': ACCOUNT, 'arena_id': 'private-arena-%d' % index,
             'timestamp': EPOCH + index * 60, 'vehicle': INTERNAL,
             'mode': '1', 'outcome': 'win', 'damage': 1000, 'xp': 500,
             'xp_bonus': None if index % 4 == 3 else index * 10,
             'credits_net': (-100, 0, 250, None)[index % 4]}
    value.update(updates)
    return value


def command(action=None, **fields):
    request = {'protocol': 1, 'request_id': 'identity-check', 'vehicle': '',
               'window': 10, 'page': 0}
    if action is not None:
        request['action'] = action
    request.update(fields)
    return request


def aliased_history():
    # Old internal and localized names both have exact, same-account evidence.
    rows = [row(index, vehicle=INTERNAL if index < 8 else DISPLAY)
            for index in range(10)]
    rows.extend(row(index, vehicle=INTERNAL if index == 10 else DISPLAY,
                    vehicle_id=TYPE_ID) for index in range(10, 19))
    rows.append(row(19, vehicle=LATEST_DISPLAY, vehicle_id=TYPE_ID))
    return rows


def normalized(personal=None, context=None, entity_id=42):
    own = {'team': 1, 'damageDealt': 1000, 'xp': 500}
    own.update(personal or {})
    captured = {'account_id': '88', 'player_vehicle_id': entity_id,
                'vehicle_name': DISPLAY}
    captured.update(context or {})
    payload = {'arenaUniqueID': 99, 'common': {'winnerTeam': 1, 'bonusType': 1},
               'personal': {entity_id: own}}
    return normalize_result(payload, captured, observed_at=EPOCH)


class CoreIdentityIntegrationTests(unittest.TestCase):
    def test_optional_identity_survives_validation_and_invalid_ids_reject_the_record(self):
        record = normalized({'typeCompDescr': 257, 'vehicleName': INTERNAL},
                            {'vehicle_id': 'type:00000257', 'vehicle_name': INTERNAL})
        self.assertIsNotNone(record)
        self.assertEqual(record['vehicle_id'], TYPE_ID)
        self.assertEqual(record['vehicle'], INTERNAL)
        self.assertEqual(validate_record(record)['vehicle_id'], TYPE_ID)
        legacy = dict(record)
        del legacy['vehicle_id']
        self.assertIsNone(validate_record(legacy)['vehicle_id'])
        self.assertIsNone(validate_record(dict(record, vehicle_id=None))['vehicle_id'])
        for invalid in ('type:42', 'name:T-34', 257, True, []):
            self.assertIsNone(validate_record(dict(record, vehicle_id=invalid)), repr(invalid))
            self.assertIsNone(normalized({'typeCompDescr': 257},
                                         {'vehicle_id': invalid}), repr(invalid))

    def test_entity_id_is_never_a_type_and_internal_name_fallback_is_exact(self):
        # 257 is a syntactically valid type descriptor, but here it is an entity ID.
        plain = normalized(entity_id=257)
        self.assertIsNotNone(plain)
        self.assertIsNone(plain['vehicle_id'])
        numeric_vehicle_type = normalized({'vehicleType': 257}, entity_id=257)
        self.assertIsNone(numeric_vehicle_type['vehicle_id'])
        for label in (DISPLAY, 'T-34', 'ussr:R04_T-34 '):
            self.assertIsNone(normalized(context={'vehicle_name': label})['vehicle_id'])
        captured = normalized(context={'vehicle_name': INTERNAL})
        from_result = normalized({'vehicleName': INTERNAL}, {'vehicle_name': None})
        self.assertEqual(captured['vehicle_id'], 'name:' + INTERNAL)
        self.assertEqual(from_result['vehicle_id'], 'name:' + INTERNAL)

    def test_context_result_type_and_internal_names_cannot_conflict(self):
        cases = [
            ({'typeCompDescr': 513}, {'vehicle_id': TYPE_ID}),
            ({'typeCompDescr': 257}, {'vehicle_name': 'germany:G04_PzVI_Tiger_I'}),
            ({'typeCompDescr': 273}, {'vehicle_name': INTERNAL}),
            ({'typeCompDescr': 257, 'vehicleName': 'germany:G04_PzVI_Tiger_I'},
             {'vehicle_id': TYPE_ID}),
            ({'vehicleName': 'ussr:R01_IS'}, {'vehicle_name': INTERNAL}),
        ]
        for personal, context in cases:
            self.assertIsNone(normalized(personal, context), repr((personal, context)))


class SnapshotIdentityIntegrationTests(unittest.TestCase):
    def assert_private_identifiers_absent(self, snapshot):
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        for secret in (ACCOUNT, FOREIGN_ACCOUNT, 'private-arena-', 'account_id',
                       'arena_id', '_vehicle_ambiguous', 'Foreign private tank'):
            self.assertNotIn(secret, encoded)

    def test_same_type_and_exact_old_aliases_group_with_labels_in_every_public_section(self):
        own = aliased_history()
        rows = own + [row(80, account_id=FOREIGN_ACCOUNT, vehicle=INTERNAL,
                          vehicle_id=OTHER_TYPE_ID, damage=9999),
                      row(81, account_id=FOREIGN_ACCOUNT, vehicle='Foreign private tank')]
        original = copy.deepcopy(rows)
        goal = {'vehicle': INTERNAL, 'window': 10, 'target_avg_damage': 900}
        snapshot = build_snapshot(rows, ACCOUNT, command(vehicle=INTERNAL),
                                  goals=[goal], now=NOW)
        self.assertEqual(snapshot['selection']['vehicle'], TYPE_ID)
        self.assertEqual(snapshot['summary']['battles'], 20)
        self.assertEqual(snapshot['vehicles'], [
            {'name': TYPE_ID, 'label': LATEST_DISPLAY, 'battles': 20}])
        self.assertEqual(snapshot['coach']['status'], 'ready')
        self.assertEqual(snapshot['coach']['vehicle'], TYPE_ID)
        self.assertEqual(snapshot['coach']['vehicle_label'], LATEST_DISPLAY)
        self.assertEqual(snapshot['goals'][0]['vehicle'], TYPE_ID)
        self.assertEqual(snapshot['goals'][0]['vehicle_label'], LATEST_DISPLAY)
        self.assertEqual(snapshot['goals'][0]['status'], 'achieved')
        tank = snapshot['insights']['tanks'][0]
        self.assertEqual((tank['label'], tank['vehicle_label']), (TYPE_ID, LATEST_DISPLAY))
        for item in snapshot['history']:
            self.assertEqual(item['vehicle'], TYPE_ID)
            self.assertEqual(item['vehicle_label'], LATEST_DISPLAY)
        self.assertEqual(snapshot['quality']['invalid_records'], 0)
        self.assertEqual(rows, original)
        self.assert_private_identifiers_absent(snapshot)

    def test_reserved_legacy_label_is_escaped_once_through_every_snapshot_section(self):
        escaped = 'legacy:' + hashlib.sha256(TYPE_ID.encode('utf-8')).hexdigest()
        rows = [row(1, vehicle=TYPE_ID), row(2, vehicle=DISPLAY, vehicle_id=TYPE_ID)]
        snapshot = build_snapshot(rows, ACCOUNT, command(vehicle=escaped),
            goals=[{'vehicle': escaped, 'window': 10, 'target_avg_damage': 900}], now=NOW)
        self.assertEqual(set(item['name'] for item in snapshot['vehicles']),
                         set([escaped, TYPE_ID]))
        self.assertEqual(snapshot['selection']['vehicle'], escaped)
        self.assertEqual(snapshot['summary']['battles'], 1)
        self.assertEqual(snapshot['history'][0]['vehicle'], escaped)
        self.assertEqual(snapshot['history'][0]['vehicle_label'], TYPE_ID)
        self.assertEqual(snapshot['coach']['vehicle'], escaped)
        self.assertEqual(snapshot['coach']['vehicle_label'], TYPE_ID)
        self.assertEqual(snapshot['goals'][0]['vehicle'], escaped)
        self.assertEqual(snapshot['goals'][0]['vehicle_label'], TYPE_ID)
        self.assertEqual(snapshot['insights']['tanks'][0]['label'], escaped)
        self.assertEqual(snapshot['insights']['tanks'][0]['vehicle_label'], TYPE_ID)
        self.assert_private_identifiers_absent(snapshot)

    def test_ambiguous_old_bucket_cannot_award_coach_records_sessions_or_goals(self):
        rows = [row(index, vehicle='T-34', timestamp=EPOCH +
                    (7200 if index >= 10 else 0) + (index % 10) * 60)
                for index in range(20)]
        rows += [row(20, vehicle='T-34', vehicle_id=TYPE_ID, timestamp=EPOCH + 8000),
                 row(21, vehicle='T-34', vehicle_id=OTHER_TYPE_ID, timestamp=EPOCH + 8060)]
        snapshot = build_snapshot(rows, ACCOUNT, command(vehicle='T-34'),
            goals=[{'vehicle': 'T-34', 'window': 10, 'target_avg_damage': 500}], now=NOW)
        self.assertEqual(dict((item['name'], item['battles']) for item in snapshot['vehicles']),
                         {'T-34': 20, TYPE_ID: 1, OTHER_TYPE_ID: 1})
        labels = dict((item['name'], item['label']) for item in snapshot['vehicles'])
        self.assertEqual(len(set(labels.values())), 3)
        self.assertEqual(snapshot['selection']['vehicle'], 'T-34')
        self.assertEqual(snapshot['summary']['battles'], 20)
        self.assertEqual(snapshot['coach']['vehicle_label'], labels['T-34'])
        self.assertEqual(snapshot['goals'][0]['vehicle_label'], labels['T-34'])
        self.assertTrue(all(item['vehicle_label'] == labels['T-34']
                            for item in snapshot['history']))
        self.assertEqual(snapshot['coach']['status'], 'identity_ambiguous')
        self.assertIsNone(snapshot['coach']['comparison'])
        for field, value in snapshot['coach']['records'].items():
            if field in ('new_damage_record', 'new_window_record'):
                self.assertIs(value, False, field)
            else:
                self.assertIsNone(value, field)
        comparison = snapshot['sessions']['comparison']
        self.assertEqual(comparison['status'], 'identity_ambiguous')
        self.assertEqual((comparison['current_battles'], comparison['previous_battles']), (10, 10))
        for field in ('current_average', 'previous_average', 'current_median',
                      'previous_median', 'delta_average', 'delta_median'):
            self.assertIsNone(comparison[field], field)
        self.assertEqual(snapshot['goals'][0]['status'], 'identity_ambiguous')
        self.assert_private_identifiers_absent(snapshot)
        typed = build_snapshot(rows, ACCOUNT, command(vehicle=TYPE_ID), now=NOW)
        self.assertEqual(typed['summary']['battles'], 1)
        self.assertEqual(typed['coach']['status'], 'collecting')


class WorkspaceIdentityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='tanksession-identity-integration-')
        self.workspace = Workspace(self.folder)
        self.rows = aliased_history()

    def tearDown(self):
        shutil.rmtree(self.folder)

    @staticmethod
    def read_bytes(path):
        with open(path, 'rb') as stream:
            return stream.read()

    @staticmethod
    def write_json(path, value):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
        with open(path, 'wb') as stream:
            stream.write(raw)
        return raw

    def test_reading_old_profile_is_read_only_and_explicit_save_has_canonical_ids_and_backup(self):
        path = self.workspace._path(ACCOUNT)
        goal = {'vehicle': INTERNAL, 'window': 10, 'target_avg_damage': 900}
        profile = {'version': 1, 'preferences': dict(DEFAULT_PREFERENCES, vehicle=INTERNAL),
                   'goals': [goal]}
        original = self.write_json(path, profile)
        untouched = {}
        for filename in ('battles.jsonl', 'battles.jsonl.pending.jsonl', 'goals.json'):
            target = os.path.join(self.folder, filename)
            untouched[target] = self.write_json(target, [goal])
        snapshot = self.workspace.snapshot(self.rows, ACCOUNT, command('initialize'), now=NOW)
        self.assertEqual(snapshot['selection']['vehicle'], TYPE_ID)
        self.assertEqual(snapshot['workspace']['preferences']['vehicle'], TYPE_ID)
        self.assertEqual(snapshot['workspace']['goals'][0]['vehicle'], TYPE_ID)
        self.assertEqual(self.read_bytes(path), original)
        self.assertFalse(os.path.exists(path + '.bak'))
        preferences = dict(snapshot['workspace']['preferences'], tab='history')
        saved = self.workspace.snapshot(self.rows, ACCOUNT, command('save_preferences',
            request_id='explicit-save', preferences=preferences), now=NOW)
        self.assertEqual(saved['workspace']['operation']['code'], 'preferences_saved')
        persisted = json.loads(self.read_bytes(path).decode('utf-8'))
        self.assertEqual(persisted['version'], 2)
        self.assertEqual(persisted['preferences'], preferences)
        self.assertEqual(persisted['goals'], [dict(goal, vehicle=TYPE_ID)])
        self.assertEqual(self.read_bytes(path + '.bak'), original)
        reopened = Workspace(self.folder).snapshot(self.rows, ACCOUNT,
                                                   command('initialize'), now=NOW)
        self.assertEqual(reopened['selection']['vehicle'], TYPE_ID)
        self.assertEqual(reopened['workspace']['goals'][0]['vehicle'], TYPE_ID)
        for target, raw in untouched.items():
            self.assertEqual(self.read_bytes(target), raw)

    def test_old_literal_reserved_label_does_not_redirect_a_saved_profile_to_a_new_type(self):
        rows = [row(0, vehicle=TYPE_ID, damage=100),
                row(1, vehicle=DISPLAY, vehicle_id=TYPE_ID, damage=5000)]
        path = self.workspace._path(ACCOUNT)
        goal = {'vehicle': TYPE_ID, 'window': 10, 'target_avg_damage': 900}
        original = self.write_json(path, {
            'version': 1, 'preferences': dict(DEFAULT_PREFERENCES, vehicle=TYPE_ID),
            'goals': [goal]})
        old = self.workspace.snapshot(rows, ACCOUNT, command('initialize'), now=NOW)
        legacy_selector = old['selection']['vehicle']
        self.assertTrue(legacy_selector.startswith('legacy:'))
        self.assertEqual(old['summary']['avg_damage'], 100)
        self.assertEqual(old['workspace']['goals'][0]['vehicle'], legacy_selector)
        self.assertEqual(self.read_bytes(path), original)
        # An explicit new selection stores version 2 and remains a real ID on
        # reopen, even while that literal legacy label remains in the journal.
        preferences = dict(DEFAULT_PREFERENCES, vehicle=TYPE_ID)
        self.workspace.snapshot(rows, ACCOUNT, command('save_preferences',
            request_id='choose-real-type', preferences=preferences), now=NOW)
        persisted = json.loads(self.read_bytes(path).decode('utf-8'))
        self.assertEqual(persisted['version'], 2)
        self.assertEqual(persisted['goals'][0]['vehicle'], legacy_selector)
        reopened = Workspace(self.folder).snapshot(rows, ACCOUNT, command('initialize'), now=NOW)
        self.assertEqual(reopened['selection']['vehicle'], TYPE_ID)
        self.assertEqual(reopened['summary']['avg_damage'], 5000)
        self.assertEqual(self.read_bytes(path + '.bak'), original)

    def test_conflicting_legacy_targets_survive_reading_and_deleting_one_preserves_the_other(self):
        goals = [{'vehicle': INTERNAL, 'window': 10, 'target_avg_damage': 900},
                 {'vehicle': DISPLAY, 'window': 10, 'target_avg_damage': 2000},
                 {'vehicle': INTERNAL, 'window': 10, 'target_avg_damage': 9000,
                  'account_id': FOREIGN_ACCOUNT}]
        path = os.path.join(self.folder, 'goals.json')
        original = self.write_json(path, goals)

        def read_legacy():
            return json.loads(self.read_bytes(path).decode('utf-8'))

        snapshot = self.workspace.snapshot(self.rows, ACCOUNT, command('initialize'),
                                            legacy_goals=read_legacy, now=NOW)
        self.assertEqual(set((goal['vehicle'], goal['target_avg_damage'])
                             for goal in snapshot['workspace']['goals']),
                         set([(INTERNAL, 900), (DISPLAY, 2000)]))
        self.assertEqual(len(snapshot['goals']), 2)
        self.assertFalse(os.path.exists(self.workspace._path(ACCOUNT)))
        self.assertEqual(self.read_bytes(path), original)
        deleted = self.workspace.snapshot(self.rows, ACCOUNT, command('delete_goal',
            request_id='delete-only-internal-alias', goal={'vehicle': INTERNAL, 'window': 10}),
            legacy_goals=read_legacy, now=NOW)
        self.assertEqual(deleted['workspace']['operation']['code'], 'goal_deleted')
        self.assertEqual(len(deleted['workspace']['goals']), 1)
        self.assertEqual(deleted['workspace']['goals'][0]['target_avg_damage'], 2000)
        reopened = Workspace(self.folder).snapshot(self.rows, ACCOUNT, command('initialize'),
                                                    legacy_goals=read_legacy, now=NOW)
        self.assertEqual(len(reopened['workspace']['goals']), 1)
        self.assertEqual(reopened['workspace']['goals'][0]['vehicle'], TYPE_ID)
        self.assertEqual(reopened['workspace']['goals'][0]['target_avg_damage'], 2000)
        self.assertEqual(self.read_bytes(path), original)

    def test_csv_exports_all_own_rows_with_original_labels_identity_and_optional_economy(self):
        own = self.rows + [row(40, vehicle=u'КВ-1', vehicle_id=OTHER_TYPE_ID,
                              xp_bonus=0, credits_net=-200)]
        rows = own + [row(80, account_id=FOREIGN_ACCOUNT, vehicle='Foreign private tank',
                          vehicle_id=TYPE_ID)]
        snapshot = self.workspace.snapshot(rows, ACCOUNT, command('export_csv', page=2), now=NOW)
        operation = snapshot['workspace']['operation']
        self.assertEqual(operation['status'], 'exported')
        self.assertEqual(operation['rows'], len(own))
        self.assertEqual(len(snapshot['history']), 5)
        raw = self.read_bytes(os.path.join(self.folder, 'exports', operation['filename']))
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        text = raw.decode('utf-8-sig')
        # Python 2's csv reader requires UTF-8 byte strings; decode its output.
        lines = text.encode('utf-8').splitlines() if sys.version_info[0] < 3 else text.splitlines()
        exported = list(csv.DictReader(lines, delimiter=';'))
        if sys.version_info[0] < 3:
            exported = [dict((key.decode('utf-8'), value.decode('utf-8'))
                             for key, value in item.items()) for item in exported]
        self.assertEqual(len(exported), len(own))
        for source, actual in zip(own, exported):
            self.assertEqual(actual['vehicle'], source['vehicle'])
            self.assertEqual(actual['vehicle_id'], source.get('vehicle_id') or TYPE_ID)
            for metric in ('xp_bonus', 'credits_net'):
                value = source[metric]
                self.assertEqual(actual[metric], '' if value is None else str(value))
        for secret in (ACCOUNT, FOREIGN_ACCOUNT, 'private-arena-', 'account_id',
                       'arena_id', 'Foreign private tank'):
            self.assertNotIn(secret, text)


if __name__ == '__main__':
    unittest.main()
