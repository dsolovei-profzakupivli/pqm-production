"""Cross-filtered appeal KPI facets on the disposable fixture database."""
from contextlib import closing
import json
from pathlib import Path
import gc
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server
import validation.local_release_20260911.test_formed_protocols as fixture_module


class ViolationReportKpiFacetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,
                                                ignore_cleanup_errors=True)
        self.fixture = fixture_module.FormedProtocolTests()
        with patch('tempfile.tempdir', self.temp.name):
            self.fixture.setUp()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(gc.collect)
        rows = [
            ('A','pending','r1','2026-10-01','needle','111'),
            ('A','pending','r1','2026-10-02','needle','111'),
            ('A','satisfied','r1','2026-10-03','needle','111'),
            ('A','declined','r2','2026-10-04','other','222'),
            ('A','answered','r2','2026-10-05','needle','111'),
            ('A','draft','r2','2026-10-06','other','222'),
            ('A','cancelled','r2','2026-10-07','other','222'),
            ('B','pending','r1','2026-10-01','needle','111'),
            ('B','satisfied','r1','2026-10-03','needle','111'),
            ('B','declined','r2','2026-10-04','other','222'),
            ('B','answered','r2','2026-10-05','needle','111'),
            ('B','draft','r2','2026-10-06','other','222'),
            ('B','cancelled','r2','2026-10-07','other','222'),
            ('B','future_status','r2','2026-10-08','other','222'),
        ]
        with closing(server.db()) as con:
            with con:
                for i,(authority,status,reason,day,description,supplier) in enumerate(rows):
                    con.execute('''INSERT INTO violation_reports
                      (id,report_id,status,date_published,authority_name,authority_code,reason,
                       description,defendant_code,raw_json,synced_at)
                      VALUES(?,?,?,?,?,?,?,?,?,'{}','fixture')''',
                      (f'r{i}',f'R-{i}-{description}',status,day,f'Authority {authority}',
                       authority,reason,description,supplier))

    @staticmethod
    def query(**filters):
        return server.list_violation_reports({key:[str(value)] for key,value in filters.items()})

    def test_facets_cross_filter_and_keep_non_kpi_statuses_in_totals(self):
        all_rows=self.query()
        self.assertEqual(14,all_rows['total'])
        self.assertEqual((3,2,2),(all_rows['pending'],all_rows['satisfied'],all_rows['declined']))
        self.assertEqual({'A':7,'B':7},{x['authority_code']:x['count'] for x in all_rows['authorities']})
        admin=self.query(authority_code='A')
        self.assertEqual((2,1,1),(admin['pending'],admin['satisfied'],admin['declined']))
        self.assertEqual({'A':7,'B':7},{x['authority_code']:x['count'] for x in admin['authorities']})
        self.assertEqual(3,admin['total']-admin['pending']-admin['satisfied']-admin['declined'])
        decision=self.query(status='pending')
        self.assertEqual((3,2,2),(decision['pending'],decision['satisfied'],decision['declined']))
        self.assertEqual({'A':2,'B':1},{x['authority_code']:x['count'] for x in decision['authorities']})
        both=self.query(authority_code='A',status='pending')
        self.assertEqual(2,both['total'])
        self.assertEqual((2,1,1),(both['pending'],both['satisfied'],both['declined']))

    def test_shared_search_reason_date_supplier_and_pagination(self):
        filtered=self.query(search='needle',reason='r1',date_from='2026-10-02',
                            date_to='2026-10-03',supplier_code='111',
                            authority_code='A',status='satisfied')
        self.assertEqual(1,filtered['total'])
        self.assertEqual(['R-2-needle'],[item['report_id'] for item in filtered['items']])
        first=self.query(page=1,size=10);second=self.query(page=2,size=10)
        self.assertEqual(14,first['total']);self.assertEqual(14,second['total'])
        self.assertEqual((first['pending'],first['satisfied'],first['declined']),
                         (second['pending'],second['satisfied'],second['declined']))
        self.assertEqual(first['authorities'],second['authorities'])
        self.assertNotEqual([x['id'] for x in first['items']],[x['id'] for x in second['items']])

    def test_read_only_http_api_keeps_contract_and_combines_all_query_facets(self):
        query=('search=needle&reason=r1&date_from=2026-10-02&date_to=2026-10-03'
               '&supplier_code=111&authority_code=A&status=satisfied&page=1&size=10')
        request=SimpleNamespace(path='/api/violation-reports?'+query,
                                send_json=lambda body,status=200:(body,status))
        payload,status=server.Handler._do_GET(request)
        self.assertEqual(200,status)
        self.assertEqual({'items','total','pending','satisfied','declined','page','size','pages',
                          'statuses','reasons','authorities','sync'},set(payload))
        self.assertEqual(1,payload['total']);self.assertEqual(1,len(payload['items']))
        self.assertEqual('R-2-needle',payload['items'][0]['report_id'])
        self.assertEqual((1,1,0),(payload['pending'],payload['satisfied'],payload['declined']))
        self.assertEqual({'A':1,'B':1},{x['authority_code']:x['count'] for x in payload['authorities']})

    def test_additional_statuses_are_not_lost_from_filtered_counts(self):
        data=self.query(authority_code='A')
        self.assertEqual({'pending':2,'satisfied':1,'declined':1},
                         {key:data[key] for key in ('pending','satisfied','declined')})
        self.assertEqual(7,data['total'])


if __name__=='__main__':
    unittest.main()
