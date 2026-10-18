"""Real account endpoint/authorization against disposable synthetic SQLite only."""
from contextlib import closing
import base64
import gc
import http.client
from http.server import HTTPServer
import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import auth_access
import server


class PersonalThemeAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret=server.hash_password('theme-fixture-only-password')

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='pqm-theme-http-')
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'isolated.sqlite3'
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER,full_name TEXT)')
            auth_access.migrate(con)
            for user,role in [('alice','officer'),('bob','viewer')]:
                con.execute('INSERT INTO auth_users(username,password_hash,role,active,created_at,updated_at,created_by) VALUES(?,?,?,1,?,?,?)',(user,self.secret,role,'before','before','fixture'))
                con.execute('INSERT INTO user_preferences(username,display_name,start_view,color_scheme,density,presence_status,updated_at) VALUES(?,?,?,?,?,?,?)',(user,user.title(),'workQueue','system','compact','away','before'))
            con.commit()
        for key,value in [('DB_PATH',self.path),('AUTH_ENABLED',True),('IS_WEB_ENV',False),('SANDBOX_MODE',False),('SAFE_MODE',False)]:
            p=patch.object(server,key,value);p.start();self.addCleanup(p.stop)
        p=patch.object(server,'configured_auth_accounts',return_value={});p.start();self.addCleanup(p.stop)
        p=patch.object(server,'AUTH_SESSIONS',{});p.start();self.addCleanup(p.stop)
        self.http=HTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop_http)

    def stop_http(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=5);gc.collect()

    def call(self,method='GET',payload=None,user='alice',cookie=None,path='/api/account'):
        headers={}
        if cookie:headers['Cookie']=cookie
        elif user:headers['Authorization']='Basic '+base64.b64encode((user+':theme-fixture-only-password').encode()).decode()
        body=None if payload is None else json.dumps(payload)
        if body is not None:headers['Content-Type']='application/json'
        encoded=(body or '').encode()
        headers.update({'Host':'127.0.0.1','Content-Length':str(len(encoded)),'Connection':'close'})
        wire=(f'{method} {path} HTTP/1.0\r\n'+''.join(f'{key}: {value}\r\n' for key,value in headers.items())+'\r\n').encode()+encoded
        with closing(socket.create_connection(('127.0.0.1',self.http.server_port),timeout=10)) as client:
            client.sendall(wire)
            r=http.client.HTTPResponse(client);r.begin();raw=r.read()
            return r.status,json.loads(raw) if raw else None,dict(r.getheaders())

    def row(self,user):
        with closing(sqlite3.connect(self.path)) as con:
            con.row_factory=sqlite3.Row;return dict(con.execute('SELECT * FROM user_preferences WHERE username=?',(user,)).fetchone())

    def test_default_and_legacy_system_are_light(self):
        self.assertEqual(self.call()[1]['color_scheme'],'light')
        with closing(sqlite3.connect(self.path)) as con:con.execute("DELETE FROM user_preferences WHERE username='alice'");con.commit()
        self.assertEqual(self.call()[1]['color_scheme'],'light')

    def test_theme_only_preserves_every_other_preference(self):
        before=self.row('alice');bob=self.row('bob')
        self.assertEqual(self.call('PATCH',{'color_scheme':'dark'})[0],200)
        after=self.row('alice')
        for key in ['username','display_name','start_view','density','presence_status']:self.assertEqual(after[key],before[key])
        self.assertEqual(self.row('bob'),bob)
        self.assertEqual(self.call()[1]['color_scheme'],'dark')
        self.assertEqual(self.call(user='bob')[1]['color_scheme'],'light')

    def test_payload_username_cannot_target_another_account(self):
        before=self.row('bob')
        self.assertEqual(self.call('PATCH',{'username':'bob','color_scheme':'dark'})[0],200)
        self.assertEqual(self.row('bob'),before)
        self.assertEqual(self.row('alice')['color_scheme'],'dark')

    def test_viewer_can_only_save_own_appearance(self):
        self.assertEqual(self.call('PATCH',{'color_scheme':'dark'},user='bob')[0],200)
        self.assertEqual(self.row('alice')['color_scheme'],'system')
        self.assertEqual(self.call(user='bob')[1]['color_scheme'],'dark')

    def test_invalid_values_are_controlled_and_do_not_write(self):
        before=self.row('alice')
        for value in [None,'system','DARK','',0,[],{}]:
            with self.subTest(value=value):self.assertEqual(self.call('PATCH',{'color_scheme':value})[0],400)
        self.assertEqual(self.row('alice'),before)

    def test_unauthenticated_request_cannot_read_or_write_theme(self):
        before=self.row('alice')
        self.assertEqual(self.call(user=None)[0],401)
        self.assertEqual(self.call('PATCH',{'color_scheme':'dark'},user=None)[0],401)
        self.assertEqual(self.row('alice'),before)

    def test_legacy_full_profile_save_preserves_existing_dark(self):
        self.call('PATCH',{'color_scheme':'dark'})
        payload={'display_name':'Alice Updated','start_view':'applications','density':'comfortable','presence_status':'working'}
        self.assertEqual(self.call('PATCH',payload)[0],200)
        self.assertEqual(self.call()[1]['color_scheme'],'dark')
        self.assertEqual(self.row('alice')['display_name'],'Alice Updated')

    def test_full_save_accepts_theme_and_keeps_password_guard(self):
        payload={'display_name':'Alice','start_view':'workQueue','density':'compact','presence_status':'away','color_scheme':'dark','new_password':'replacement-fixture-password','current_password':'incorrect'}
        before=self.row('alice')
        self.assertEqual(self.call('PATCH',payload)[0],403)
        self.assertEqual(self.row('alice'),before)
        payload.update(new_password='',current_password='')
        self.assertEqual(self.call('PATCH',payload)[0],200)
        self.assertEqual(self.call()[1]['color_scheme'],'dark')

    def test_choice_survives_logout_and_new_login(self):
        self.call('PATCH',{'color_scheme':'dark'})
        for _ in range(2):
            status,_,headers=self.call('POST',{'username':'alice','password':'theme-fixture-only-password'},user=None,path='/api/login')
            self.assertEqual(status,200)
            cookie=headers['Set-Cookie'].split(';')[0]
            self.assertEqual(self.call(user=None,cookie=cookie)[1]['color_scheme'],'dark')
            self.assertEqual(self.call('POST',{},user=None,cookie=cookie,path='/api/logout')[0],204)

    def test_get_is_read_only(self):
        before=self.row('alice')
        self.assertEqual(self.call()[0],200)
        self.assertEqual(self.row('alice'),before)


class PersonalThemeSourceTests(unittest.TestCase):
    def test_dark_css_has_no_geometry_or_icon_overrides(self):
        css=Path('theme.css').read_text(encoding='utf-8')
        for forbidden in ['width:', 'height:', 'padding:', 'margin:', 'display:', 'position:', 'opacity:', 'font-size:', 'fill:', 'stroke:', 'filter:', 'url(', 'data-pqm-environment', 'halloween']:
            self.assertNotIn(forbidden,css)
        self.assertIn('@media screen',css)
        self.assertIn('html[data-theme="dark"]',css)

    def test_ui_uses_no_shared_storage_or_new_api(self):
        source=Path('theme_ui.js').read_text(encoding='utf-8')
        for forbidden in ['localStorage','sessionStorage','fetch(','XMLHttpRequest','/api/','setInterval(']:self.assertNotIn(forbidden,source)
        self.assertIn('value="light">Світла',source)
        self.assertIn('value="dark">Темна',source)

    def test_html_has_no_seasonal_dependencies(self):
        html=Path('index.html').read_text(encoding='utf-8').lower()
        for forbidden in ['halloween','sandbox_runtime','sandbox_theme','sandbox_contrast']:self.assertNotIn(forbidden,html)
        self.assertIn('theme.css',html)
        self.assertIn('theme_ui.js',html)
