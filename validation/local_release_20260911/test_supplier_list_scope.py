"""Production list scope: synthetic schema, query-only reads, no live data."""
import json
import re
import sqlite3
import unittest
from unittest.mock import patch

import server
import supplier_list_scope


class SupplierListScopeTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.con.create_function('DIGITS',1,lambda v:re.sub(r'\D','',str(v or '')))
        self.con.create_function('CASEFOLD',1,lambda v:str(v or '').casefold())
        self.con.create_function('NORMALIZE_NAME',1,lambda v:str(v or '').casefold())
        with sqlite3.connect('file:data/pqm.sqlite3?mode=ro',uri=True) as source:
            for sql, in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"):
                self.con.execute(sql)
        for fid,dk in [('a','00111111-1'),('b','22222222-2'),('c','00111111-1')]:
            self.con.execute('''INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at)
              VALUES(?,?,?,?,?,'{}','fixture')''',(fid,'UA-'+fid,'Scope '+fid,dk,'active'))
        self.add('00000001','a','terminated')
        self.add('00000001','b','active')
        self.add('00000002','c','active')
        self.add('00000003','a',None)
        for i in range(10,35):self.add(f'{i:08d}','b','active')
        self.con.commit()
        self.mock=patch.object(server,'db',return_value=self.con)
        self.mock.start();self.addCleanup(self.mock.stop)

    def add(self,code,fid,status):
        sid=code+'-'+fid;qid='q-'+sid
        self.con.execute('''INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,
          date_published,qualification_id,raw_json,documents_json,synced_at)
          VALUES(?,?,?,?,?,?,?,'[]','fixture')''',
          (sid,fid,code,'Supplier '+code,'2026-01-01',qid,'{}'))
        self.con.execute('''INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at)
          VALUES(?,?,?,?,?,'fixture')''',(qid,fid,sid,'active' if status else 'pending','{}'))
        if status:
            self.con.execute('''INSERT INTO registry_contracts(id,framework_id,qualification_id,
              supplier_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,'{}','fixture')''',
              ('rc-'+sid,fid,qid,code,status))
        self.con.execute('''INSERT OR IGNORE INTO supplier_registry_summary
          (supplier_code,supplier_name,qualifications_count,active_count,refreshed_at)
          VALUES(?,?,1,1,'fixture')''',(code,'Supplier '+code))

    def listing(self,**params):
        return server.list_qualified_suppliers({key:value if isinstance(value,list) else [str(value)]
                                               for key,value in params.items()})

    def codes(self,**params):return {row['code'] for row in self.listing(**params)['items']}

    def test_single_dk_retains_leading_zeroes(self):
        self.assertEqual(self.codes(dk_code='00111111-1'),{'00000001','00000002','00000003'})

    def test_multiple_dk_or_and_comma_repeated_equivalence(self):
        params=['00111111-1','22222222-2']
        self.assertEqual(self.listing(dk_code=params)['total'],28)
        self.assertEqual(self.listing(dk_code=','.join(params)),self.listing(dk_code=params))

    def test_single_framework(self):
        self.assertEqual(self.codes(framework_id='a'),{'00000001','00000003'})

    def test_multiple_frameworks_or(self):
        self.assertEqual(self.codes(framework_id=['a','c']),{'00000001','00000002','00000003'})

    def test_scope_groups_and_on_same_framework(self):
        self.assertEqual(self.codes(dk_code=['00111111-1','22222222-2'],framework_id='c'),{'00000002'})
        self.assertEqual(self.codes(dk_code='00111111-1',framework_id=['a','c']),
                         {'00000001','00000002','00000003'})

    def test_no_cross_qualification_false_match(self):
        # Supplier 1 has DK-A in a and membership b in DK-B; no single row meets both.
        self.assertEqual(self.listing(dk_code='00111111-1',framework_id='b')['total'],0)
        self.assertEqual(self.listing(dk_code='00111111-1',framework_id='a',status='active')['total'],0)

    def test_empty_and_clear_filters(self):
        self.assertEqual(self.listing(framework_id='absent')['total'],0)
        self.assertEqual(self.listing(dk_code='absent')['total'],0)
        self.assertEqual(self.listing(dk_code=['',' '],framework_id=['']),self.listing())

    def test_pagination_unique_totals_and_out_of_range(self):
        seen=[]
        for page,expected_size in [(1,10),(2,10),(3,6),(4,0)]:
            value=self.listing(framework_id='b',size=10,page=page)
            self.assertEqual((value['total'],value['pages'],value['active']),(26,3,26))
            self.assertEqual(len(value['items']),expected_size)
            seen.extend(row['code'] for row in value['items'])
        self.assertEqual(len(seen),len(set(seen)))
        self.assertEqual(len(seen),26)

    def test_kpis_and_page_application_counts_stay_in_scope(self):
        value=self.listing(framework_id='a')
        self.assertEqual((value['total'],value['registered_total'],value['not_registered'],value['active']),
                         (2,1,1,0))
        self.assertTrue(all(row['applications_count']==1 for row in value['items']))
        self.assertEqual(self.listing(framework_id='a',status='terminated')['total'],1)
        self.assertEqual(self.listing(framework_id='a',status='not_registered')['total'],1)

    def test_existing_search_and_edr_filters_intersect_scope(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_status,synced_at) VALUES('00000001','Зареєстровано','fixture')")
        self.assertEqual(self.listing(framework_id='a',search='00000001',edr_status='Зареєстровано')['total'],1)
        self.assertEqual(self.listing(framework_id='c',search='00000001')['total'],0)

    def test_parameterized_sql_and_duplicate_values(self):
        sql,args=supplier_list_scope.predicate({'framework_id':["a') OR 1=1 --"],
                                               'dk_code':['00111111-1','00111111-1']})
        self.assertNotIn('OR 1=1',sql)
        self.assertEqual(len(args),2)
        self.assertEqual(self.listing(framework_id="a') OR 1=1 --")['total'],0)

    def test_reading_does_not_change_data(self):
        before='\n'.join(self.con.iterdump());changes=self.con.total_changes
        self.con.execute('PRAGMA query_only=ON')
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION}
        def authorize(action,a,b,db,trigger):
            read_pragma=action==sqlite3.SQLITE_PRAGMA and a in {'table_info','table_xinfo','foreign_key_list'}
            return sqlite3.SQLITE_OK if action in allowed or read_pragma else sqlite3.SQLITE_DENY
        self.con.set_authorizer(authorize)
        self.listing(dk_code=['00111111-1','22222222-2'],framework_id=['a','b'],_include_codes=1)
        self.con.set_authorizer(None)
        self.assertEqual(self.con.total_changes,changes)
        self.assertEqual('\n'.join(self.con.iterdump()),before)


if __name__=='__main__':unittest.main()
