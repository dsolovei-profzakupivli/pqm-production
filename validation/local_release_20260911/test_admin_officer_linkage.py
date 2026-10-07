"""Synthetic account linkage tests; no deployed databases or credentials."""
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock

import auth_access as a
import operational_tasks
import server
import test_formed_protocols as protocol_fixture


class AdminOfficerLinkageTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER,full_name TEXT)')
        self.c.executemany('INSERT INTO authorized_officers VALUES(?,?,?)', [(1,1,'СВІТЛАНА НАМЯСЕНКО'),(2,0,'Inactive'),(3,1,'Other')])
        a.migrate(self.c)

    def tearDown(self):
        self.c.close()

    def save(self, **changes):
        p = dict(username='s.namiasenko', role_code='admin', password='synthetic-password-only')
        p.update(changes)
        a.save_user(self.c, p, 'bootstrap', {})
        return self.c.execute('SELECT * FROM auth_users WHERE username=?', (p['username'],)).fetchone()

    def test_admin_without_link(self):
        row = self.save()
        self.assertEqual(row['role'], 'admin')
        self.assertIsNone(row['officer_id'])

    def test_admin_explicit_link_and_repeat_save(self):
        self.assertEqual(self.save(officer_id='1')['officer_id'], 1)
        self.assertEqual(self.save(display_name='Changed')['officer_id'], 1)
        self.assertEqual(self.save(officer_id=1)['role'], 'admin')
        self.assertEqual(a.users_payload(self.c)['items'][0]['officer_id'], 1)

    def test_explicit_clear_remains_allowed(self):
        self.save(officer_id=1)
        self.assertIsNone(self.save(officer_id=None)['officer_id'])

    def test_invalid_inactive_and_malformed_rejected(self):
        for value in (2, 999, 0, -1, True, False, 1.5, 'x', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.save(officer_id=value)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0], 0)

    def test_occupied_rejected(self):
        self.save(username='other', officer_id=1)
        with self.assertRaises(ValueError):
            self.save(officer_id=1)

    def test_inactive_account_does_not_occupy_link(self):
        self.save(username='other', officer_id=1, active=False)
        self.assertEqual(self.save(officer_id=1)['officer_id'], 1)

    def test_unique_index_still_guards_direct_writes(self):
        self.save(officer_id=1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("INSERT INTO auth_users VALUES('other','hash','admin',1,1,'c','u','creator',NULL)")

    def test_officer_path_still_requires_link(self):
        with self.assertRaises(ValueError):
            self.save(role_code='officer')
        self.assertEqual(self.save(role_code='officer', officer_id=1)['role'], 'officer')

    def test_no_display_name_automatic_link(self):
        self.assertIsNone(self.save(display_name='СВІТЛАНА НАМЯСЕНКО')['officer_id'])

    def test_permissions_unchanged(self):
        self.save()
        before = a.effective(self.c, 's.namiasenko', 'admin')['permissions']
        self.save(officer_id=1)
        self.assertEqual(before, a.effective(self.c, 's.namiasenko', 'admin')['permissions'])

    def test_manual_operational_actor_resolves_link_without_application_protocol(self):
        """Operational audit login maps to actual officer, not task assignment."""
        self.save(officer_id=1)
        self.c.executescript('''
          CREATE TABLE operational_task_qualifications(task_id,qualification_id,registry_contract_id);
          CREATE TABLE operational_task_qualification_decisions(task_id,qualification_id,registry_contract_id,decision,note,updated_at,updated_by);
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY,task_id,event_type,created_at,actor,old_value,new_value,metadata);
          INSERT INTO operational_task_qualifications VALUES('task','qualification','contract');
          INSERT INTO operational_task_qualification_decisions VALUES('task','qualification','contract','','','','');
        ''')
        operational_tasks.update_termination_decisions(self.c, 'task', [dict(qualification_id='qualification',registry_contract_id='contract',decision='exclude')], 's.namiasenko')
        actor = self.c.execute('SELECT actor FROM operational_task_events').fetchone()[0]
        self.assertEqual(actor, 's.namiasenko')
        self.assertEqual(self.c.execute('SELECT updated_by FROM operational_task_qualification_decisions').fetchone()[0], actor)
        self.assertEqual(server.canonical_officer_identity(self.c, actor), 'Світлана НАМЯСЕНКО')
        self.assertIsNone(self.c.execute("SELECT name FROM sqlite_master WHERE name='application_fields'").fetchone())

    def test_ui_both_paths_expose_and_preserve_admin_link(self):
        js = Path('app.js').read_text(encoding='utf-8')
        self.assertIn("canLink=isOfficer||role==='admin'", js)
        self.assertIn("['officer','admin'].includes(accountRole)", js)
        editor = Path('auth_ui.js').read_text(encoding='utf-8')
        self.assertIn("q('accessOfficer').value=u.officer_id||''", editor)
        self.assertIn("officer_id:q('accessOfficer').value||null", editor)
        self.assertIn("if(data.username){q('accessUser').value=data.username;q('accessUser').onchange()}", editor)


class AdminAttributionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = protocol_fixture.FormedProtocolTests()
        self.fixture.setUp()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute("DELETE FROM authorized_officers WHERE full_name='СВІТЛАНА НАМЯСЕНКО'")
            con.execute("INSERT INTO authorized_officers(id,full_name,role,active,created_at,updated_at) VALUES(901,'СВІТЛАНА НАМЯСЕНКО','УО',1,'now','now')")
            a.save_user(con, dict(username='s.namiasenko', role_code='admin', officer_id=901, password='synthetic-password-only'), 'bootstrap', {})
            con.execute("UPDATE application_fields SET protocol_decision='' WHERE submission_id='s0'")

    def tearDown(self):
        self.fixture.tearDown()

    def decide(self, officer_id=901):
        handler = object.__new__(server.Handler)
        handler.path = '/api/applications/s0'
        handler.auth_user = 's.namiasenko'
        handler.auth_role = 'admin'
        handler.auth_officer_id = officer_id
        handler.read_json = Mock(return_value={'protocol_decision':'admit'})
        handler.send_json = Mock()
        handler._do_PATCH()
        return handler

    def account_action(self, path, payload, method='PATCH'):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.auth_user = 'bootstrap'
        handler.auth_role = 'admin'
        handler.auth_officer_id = None
        handler.read_json = Mock(return_value=payload)
        handler.send_json = Mock()
        getattr(handler, '_do_' + method)()
        return handler

    def test_classic_editor_repeat_save_and_active_officer_validation(self):
        h = self.account_action('/api/admin/users/s.namiasenko', {'role':'admin','active':True})
        self.assertNotIn('error', h.send_json.call_args.args[0])
        with server.db() as con:
            self.assertEqual(con.execute("SELECT officer_id FROM auth_users WHERE username='s.namiasenko'").fetchone()[0], 901)
        for bad in (99999, True, False, 0, 'not-an-id'):
            h = self.account_action('/api/admin/users/s.namiasenko', {'officer_id':bad})
            self.assertEqual(h.send_json.call_args.args[1], 400)

    def test_classic_create_admin_optional_link_and_occupied_validation(self):
        h = self.account_action('/api/admin/users', {'username':'new.admin','password':'synthetic-password-only','role':'admin'}, 'POST')
        self.assertEqual(h.send_json.call_args.args[1], 201)
        h = self.account_action('/api/admin/users', {'username':'busy.admin','password':'synthetic-password-only','role':'admin','officer_id':901}, 'POST')
        self.assertEqual(h.send_json.call_args.args[1], 400)

    def test_modern_editor_endpoint_preserves_admin_link(self):
        h = self.account_action('/api/admin/users', {'username':'s.namiasenko','role_code':'admin','display_name':'Світлана НАМЯСЕНКО'}, 'POST')
        self.assertNotIn('error', h.send_json.call_args.args[0])
        with server.db() as con:
            row = con.execute("SELECT role,officer_id FROM auth_users WHERE username='s.namiasenko'").fetchone()
            self.assertEqual(tuple(row), ('admin',901))

    def test_canonical_identity_decision_audit_assignment_unchanged(self):
        with server.db() as con:
            self.assertEqual(server.canonical_officer_identity(con,'s.namiasenko',901), 'Світлана НАМЯСЕНКО')
        h = self.decide()
        self.assertNotIn('error', h.send_json.call_args.args[0])
        with server.db() as con:
            row = con.execute("SELECT review_officer,protocol_officer FROM application_fields WHERE submission_id='s0'").fetchone()
            self.assertEqual(tuple(row), ('Світлана НАМЯСЕНКО','Тетяна ФЕДЧЕНКО'))
            audit = con.execute("SELECT changed_by,new_value FROM audit_log WHERE submission_id='s0' AND field_name='review_officer'").fetchone()
            self.assertEqual(tuple(audit), ('s.namiasenko','Світлана НАМЯСЕНКО'))

    def test_unlinked_admin_guard_not_bypassed(self):
        with server.db() as con:
            con.execute("UPDATE auth_users SET officer_id=NULL WHERE username='s.namiasenko'")
        h = self.decide(None)
        self.assertEqual(h.send_json.call_args.args[1], 409)

    def test_known_separate_protocol_attribution_defect(self):
        """Document existing divergence, not an acceptance assertion for substitution."""
        self.decide()
        result = server.generate_protocol({'protocol_number':'100'}, 's.namiasenko','admin',901)
        with server.db() as con:
            row = con.execute('SELECT officer,created_by FROM formed_protocols WHERE id=?', (result['protocol_id'],)).fetchone()
            self.assertEqual(tuple(row), ('Тетяна ФЕДЧЕНКО','s.namiasenko'))
            self.assertNotEqual(row['officer'], 'Світлана НАМЯСЕНКО')
            audit = con.execute("SELECT changed_by FROM audit_log WHERE submission_id='s0' AND field_name='formed_protocol_created'").fetchone()
            self.assertEqual(audit['changed_by'], 's.namiasenko')

    def test_protocol_attribution_when_explicit_assignment_already_matches(self):
        with server.db() as con:
            con.execute("UPDATE application_fields SET protocol_officer='Світлана НАМЯСЕНКО' WHERE protocol_number='100'")
        self.decide()
        result = server.generate_protocol({'protocol_number':'100'}, 's.namiasenko','admin',901)
        with server.db() as con:
            row = con.execute('SELECT officer,created_by FROM formed_protocols WHERE id=?', (result['protocol_id'],)).fetchone()
            self.assertEqual(tuple(row), ('Світлана НАМЯСЕНКО','s.namiasenko'))
