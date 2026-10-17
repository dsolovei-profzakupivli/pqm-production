"""Read-only HTTP contract and representative 450k-row fixture. No runtime DB."""
from contextlib import closing
import http.client
import json
import sqlite3
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import audit_reader
import server
import test_bulk_protocol_save as fixtures


class AuditReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BulkProtocolSaveTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        with closing(server.db()) as con:
            with con:
                con.execute('DELETE FROM audit_log')
                con.executemany('INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES(?,?,?,?,?,?)',[
                    ('old-page','2026-10-15T21:30:00+00:00','УО Єрьоміна','protocol_number','before','1531'),
                    ('new-page','2026-10-16T22:00:00+00:00','УО Федченко','notes','старе','Нове')]+[
                    (str(i),'2026-10-16T12:00:00+00:00','УО Савва','notes','a','b') for i in range(220)])
    def get(self,query='',role='admin'):
        with closing(http.client.HTTPConnection('127.0.0.1',self.fixture.http.server_port,timeout=10)) as client:
            client.request('GET','/api/audit'+query,headers={'X-PQM-Local-Role':role})
            response=client.getresponse();return response.status,json.loads(response.read())
    def test_existing_endpoint_defaults_and_server_filter_before_pagination(self):
        status,data=self.get();self.assertEqual(status,200);self.assertEqual(data['total'],222);self.assertEqual(len(data['items']),100)
        status,data=self.get('?search=1531');self.assertEqual(status,200);self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['submission_id'],'old-page')
        self.assertEqual(self.get('?search=before')[1]['total'],1)
        self.assertEqual(self.get('?search=old-page')[1]['total'],1)
    def test_combination_unicode_and_literal_injection(self):
        from urllib.parse import urlencode
        for query in [dict(search='єРЬОМІНА'),dict(user='УО Єрьоміна',field='protocol_number',date_from='2026-10-16',date_to='2026-10-16')]:
            status,data=self.get('?'+urlencode(query));self.assertEqual(status,200);self.assertEqual(data['total'],1)
        self.assertEqual(self.get('?'+urlencode(dict(search="' OR 1=1 --")))[1]['total'],0)
        self.assertEqual(self.get('?date_from=2026-10-17&date_to=2026-10-16')[0],400)
    def test_read_only_rights_and_schema(self):
        with closing(server.db()) as con:before=list(con.iterdump())
        self.get('?search=notes')
        with closing(server.db()) as con:self.assertEqual(before,list(con.iterdump()))
        self.assertEqual(self.get(role='viewer')[0],403)
        with patch.object(server,'AUTH_ENABLED',True),patch.object(server,'auth_accounts',return_value={}):self.assertEqual(self.get()[0],401)

    def test_kyiv_dst_day_includes_both_offsets_not_next_day(self):
        with closing(server.db()) as con:
            with con:
                for stamp in ['2026-10-24T21:30:00Z','2026-10-25T21:30:00Z','2026-10-25T22:30:00Z']:
                    con.execute("INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES('dst',?,'fixture','dst','','')",(stamp,))
        status,data=self.get('?field=dst&date_from=2026-10-25&date_to=2026-10-25')
        self.assertEqual(status,200);self.assertEqual(data['total'],2)


class AuditPerformanceTests(unittest.TestCase):
    def test_450000_rows_without_added_indexes(self):
        with tempfile.TemporaryDirectory(prefix='pqm-audit-perf-') as folder:
            path=Path(folder)/'synthetic.sqlite3'
            with closing(sqlite3.connect(path)) as con:
                con.execute('CREATE TABLE audit_log(id INTEGER PRIMARY KEY,submission_id TEXT,changed_at TEXT,changed_by TEXT,field_name TEXT,old_value TEXT,new_value TEXT)')
                con.executemany('INSERT INTO audit_log VALUES(?,?,?,?,?,?,?)',((i,'submission-'+str(i),'2026-10-16T12:00:00+00:00','Officer '+str(i%30),'protocol_number','before '+str(i),'new '+str(i)) for i in range(450001)))
                con.commit()
            timings=[]
            for query in [{},{'search':['submission-12']},{'search':['absent']},{'user':['Officer 2'],'field':['protocol_number'],'date_from':['2026-10-16'],'date_to':['2026-10-16']}]:
                start=time.monotonic();result=audit_reader.read(path,query);elapsed=time.monotonic()-start;timings.append(round(elapsed,3))
                self.assertLess(elapsed,5,'STOP: 450k-row read needs separate performance/index approval')
                self.assertIn('total',result)
            print('AUDIT_450K_QUERY_SECONDS='+json.dumps(timings))
