import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import supplier_manual_classification as manual
import supplier_classification
import auth_access


class ManualClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.path = Path(self.tmp.name) / 'manual.sqlite3'
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript('''
          CREATE TABLE submissions(id TEXT PRIMARY KEY, supplier_code TEXT, supplier_name TEXT,
            raw_json TEXT, date_published TEXT);
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY);
          CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY);
          CREATE TABLE registry_contracts(supplier_code TEXT);
          CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT,active INTEGER);
          CREATE TABLE auth_user_roles(username TEXT,role_code TEXT);
          CREATE TABLE auth_roles(code TEXT,base_role TEXT,active INTEGER);
          CREATE TABLE auth_role_permissions(role_code TEXT,permission_key TEXT,allowed INTEGER);
          CREATE TABLE protected_business_data(code TEXT PRIMARY KEY,value TEXT);
          INSERT INTO authorized_officers VALUES(7,'\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430',1);
          INSERT INTO protected_business_data VALUES('00001234','untouched');
        ''')
        self.add_supplier('00001234', '\u0424\u041e\u041f \u0422\u0435\u0441\u0442\u043e\u0432\u0438\u0439', 'UA', '\u0424\u0456\u0437\u0438\u0447\u043d\u0430 \u043e\u0441\u043e\u0431\u0430 \u2013 \u043f\u0456\u0434\u043f\u0440\u0438\u0454\u043c\u0435\u0446\u044c')
        self.add_supplier('passport:\u0421\u0420 918414', '\u041f\u043e\u0441\u0442\u0430\u0447\u0430\u043b\u044c\u043d\u0438\u043a \u0431\u0435\u0437 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u043e\u0432\u0430\u043d\u043e\u0433\u043e \u0442\u0438\u043f\u0443', '', '')
        self.add_supplier('87654321', '\u0410\u0422 \u0422\u0435\u0441\u0442', 'UA', '\u0410\u043a\u0446\u0456\u043e\u043d\u0435\u0440\u043d\u0435 \u0442\u043e\u0432\u0430\u0440\u0438\u0441\u0442\u0432\u043e')
        manual.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def add_supplier(self, code, name, country, form):
        payload = {'tenderers': [{'identifier': {'id': code, 'legalName': name},
            'address': {'countryName': country} if country else {}, 'legalForm': form, 'name': name}]}
        self.con.execute('INSERT INTO submissions VALUES(?,?,?,?,?)',
                         (f'sub-{len(list(self.con.execute("SELECT 1 FROM submissions")))}', code,
                          name, json.dumps(payload, ensure_ascii=False), '2026-10-01'))
        self.con.execute('INSERT OR IGNORE INTO supplier_edr_profiles(supplier_code) VALUES(?)', (code,))
        self.con.commit()

    def decision(self, code, revision, subject, residency):
        return {'supplier_code': code, 'expected_revision': revision,
                'subject_type': subject, 'residency': residency}

    def save(self, code, subject, residency, revision=0, confirm=False):
        with self.con:
            return manual.save_many(self.con, [self.decision(code, revision, subject, residency)],
                actor='uo@example.test', officer_id=7, officer_name='\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430',
                confirm_replace=confirm)

    def effective(self, code):
        auto = supplier_classification.resolve(supplier_classification.build_index(self.con), code)
        return manual.apply_effective(auto, manual.current_record(self.con, code))

    def test_all_subject_types_route_only_to_supported_internal_groups(self):
        for subject in manual.SUBJECT_TYPES:
            group = manual.derive_group(subject, 'UA')
            self.assertIn(group, {'fop', 'legal_other', 'unresolved'})
            self.assertNotEqual(group, 'nonresident')
        self.assertEqual(manual.derive_group('individual_entrepreneur', 'UA'), 'fop')
        for subject in manual.LEGAL_OTHER_TYPES:
            self.assertEqual(manual.derive_group(subject, 'UA'), 'legal_other')
        self.assertEqual(manual.derive_group('legal_entity', 'nonresident'), 'nonresident')
        self.assertEqual(manual.derive_group('legal_entity', 'unknown'), 'unresolved')
        self.assertEqual(manual.derive_group('unknown', 'UA'), 'unresolved')

    def test_manual_override_persists_and_prozorro_refresh_does_not_remove_it(self):
        before = self.effective('passport:\u0421\u0420 918414')
        self.assertEqual(before['google_sheet_group'], 'unresolved')
        self.save('passport:\u0421\u0420 918414', 'individual_entrepreneur', 'UA')
        self.add_supplier('passport:\u0421\u0420 918414', '\u041e\u043d\u043e\u0432\u043b\u0435\u043d\u0430 \u043d\u0430\u0437\u0432\u0430 \u0437\u0430\u044f\u0432\u043a\u0438', 'UA', '')
        after = self.effective('passport:\u0421\u0420 918414')
        self.assertEqual(after['google_sheet_group'], 'fop')
        self.assertEqual(after['classification_source'], 'manual')
        self.assertEqual(after['manual_classification_revision'], 1)
        detail = manual.detail(supplier_classification.resolve(
            supplier_classification.build_index(self.con), 'passport:\u0421\u0420 918414'),
            dict(manual.current_record(self.con, 'passport:\u0421\u0420 918414')))
        self.assertEqual(detail['manual']['changed_officer_name'], '\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430')
        self.assertEqual(len(manual.history(self.con, 'passport:\u0421\u0420 918414')), 1)

        event = manual.history(self.con, 'passport:\u0421\u0420 918414')[0]
        self.assertEqual(event['old_value']['source'], 'automatic_v3')
        self.assertEqual(event['old_value']['google_group'], 'unresolved')
        self.assertEqual(event['new_value']['google_group'], 'fop')

    def test_override_maps_fop_and_legal_other_without_changing_auto_evidence(self):
        auto = supplier_classification.resolve(supplier_classification.build_index(self.con), '00001234')
        self.assertEqual(auto['subject_nature'], 'fop')
        self.save('00001234', 'branch', 'UA')
        result = self.effective('00001234')
        self.assertEqual(result['entity_type'], 'legal_entity')
        self.assertEqual(result['target_sheet'], '\u042e\u041e')
        self.assertEqual(result['automatic_subject_nature'], 'fop')
        self.assertEqual(result['effective_subject_type'], 'branch')
        self.assertEqual(result['google_sheet_group'], 'legal_other')
        self.assertEqual(self.con.execute("SELECT value FROM protected_business_data").fetchone()[0], 'untouched')

    def test_nonresident_and_unknown_are_blocked_from_both_existing_tabs(self):
        self.save('passport:\u0421\u0420 918414', 'other', 'nonresident')
        result = self.effective('passport:\u0421\u0420 918414')
        self.assertEqual(result['google_sheet_group'], 'nonresident')
        self.assertIsNone(result['target_sheet'])
        self.assertFalse(result['append_allowed'])
        self.assertEqual(manual.derive_group('unknown', 'UA'), 'unresolved')

    def test_cancel_restores_automatic_classification_and_keeps_tombstone_revision(self):
        code = '87654321'
        auto = self.effective(code)
        self.save(code, 'branch', 'UA')
        with self.con:
            result = manual.save_many(self.con, [{'supplier_code': code, 'expected_revision': 1}],
                actor='uo@example.test', officer_id=7, officer_name='\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430', cancel=True)
        restored = self.effective(code)
        self.assertEqual(restored['entity_type'], auto['entity_type'])
        self.assertEqual(restored['classification_source'], 'automatic_v3')
        row = manual.current_record(self.con, code)
        self.assertEqual(row['revision'], 2)
        self.assertEqual(row['is_active'], 0)
        self.assertEqual([entry['action'] for entry in manual.history(self.con, code)], ['cancel', 'set'])

    def test_existing_decision_requires_explicit_replacement_and_revision(self):
        code = '87654321'
        self.save(code, 'legal_entity', 'UA')
        with self.assertRaises(manual.ExistingManualDecision):
            self.save(code, 'branch', 'UA', revision=1)
        self.save(code, 'branch', 'UA', revision=1, confirm=True)
        self.assertEqual(self.effective(code)['effective_subject_type'], 'branch')
        self.assertEqual([entry['action'] for entry in manual.history(self.con, code)], ['change', 'set'])

    def test_bulk_preview_preserves_literal_codes_and_changes_only_selected(self):
        result = manual.preview_many(self.con, ['00001234', 'passport:\u0421\u0420 918414'], 'individual_entrepreneur', 'UA')
        self.assertEqual([item['supplier_code'] for item in result], ['00001234', 'passport:\u0421\u0420 918414'])
        choices = [self.decision(item['supplier_code'], item['expected_revision'], 'individual_entrepreneur', 'UA') for item in result]
        with self.con:
            manual.save_many(self.con, choices, actor='uo@example.test', officer_id=7,
                             officer_name='\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430')
        self.assertIsNone(manual.current_record(self.con, '87654321'))
        self.assertEqual(self.effective('00001234')['google_sheet_group'], 'fop')

    def test_stale_member_rejects_bulk_without_partial_write(self):
        decisions = [self.decision('00001234', 0, 'individual_entrepreneur', 'UA'),
                     self.decision('87654321', 0, 'branch', 'UA')]
        self.save('00001234', 'individual_entrepreneur', 'UA')
        with self.assertRaises(manual.RevisionConflict):
            with self.con:
                manual.save_many(self.con, decisions, actor='uo@example.test', officer_id=7,
                                 officer_name='\u0423\u043f\u043e\u0432\u043d\u043e\u0432\u0430\u0436\u0435\u043d\u0430 \u043e\u0441\u043e\u0431\u0430', confirm_replace=True)
        self.assertIsNone(manual.current_record(self.con, '87654321'))
        self.assertEqual(len(manual.history(self.con, '87654321')), 0)

    def test_same_decision_is_idempotent_and_does_not_add_audit_event(self):
        self.save('00001234', 'individual_entrepreneur', 'UA')
        self.save('00001234', 'individual_entrepreneur', 'UA', revision=1, confirm=True)
        self.assertEqual(len(manual.history(self.con, '00001234')), 1)
        self.assertEqual(manual.current_record(self.con, '00001234')['revision'], 1)

    def test_schema_adds_only_its_own_tables_idempotently(self):
        before = self.con.execute('SELECT value FROM protected_business_data').fetchone()[0]
        manual.ensure_schema(self.con)
        manual.ensure_schema(self.con)
        tables = {row[0] for row in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('supplier_manual_classifications', tables)
        self.assertIn('supplier_manual_classification_events', tables)
        self.assertEqual(self.con.execute('SELECT value FROM protected_business_data').fetchone()[0], before)

    def test_read_and_mutation_routes_use_separate_permissions(self):
        self.assertEqual(auth_access.permission_key('GET', '/api/supplier-classifications/passport%3ACR%20918414'),
                         'suppliers.read')
        self.assertEqual(auth_access.permission_key('POST', '/api/suppliers/passport%3ACR%20918414/classification'),
                         'suppliers.classification')
        self.assertEqual(auth_access.permission_key('POST', '/api/supplier-classifications/bulk/preview'),
                         'suppliers.classification')
        rights = auth_access.effective(self.con, 'officer@test', 'officer')['permissions']
        self.assertTrue(rights['suppliers.classification'])
        viewer_rights = auth_access.effective(self.con, 'viewer@test', 'viewer')['permissions']
        self.assertFalse(viewer_rights['suppliers.classification'])


if __name__ == '__main__':
    unittest.main()
