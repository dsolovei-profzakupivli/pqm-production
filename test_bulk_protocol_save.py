"""HTTP/CAS regressions on disposable synthetic DB; no runtime access."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import gc
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
import unittest
from unittest.mock import patch
import server
import validation.local_release_20260911.test_formed_protocols as fixtures


class BulkProtocolSaveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FormedProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        for key,value in (('IS_WEB_ENV',False),('SANDBOX_MODE',False),('AUTH_ENABLED',False),
                          ('SAFE_MODE',False),('LOCAL_ROLE_IMPERSONATION',True)):
            context=patch.object(server,key,value);context.start();self.addCleanup(context.stop)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=5);gc.collect()

    def call(self,method='PATCH',payload=None,sid='s0',role='admin',suffix=''):
        with closing(http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)) as client:
            client.request(method,'/api/applications/'+sid+suffix,
                           body=json.dumps(payload) if payload is not None else None,
                           headers={'Content-Type':'application/json','X-PQM-Local-Role':role})
            response=client.getresponse();return response.status,json.loads(response.read())

    def guarded(self,new='200',expected='100',**extra):
        return {'protocol_number':new,'_expected_values':{'protocol_number':expected},**extra}

    def current(self):
        with closing(server.db()) as con:
            return con.execute("SELECT protocol_number FROM application_fields WHERE submission_id='s0'").fetchone()[0]

    def test_save_and_idempotent_confirmation_do_not_duplicate_audit(self):
        self.assertEqual(self.call(payload=self.guarded())[0],200)
        with closing(server.db()) as con:before=con.execute('SELECT count(*) FROM audit_log').fetchone()[0]
        status,data=self.call(payload=self.guarded())
        self.assertEqual(status,200);self.assertTrue(data['unchanged']);self.assertEqual(self.current(),'200')
        with closing(server.db()) as con:self.assertEqual(con.execute('SELECT count(*) FROM audit_log').fetchone()[0],before)

    def test_conflicting_officer_value_is_not_overwritten(self):
        self.assertEqual(self.call(payload=self.guarded('OTHER'))[0],200)
        status,data=self.call(payload=self.guarded())
        self.assertEqual(status,409);self.assertEqual(data['code'],'bulk_value_conflict');self.assertEqual(self.current(),'OTHER')

    def test_two_concurrent_requests_have_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda number:self.call(payload=self.guarded(number)),('A','B')))
        self.assertEqual(sorted(status for status,_ in results),[200,409]);self.assertIn(self.current(),('A','B'))

    def test_authorized_readback_is_business_read_only_and_rejects_invalid_fields(self):
        with closing(server.db()) as con:before=list(con.iterdump())
        status,data=self.call('GET',suffix='/bulk-state?fields=protocol_number,protocol_date')
        self.assertEqual(status,200);self.assertEqual(data['values'],{'protocol_number':'100','protocol_date':'2026-09-05'})
        with closing(server.db()) as con:self.assertEqual(list(con.iterdump()),before)
        self.assertEqual(self.call('GET',suffix='/bulk-state?fields=protocol_number%3BDROP')[0],400)
        self.assertEqual(self.call('GET',sid='missing',suffix='/bulk-state?fields=protocol_number')[0],404)

    def test_readback_requires_authentication(self):
        with patch.object(server,'AUTH_ENABLED',True),patch.object(server,'auth_accounts',return_value={}):
            self.assertEqual(self.call('GET',suffix='/bulk-state?fields=protocol_number')[0],401)

    def test_readback_requires_applications_read_permission(self):
        with patch.object(server.auth_access,'effective',return_value={'active':True,'permissions':{'applications.read':False}}):
            self.assertEqual(self.call('GET',suffix='/bulk-state?fields=protocol_number')[0],403)

    def test_viewer_cannot_write_or_bypass_with_payload_role(self):
        self.assertEqual(self.call(payload=self.guarded(role='admin',user='spoof'),role='viewer')[0],403)
        self.assertEqual(self.current(),'100')

    def test_formed_protocol_guard_remains_effective(self):
        self.fixture.generate()
        self.assertEqual(self.call(payload=self.guarded())[0],409);self.assertEqual(self.current(),'100')

    def test_final_qualification_and_historical_guards_remain_effective(self):
        with closing(server.db()) as con:
            with con:con.execute("UPDATE qualifications SET status='active' WHERE id='qs0'")
        # Final-status rejection occurs before reading a mutation body. Use an
        # empty request here to avoid the pre-existing Windows unread-body RST.
        self.assertEqual(self.call()[0],409);self.assertEqual(self.current(),'100')
        with patch.object(server.historical_applications,'assert_editable',side_effect=server.historical_applications.HistoricalApplicationReadOnlyError('historical')):
            # Test guard directly; final status check would otherwise reject first.
            with closing(server.db()) as con:
                with con:con.execute("UPDATE qualifications SET status='pending' WHERE id='qs0'")
            self.assertEqual(self.call(payload=self.guarded())[0],409)

    def test_database_locked_is_explicitly_unconfirmed_and_readback_then_retry_works(self):
        original=server.db
        def short_wait():
            con=original();con.execute('PRAGMA busy_timeout=30');return con
        with closing(sqlite3.connect(server.DB_PATH)) as holder:
            holder.execute('BEGIN IMMEDIATE')
            with patch.object(server,'db',side_effect=short_wait):
                status,data=self.call(payload=self.guarded())
            self.assertEqual(status,503);self.assertEqual(data['code'],'bulk_database_busy');holder.rollback()
        self.assertEqual(self.call('GET',suffix='/bulk-state?fields=protocol_number')[1]['values']['protocol_number'],'100')
        self.assertEqual(self.call(payload=self.guarded())[0],200)

    def test_invalid_expected_payload_never_writes(self):
        for expected in (None,{},[],{'protocol_date':'100'},{'protocol_number':1}):
            with self.subTest(expected=expected):
                self.assertEqual(self.call(payload={'protocol_number':'200','_expected_values':expected})[0],400)
                self.assertEqual(self.current(),'100')

    def test_commit_can_succeed_even_when_response_is_lost(self):
        original=server.Handler.send_json
        def lose_response(handler,data,status=200):
            if data.get('saved'):raise BrokenPipeError('synthetic lost response')
            return original(handler,data,status)
        with patch.object(server.Handler,'send_json',lose_response):
            with self.assertRaises((http.client.RemoteDisconnected,ConnectionResetError)):
                self.call(payload=self.guarded())
        status,data=self.call('GET',suffix='/bulk-state?fields=protocol_number')
        self.assertEqual(status,200);self.assertEqual(data['values']['protocol_number'],'200')
        with closing(server.db()) as con:before=con.execute('SELECT count(*) FROM audit_log').fetchone()[0]
        self.assertTrue(self.call(payload=self.guarded())[1]['unchanged'])
        with closing(server.db()) as con:self.assertEqual(con.execute('SELECT count(*) FROM audit_log').fetchone()[0],before)

    def test_legacy_single_edit_still_uses_existing_business_checks(self):
        self.assertEqual(self.call(payload={'protocol_number':'201'})[0],200)
        self.assertEqual(self.current(),'201')

    def test_ui_regressions(self):
        root=Path(__file__).resolve().parent
        result=subprocess.run(['node','--test','validation/bulk_application_save_ui.cjs'],cwd=root,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
