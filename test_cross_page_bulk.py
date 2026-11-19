"""All-results snapshot and sequential HTTP writes on isolated synthetic records."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import server
import test_bulk_protocol_save as fixtures


class CrossPageBulkTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BulkProtocolSaveTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        server.init_reference_tables(server.DB_PATH)

    def seed(self,n):
        with closing(server.db()) as con:
            with con:
                for i in range(8,n):
                    sid='s'+str(i)
                    con.execute("INSERT OR IGNORE INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,'f',?,'pending','{}','fixture')",('q'+sid,sid))
                    con.execute("INSERT OR IGNORE INTO submissions(id,framework_id,supplier_code,supplier_name,qualification_id,date_published,raw_json,synced_at) VALUES (?,'f',?,'Тест',?,'2026-09-05','{}','fixture')",(sid,str(i),'q'+sid))
                    con.execute("INSERT OR IGNORE INTO application_fields(submission_id) VALUES (?)",(sid,))

    def get(self,**filters):
        return self.fixture.call('GET',sid='selection',suffix='?'+urlencode(filters,doseq=True))

    def test_20_72_205_ids_ignore_pagination_and_all_sequential_writes_confirm(self):
        for n in (20,72,205):
            with self.subTest(n=n):
                self.seed(n);status,data=self.get(framework_id='f',page=1,size=50)
                self.assertEqual(status,200);self.assertEqual(data['total'],n)
                self.assertEqual(len({item['id'] for item in data['items']}),n)
                for item in data['items']:
                    payload={'protocol_number':'900','_expected_values':{'protocol_number':item['values']['protocol_number']}}
                    self.assertEqual(self.fixture.call(payload=payload,sid=item['id'])[0],200)
                with closing(server.db()) as con:
                    self.assertEqual(con.execute("SELECT count(*) FROM application_fields WHERE protocol_number='900'").fetchone()[0],n)

    def test_filters_match_existing_view_and_do_not_include_hidden_records(self):
        self.seed(72)
        params={'framework_id':['f'],'protocol_number':['100']}
        expected=server.list_applications({**params,'size':['50']})
        status,data=self.get(**params)
        self.assertEqual(status,200);self.assertEqual(data['total'],expected['total'])
        self.assertEqual({x['id'] for x in data['items']},{x['id'] for x in expected['items']})
        self.assertEqual(self.get(framework_id='missing')[1]['total'],0)
        self.assertEqual(self.get(search="' OR 1=1 --")[1]['total'],0)

    def test_snapshot_is_read_only_and_keeps_previous_values_when_other_officer_edits(self):
        self.seed(72)
        with closing(server.db()) as con:before=list(con.iterdump())
        _,data=self.get(framework_id='f')
        with closing(server.db()) as con:self.assertEqual(list(con.iterdump()),before)
        item=next(x for x in data['items'] if x['id']=='s0')
        self.assertEqual(self.fixture.call(payload=self.fixture.guarded('OTHER'))[0],200)
        status,result=self.fixture.call(payload={'protocol_number':'900','_expected_values':{'protocol_number':item['values']['protocol_number']}})
        self.assertEqual(status,409);self.assertEqual(result['code'],'bulk_value_conflict');self.assertEqual(self.fixture.current(),'OTHER')

    def test_selection_requires_auth_and_read_permission(self):
        with patch.object(server,'AUTH_ENABLED',True),patch.object(server,'auth_accounts',return_value={}):
            self.assertEqual(self.get()[0],401)
        with patch.object(server.auth_access,'effective',return_value={'active':True,'permissions':{'applications.read':False}}):
            self.assertEqual(self.get()[0],403)

    def test_historical_rows_are_explicit_and_never_silently_removed(self):
        with patch.object(server.historical_applications,'is_read_only',side_effect=lambda sid:sid=='s0'):
            _,data=self.get()
        self.assertEqual(data['total'],8)
        self.assertTrue(next(item for item in data['items'] if item['id']=='s0')['historical_read_only'])

    def test_ui_scenarios(self):
        result=subprocess.run(['node','--test','validation/cross_page_bulk_ui.cjs'],cwd=Path(__file__).resolve().parent,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
