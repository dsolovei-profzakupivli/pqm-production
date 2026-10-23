import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import auth_access
import server


class AdminOfficerLinkPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER,full_name TEXT)')
        self.con.execute("INSERT INTO authorized_officers VALUES(901,1,'Synthetic Officer')")
        auth_access.migrate(self.con)

    def tearDown(self):
        self.con.close()

    def save_admin(self, **values):
        auth_access.save_user(self.con, {'username': 'linked-admin', 'role_code': 'admin', **values}, 'bootstrap', {})

    def test_create_readback_and_unrelated_edits_preserve_officer_link_and_admin_role(self):
        self.save_admin(password='Synthetic-only-2026!', officer_id='901', display_name='Admin One')
        first = auth_access.users_payload(self.con)['items'][0]
        self.assertEqual(('admin', 901), (first['role'], first['officer_id']))
        self.save_admin(password='Synthetic-only-2027!', display_name='Admin Renamed')
        row = self.con.execute('SELECT role,officer_id,password_hash FROM auth_users WHERE username=?',
                               ('linked-admin',)).fetchone()
        self.assertEqual(('admin', 901), (row['role'], row['officer_id']))
        self.assertTrue(auth_access.verify_password('Synthetic-only-2027!', row['password_hash']))
        self.assertEqual(901, auth_access.users_payload(self.con)['items'][0]['officer_id'])
        self.assertEqual('Admin Renamed', self.con.execute(
            'SELECT display_name FROM user_preferences WHERE username=?', ('linked-admin',)).fetchone()[0])

    def test_admin_without_explicit_link_remains_unlinked(self):
        self.save_admin(password='Synthetic-only-2026!', display_name='Unlinked Admin')
        row = auth_access.users_payload(self.con)['items'][0]
        self.assertEqual(('admin', None), (row['role'], row['officer_id']))

    def test_invalid_or_conflicting_link_is_rejected(self):
        self.save_admin(password='Synthetic-only-2026!', officer_id=901)
        with self.assertRaises(ValueError):
            auth_access.save_user(self.con, {'username': 'second-admin', 'password': 'Synthetic-only-2026!',
                'role_code': 'admin', 'officer_id': 901}, 'bootstrap', {})
        with self.assertRaises(ValueError):
            auth_access.validated_officer_link(self.con, 'other', 'admin', '901x')
        self.con.execute('UPDATE authorized_officers SET active=0 WHERE id=901')
        with self.assertRaises(ValueError):
            auth_access.validated_officer_link(self.con, 'other', 'admin', 901)

    def test_link_does_not_change_admin_permissions(self):
        permissions = auth_access.effective(self.con, 'not-linked', 'admin')['permissions']
        self.save_admin(password='Synthetic-only-2026!', officer_id=901)
        self.assertEqual(permissions, auth_access.effective(self.con, 'linked-admin', 'admin')['permissions'])

    def test_modern_create_and_password_patch_round_trip_the_link(self):
        self.con.commit()
        request = type('Request', (), {})()
        request.path = '/api/admin/users'
        request.auth_user = 'bootstrap-admin'
        request.read_json = lambda: {'username': 'api-admin', 'password': 'Synthetic-only-2026!',
                                     'role': 'admin', 'officer_id': '901'}
        request.send_json = Mock(side_effect=lambda body, status=200: (status, body))
        with patch.object(server, 'db', return_value=self.con), \
             patch.object(server, 'configured_auth_accounts', return_value={}):
            server.Handler._do_POST(request)
        self.assertEqual(201, request.send_json.call_args.args[1])
        self.assertEqual(901, auth_access.users_payload(self.con)['items'][0]['officer_id'])
        request.path = '/api/admin/users/api-admin'
        request.read_json = lambda: {'password': 'Synthetic-only-2027!'}
        with patch.object(server, 'db', return_value=self.con), \
             patch.object(server, 'configured_auth_accounts', return_value={}):
            server.Handler._do_PATCH(request)
        self.assertEqual(901, auth_access.users_payload(self.con)['items'][0]['officer_id'])
        row = self.con.execute('SELECT role,password_hash FROM auth_users WHERE username=?', ('api-admin',)).fetchone()
        self.assertEqual('admin', row['role'])
        self.assertTrue(auth_access.verify_password('Synthetic-only-2027!', row['password_hash']))

    def test_ui_keeps_two_panels_and_admin_only_accounts_guard(self):
        test_path = Path(__file__).resolve()
        root = (test_path.parents[2] if test_path.parent.name == 'local_release_20260911'
                else test_path.parent)
        html = (root / 'index.html').read_text(encoding='utf-8')
        ui = (root / 'auth_ui.js').read_text(encoding='utf-8')
        app = (root / 'app.js').read_text(encoding='utf-8')
        self.assertIn('id="adminOfficersPanel"', html)
        self.assertIn('id="adminAccountsPanel" class="admin-panel" data-admin-only hidden', html)
        self.assertIn("currentMe?.role!=='admin'", ui)
        self.assertIn("return prior('officers')", ui)
        self.assertIn("canLink=isOfficer||accountRole==='admin'", app)


class AdminReviewAttributionTests(unittest.TestCase):
    def setUp(self):
        from validation.local_release_20260911 import test_formed_protocols
        test_formed_protocols.FormedProtocolTests.setUp(self)
        with server.db() as con:
            con.execute("INSERT INTO authorized_officers(id,full_name,role,active,created_at,updated_at) VALUES(901,'Synthetic Officer','УО',1,'test','test')")
            auth_access.save_user(con, {'username': 'review-admin', 'password': 'Synthetic-only-2026!',
                'role_code': 'admin', 'officer_id': 901}, 'bootstrap', {})
            con.execute("UPDATE application_fields SET protocol_decision='' WHERE submission_id='s0'")

    def tearDown(self):
        from validation.local_release_20260911 import test_formed_protocols
        test_formed_protocols.FormedProtocolTests.tearDown(self)

    def make_request(self, user, officer_id):
        request = type('Request', (), {})()
        request.path = '/api/applications/s0'
        request.auth_user = user
        request.auth_role = 'admin'
        request.auth_officer_id = officer_id
        request.read_json = lambda: {'protocol_decision': 'admit'}
        def send_json(body, status=200):
            request.response = (status, body)
            return request.response
        request.send_json = Mock(side_effect=send_json)
        return request

    def test_linked_admin_can_review_and_persists_officer_attribution(self):
        with server.db() as con:
            linked_id = con.execute("SELECT officer_id FROM auth_users WHERE username='review-admin'").fetchone()[0]
        self.assertEqual(901, linked_id)
        request = self.make_request('review-admin', linked_id)
        with patch.object(server, 'amcu_blocks_submission', return_value=False):
            server.Handler._do_PATCH(request)
        self.assertEqual(200, request.response[0])
        with server.db() as con:
            row = con.execute("SELECT protocol_decision,review_officer FROM application_fields WHERE submission_id='s0'").fetchone()
            self.assertEqual('admit', row['protocol_decision'])
            self.assertEqual(server.formatted_officer_name('Synthetic Officer'), row['review_officer'])

    def test_unlinked_admin_has_no_implicit_officer_assignment(self):
        request = self.make_request('unlinked-admin', None)
        with patch.object(server, 'amcu_blocks_submission', return_value=False):
            server.Handler._do_PATCH(request)
        self.assertEqual(409, request.response[0])
        with server.db() as con:
            row = con.execute("SELECT COALESCE(protocol_decision,''),COALESCE(review_officer,'') FROM application_fields WHERE submission_id='s0'").fetchone()
            self.assertEqual(('', ''), tuple(row))


if __name__ == '__main__':
    unittest.main()
