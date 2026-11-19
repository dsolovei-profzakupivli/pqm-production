"""UI summary regressions: synthetic DB only, no external integrations."""
from contextlib import closing
from datetime import datetime
import http.client
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import server
import ui_action_summary as summary
import test_bulk_protocol_save as fixtures


class UiImprovementsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BulkProtocolSaveTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.moment=datetime(2026,10,16,12,tzinfo=ZoneInfo('Europe/Kyiv'))
        with closing(server.db()) as con:
            with con:
                for i,(status,end,closed) in enumerate([
                    ('pending','2026-10-16T11:00:00+03:00',False),
                    ('pending','2026-10-16T13:00:00+03:00',False),
                    ('pending','2026-10-15T11:00:00+03:00',True),
                    ('satisfied','2026-10-15',False),('pending','',False),
                    ('pending','2026-10-16',False)]):
                    con.execute("INSERT INTO violation_reports(id,report_id,status,defendant_period_end,authority_code,raw_json,synced_at) VALUES(?,?,?,?,'40996564','{}','fixture')",(str(i),str(i),status,end))
                    if closed:con.execute("INSERT INTO violation_report_reviews(report_id,review_status,completed_at,updated_at) VALUES(?,'reviewed','2026-10-15','fixture')",(str(i),))
                for i,status in enumerate(['new','in_progress','ready_for_document','awaiting_response','completed','cancelled']):
                    con.execute("INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,status,created_at,updated_at) VALUES(?,?,'manual','1',?,'fixture','fixture')",('t'+str(i),'k'+str(i),status))

    def count(self,kind='appeals',moment=None):
        return summary.summary(server.DB_PATH,kind,server.operational_tasks.STATUS_GROUPS['needs_action'],server.violation_deadline_control,moment or self.moment)['count']

    def get(self,path):
        with closing(http.client.HTTPConnection('127.0.0.1',self.fixture.http.server_port,timeout=5)) as con:
            con.request('GET',path,headers={'X-PQM-Local-Role':'admin'})
            response=con.getresponse();return response.status,json.loads(response.read())

    def test_summary_uses_task_kpi_statuses_not_unread(self):
        self.assertEqual(3,self.count('tasks'))
        with closing(server.db()) as con:
            with con:con.execute("UPDATE operational_tasks SET status='completed' WHERE id='t0'")
        self.assertEqual(2,self.count('tasks'))

    def test_expired_summary_matches_all_filtered_ids_and_completion(self):
        self.assertEqual(1,self.count())
        with patch.object(server,'datetime',wraps=datetime) as clock:
            clock.now.return_value=self.moment
            data=server.list_violation_reports({'response_expired':['1']})
        self.assertEqual(['0'],[item['id'] for item in data['items']]);self.assertEqual(1,data['total'])
        with closing(server.db()) as con:
            with con:con.execute("INSERT INTO violation_report_reviews(report_id,review_status,completed_at,updated_at) VALUES('0','reviewed','done','fixture')")
        self.assertEqual(0,self.count())

    def test_time_passage_offsets_date_only_missing_and_dst(self):
        later=self.moment.replace(hour=14)
        self.assertEqual(2,self.count(moment=later))
        self.assertEqual(3,self.count(moment=later.replace(day=17)))
        for end,now,expected in [
            ('2026-10-25T03:30:00+03:00','2026-10-25T03:15:00+02:00',True),
            ('2026-03-29T04:30:00+03:00','2026-03-29T02:30:00+02:00',False),
            ('2026-10-16','2026-10-16T23:59:59+03:00',False),
            ('2026-10-16T09:00:00Z','2026-10-16T12:00:00+03:00',True),
            ('bad','2026-10-16T12:00:00+03:00',False)]:
            self.assertEqual(expected,server.violation_deadline_control({'defendant_period_end':end},datetime.fromisoformat(now))['supplier_ready'])

    def test_summary_and_repeat_views_do_not_write_or_reduce_count(self):
        with closing(server.db()) as con:before=list(con.iterdump())
        for _ in range(3):self.assertEqual(1,self.count());self.assertEqual(3,self.count('tasks'))
        for path in ['/api/operational-tasks/summary','/api/violation-reports/summary']:
            self.assertEqual(200,self.get(path)[0])
        with closing(server.db()) as con:self.assertEqual(before,list(con.iterdump()))

    def test_summary_rbac_and_authentication(self):
        for permission,path in [('tasks.read','/api/operational-tasks/summary'),('appeals.read','/api/violation-reports/summary')]:
            with patch.object(server.auth_access,'effective',return_value={'active':True,'permissions':{permission:False}}):
                self.assertEqual(403,self.get(path)[0])
            with patch.object(server,'AUTH_ENABLED',True),patch.object(server,'auth_accounts',return_value={}):
                self.assertEqual(401,self.get(path)[0])

    def test_bids_presentation_requires_explicit_ready_flag(self):
        with patch.dict(server.os.environ,{'PQM_SUPPLIER_BIDS_READY':'0'}):
            self.assertFalse(self.get('/api/auth/me')[1]['ui_features']['supplier_bids_ready'])
        with patch.dict(server.os.environ,{'PQM_SUPPLIER_BIDS_READY':'1'}),patch.object(server,'BIDS_MODE','read_only'):
            self.assertTrue(self.get('/api/auth/me')[1]['ui_features']['supplier_bids_ready'])

    def test_ui_contract_and_helper(self):
        root=Path(__file__).resolve().parent
        result=subprocess.run(['node','validation/ui_improvements_unit.cjs'],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
