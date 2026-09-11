import sqlite3
import io
import unittest
from unittest.mock import patch, Mock
import auth_access as a

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER,full_name TEXT)')
        self.c.execute("INSERT INTO authorized_officers VALUES(1,1,'Fixture Officer')")
        a.migrate(self.c)
    def tearDown(self):self.c.close()
    def test_additive_idempotent(self):
        self.c.execute("INSERT INTO user_preferences(username,display_name,updated_at) VALUES('legacy','Keep','today')")
        self.c.execute("INSERT INTO chat_threads(title,is_group,created_by,created_at,updated_at) VALUES('Keep',0,'legacy','today','today')")
        self.c.execute("INSERT INTO chat_messages(chat_id,sender_username,body,created_at) VALUES(1,'legacy','Keep','today')")
        a.migrate(self.c)
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_users').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT display_name FROM user_preferences').fetchone()[0],'Keep')
        self.assertEqual(self.c.execute('SELECT body FROM chat_messages').fetchone()[0],'Keep')
        self.assertEqual(list(self.c.execute('PRAGMA foreign_key_check')),[])
    def test_legacy_no_assignment(self):
        self.assertTrue(a.effective(self.c,'legacy','officer')['permissions']['applications.edit'])
    def test_existing_account_preserved(self):
        self.c.execute("INSERT INTO auth_users VALUES('legacy','unchanged','viewer',NULL,1,'c','u','creator','seen')")
        original=tuple(self.c.execute('SELECT * FROM auth_users').fetchone())
        a.migrate(self.c)
        self.assertEqual(tuple(self.c.execute('SELECT * FROM auth_users').fetchone()),original)
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_user_roles').fetchone()[0],0)
    def test_viewer_boundary(self):
        self.c.execute("INSERT INTO auth_role_permissions VALUES('viewer','applications.edit',1,'now','test')")
        self.assertFalse(a.effective(self.c,'legacy','viewer')['permissions']['applications.edit'])
    def test_custom_assignment(self):
        a.save_role(self.c,dict(code='limited',label='Обмежена',base_role='officer',permissions={'applications.edit':False}),'test')
        a.save_user(self.c,dict(username='fixture',password='fixture-only-password',role_code='limited',officer_id=1),'bootstrap',{})
        self.assertFalse(a.effective(self.c,'fixture','officer')['permissions']['applications.edit'])
        self.assertEqual(self.c.execute('SELECT role FROM auth_users').fetchone()[0],'officer')
    def test_last_admin(self):
        a.save_user(self.c,dict(username='admin1',password='fixture-only-password',role_code='admin'),'bootstrap',{})
        with self.assertRaises(ValueError):a.save_user(self.c,dict(username='admin1',role_code='viewer'),'other',{})
    def test_self_lock(self):
        with self.assertRaises(ValueError):a.save_user(self.c,dict(username='admin1',role_code='viewer'),'admin1',{})
    def test_no_environment_copy(self):
        with self.assertRaises(ValueError):a.save_user(self.c,dict(username='existing',role_code='admin'),'bootstrap',{'existing':{}})
    def test_hash(self):
        h=a.hash_password('fixture-only-password')
        self.assertTrue(a.verify_password('fixture-only-password',h));self.assertFalse(a.verify_password('wrong',h))
    def test_get_start_is_mutation(self):
        self.assertEqual(a.permission_key('GET','/api/applications/123/verify-documents/start'),'applications.check')
    def test_application_assignment_is_not_an_officer_access_boundary(self):
        import server
        with patch.object(server,'db',return_value=self.c):
            self.assertTrue(server.officer_mutation_scope_allowed('/api/applications/assigned-to-someone-else',1))
            self.assertTrue(server.officer_mutation_scope_allowed('/api/applications/assigned-to-someone-else/verify-documents',1))
        self.c.execute('UPDATE authorized_officers SET active=0 WHERE id=1')
        with patch.object(server,'db',return_value=self.c):
            self.assertFalse(server.officer_mutation_scope_allowed('/api/applications/any/verify-documents',1))
    def test_managed_server_grant_and_deny(self):
        import server
        a.save_role(self.c,dict(code='limited',label='Контроль',base_role='officer',permissions={'references.update':True}),'test')
        a.save_user(self.c,dict(username='fixture',password='fixture-only-password',role_code='limited',officer_id=1),'bootstrap',{})
        handler=object.__new__(server.Handler)
        handler.auth_user='fixture';handler.auth_role='officer';handler.auth_officer_id=1
        handler.path='/api/nazk-registry/refresh';handler.command='POST';handler.headers={}
        handler._authorize=lambda:True;handler.send_json=Mock()
        action=Mock()
        with patch.object(server,'db',return_value=self.c):handler._dispatch(action)
        action.assert_called_once()
        a.save_role(self.c,dict(code='limited',label='Контроль',base_role='officer',permissions={'references.update':False}),'test')
        action.reset_mock()
        with patch.object(server,'db',return_value=self.c):handler._dispatch(action)
        action.assert_not_called();self.assertEqual(handler.send_json.call_args.args[1],403)

    def test_non_admin_cannot_replace_templates_or_save_document_metadata(self):
        import server
        for role in ('viewer','officer'):
            for path in (
                '/api/admin/templates/decline_p49_3/replace',
                '/api/admin/document-metadata/nazk_supplier_request/askod_short_summary',
            ):
                with self.subTest(role=role,path=path):
                    handler=object.__new__(server.Handler)
                    handler.auth_user='fixture';handler.auth_role=role;handler.auth_officer_id=1
                    handler.path=path;handler.command='POST';handler.headers={'Content-Length':'2'}
                    handler.rfile=io.BytesIO(b'{}');handler.send_json=Mock();handler._authorize=Mock(return_value=True)
                    action=Mock()
                    with patch.object(server,'db',return_value=self.c):handler._dispatch(action)
                    action.assert_not_called()
                    self.assertEqual(handler.send_json.call_args.args[1],403)

if __name__=='__main__':unittest.main()
