"""Full filtered-set protocol-officer KPIs, never page or review-officer counts."""
from contextlib import nullcontext
import unittest
from unittest.mock import patch
import sqlite3
from pathlib import Path
import server
import reference_directories


class OfficerScopeTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.con.create_function('DIGITS',1,lambda v:''.join(c for c in str(v or '') if c.isdigit()))
        self.con.create_function('CASEFOLD',1,lambda v:str(v or '').casefold())
        server.edr_sync_v2.register_verification_sql_functions(self.con)
        with patch('reference_directories.sqlite3.connect',return_value=self.con):
            reference_directories.init_reference_tables(':memory:')
        with patch.object(server,'db',return_value=self.con),patch.object(server,'DB_PATH',Path('memory-only-fixture.sqlite3')):
            server.init_db()
        self.con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES('f1','UA-F-f1','Відбір f1','03110000-1','active','{}','fixture')")
        for i in range(83):
            officer='Олена ЄРЬОМІНА' if i<2 else 'Тетяна ФЕДЧЕНКО' if i<28 else 'Дмитро САВВА'
            code='1531000'+str(i) if i<2 else f'{1000+i:010d}'
            sid='k'+str(i)
            self.con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,status,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,'complete',?,'{}','fixture')",
                             (sid,'f1',code,'Постачальник «Тест»','2026-10-01T12:00:00+03:00','q'+sid))
            self.con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,'f1',?,'active','{}','fixture')",('q'+sid,sid))
            self.con.execute('INSERT INTO application_fields(submission_id,protocol_officer,review_officer) VALUES(?,?,?)',('k'+str(i),officer,'Інша УО розгляду'))
    def stats(self,**query):
        with patch.object(server,'db',side_effect=lambda:nullcontext(self.con)):
            return server.application_stats({k:[v] for k,v in query.items()})
    def test_search_1531_only_two_yeriomina(self):
        result=self.stats(search='1531');self.assertEqual(result['applications'],2)
        self.assertEqual(result['officers'],[{'officer':'Олена ЄРЬОМІНА','applications':2}])
    def test_active_officer_filter_has_only_its_26_rows(self):
        result=self.stats(officer='Тетяна ФЕДЧЕНКО',page='2',size='10')
        self.assertEqual(result['applications'],26)
        self.assertEqual(result['officers'],[{'officer':'Тетяна ФЕДЧЕНКО','applications':26}])
    def test_empty_and_other_filters_combine(self):
        self.assertEqual(self.stats(search='1531',officer='Дмитро САВВА')['officers'],[])
        self.assertEqual(self.stats(search='never-exists')['applications'],0)
        self.assertEqual(self.stats(status='Очікує рішення')['officers'],[])
        self.assertEqual(sum(item['applications'] for item in self.stats()['officers']),83)
