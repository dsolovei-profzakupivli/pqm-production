"""Actual Handler on loopback; isolated DB and ordinary authorization gates."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import os
import sandbox_runtime
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
import auth_access
import chat_annotations
import server


class ChatAnnotationsHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'chat.sqlite'
        self.addCleanup(self.tmp.cleanup)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT)')
            auth_access.migrate(con);chat_annotations.migrate(con)
            con.executescript('''
              CREATE TABLE frameworks(id TEXT PRIMARY KEY,pretty_id TEXT,dk_code TEXT);
              CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_name TEXT,supplier_code TEXT,framework_id TEXT);
              INSERT INTO frameworks VALUES ('f','technical framework','03220000-9');
              INSERT INTO submissions VALUES ('target','ФОП СИНТЕТИЧНИЙ','00123456','f');
              INSERT INTO chat_threads VALUES (71,'Довільний',1,'alice','old','old');
              INSERT INTO chat_members VALUES (71,'alice','old',0);
              INSERT INTO chat_members VALUES (71,'bob','old',0);
              INSERT INTO chat_messages VALUES (81,71,'bob','Перевірити','target','old');
              INSERT INTO chat_messages VALUES (82,71,'bob','Історичне','missing','old');
            ''');con.commit()
        for name,value in [('AUTH_ENABLED',False),('LOCAL_ROLE_IMPERSONATION',True),
                           ('IS_WEB_ENV',False),('SANDBOX_MODE',False),('SAFE_MODE',False),
                           ('CURRENT_USER','alice'),('DB_PATH',self.path)]:
            self.enterContext(patch.object(server,name,value))
        original_db=server.db
        @contextmanager
        def closed_db():
            with closing(original_db()) as con:
                with con:yield con
        self.enterContext(patch.object(server,'db',closed_db))
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.stop)

    def stop(self):
        self.http.shutdown();self.thread.join();self.http.server_close()

    def call(self,path,payload=None,role='officer',empty_body=False):
        req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}'+urllib.parse.quote(path,safe='/?=&,'),
            data=b'' if empty_body else None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type':'application/json','Connection':'close','X-PQM-Local-Role':role,**getattr(self,'extra_headers',{})})
        try:response=urllib.request.urlopen(req,timeout=5)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,json.load(response)

    def test_all_three_roles_can_annotate_as_members(self):
        for role in ('admin','officer','viewer'):
            status,data=self.call('/api/chats/71/messages/81/marks',{'kind':'support','active':True},role)
            self.assertEqual(200,status,data)
        self.assertEqual(1,len(data['marks']['reactions']))

    def test_get_lists_compact_link_data_and_safe_historical_fallback(self):
        status,data=self.call('/api/chats/71/messages')
        self.assertEqual(200,status,data)
        self.assertEqual('00123456',data['items'][0]['submission']['supplier_code'])
        self.assertEqual('03220000-9',data['items'][0]['submission']['dk_code'])
        self.assertEqual({'id':'missing'},data['items'][1]['submission'])

    def test_get_never_writes_or_issues_external_queries(self):
        with closing(sqlite3.connect(self.path)) as con:before=con.iterdump();before=list(before)
        with patch.object(server,'api_get',side_effect=AssertionError('External query forbidden')):
            self.assertEqual(200,self.call('/api/chats/71/messages?mark=unmarked&search=ПЕРЕВІРИТИ')[0])
        with closing(sqlite3.connect(self.path)) as con:after=list(con.iterdump())
        self.assertEqual(before,after)

    def test_nonmember_and_cross_chat_message_are_denied(self):
        for path in ['/api/chats/99/messages','/api/chats/99/messages/81/marks','/api/chats/71/messages/999/marks']:
            status,_=self.call(path,{'kind':'seen','active':True} if path.endswith('marks') else None)
            self.assertEqual(404,status)

    def test_safe_mode_remains_blocking(self):
        with patch.object(server,'SAFE_MODE',True):
            self.assertEqual(503,self.call('/api/chats/71/messages/81/marks',{'kind':'support','active':True})[0])

    def test_custom_permission_denial_is_not_bypassed(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO auth_role_permissions VALUES ('officer','messages.write',0,'now','test')");con.commit()
        self.assertEqual(403,self.call('/api/chats/71/messages/81/marks',{'kind':'support','active':True})[0])

    def test_mark_and_filter_are_shared_without_altering_message(self):
        self.call('/api/chats/71/messages/81/marks',{'kind':'work','state':'working','version':0})
        status,data=self.call('/api/chats/71/messages?mark=working')
        self.assertEqual(200,status);self.assertEqual([81],[row['id'] for row in data['items']])
        self.assertEqual('Перевірити',data['items'][0]['body']);self.assertEqual('old',data['items'][0]['created_at'])

    def test_search_uses_linked_application_fields_without_cross_chat_leak(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript('''
              INSERT INTO chat_messages VALUES (83,71,'bob','Історичне без реквізитів','target','old');
              INSERT INTO chat_threads VALUES (72,'Інший чат',1,'alice','old','old');
              INSERT INTO chat_members VALUES (72,'alice','old',0);
              INSERT INTO chat_messages VALUES (84,72,'bob','Інше повідомлення','target','old');
            ''');con.commit()
        for term in ('03220000-9','00123456','СИНТЕТИЧНИЙ','target'):
            status,data=self.call('/api/chats/71/messages?search='+term)
            self.assertEqual(200,status,data)
            self.assertEqual({81,83},{row['id'] for row in data['items']},term)
        status,data=self.call('/api/chats/71/messages?mark=working&search=00123456')
        self.assertEqual(200,status);self.assertEqual([],data['items'])
        status,data=self.call('/api/chats/72/messages?search=00123456')
        self.assertEqual(200,status);self.assertEqual([84],[row['id'] for row in data['items']])


    def test_unauthenticated_cannot_read_or_annotate(self):
        with patch.object(server,'AUTH_ENABLED',True),patch.object(server,'AUTH_SESSIONS',{}),patch.object(server,'auth_accounts',return_value={}):
            self.assertEqual(401,self.call('/api/chats/71/messages')[0])
            self.assertEqual(401,self.call('/api/chats/71/messages/81/marks',{'kind':'seen','active':True},empty_body=True)[0])


    def test_read_receipt_never_marks_later_messages_as_seen(self):
        self.assertEqual(200,self.call('/api/chats/71/read',{'message_id':81})[0])
        self.call('/api/chats/71/read',{'message_id':0})
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(81,con.execute("SELECT last_read_message_id FROM chat_members WHERE username='alice'").fetchone()[0])


if __name__=='__main__':unittest.main()
