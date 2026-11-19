"""Actual summary builder and existing AMCU read model on a disposable DB."""
import ast
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest

import reference_directories
import supplier_activity

ROOT = Path(__file__).resolve().parent


class AmcuQualificationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.sqlite3'
        reference_directories.init_reference_tables(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript('''
                CREATE TABLE supplier_registry_summary(supplier_code,supplier_name,qualifications_count,
                  active_count,inactive_count,suspended_count,frameworks_count,dk_codes,last_qualification,refreshed_at);
                CREATE TABLE frameworks(id,status,raw_json,dk_code);
                CREATE TABLE registry_contracts(id,supplier_code,qualification_id,framework_id,status,raw_json,synced_at);
                CREATE TABLE qualifications(id,submission_id,decision_date);
                CREATE TABLE submissions(id,supplier_code,supplier_name,status);
                INSERT INTO frameworks VALUES ('current','active','{}','test');
                INSERT INTO frameworks VALUES ('ended','terminated','{}','test');
                INSERT INTO frameworks VALUES ('expired','active','{"qualificationPeriod":{"endDate":"2000-01-01"}}','test');
            ''')
            for code in range(5):
                con.execute('INSERT INTO amcu_registry(row_key,offender_code,offender_name) VALUES (?,?,?)',
                            (str(code),str(code),'Synthetic '+str(code)))
            for code, statuses in [(0,['active']),(1,['terminated','active']),(2,['terminated','suspended'])]:
                for i,status in enumerate(statuses):
                    con.execute('INSERT INTO registry_contracts VALUES (?,?,?,?,?,?,?)',
                                (str(code)+str(i),str(code),None,'current',status,'{}','2026-01-01'))
            con.execute("INSERT INTO submissions VALUES ('rejected','3','Synthetic rejected','rejected')")
        # Compile the actual pure DB summary function, without importing/starting
        # the server or reading its configured DB. Its SQL is not duplicated here.
        tree=ast.parse((ROOT/'server.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='refresh_supplier_registry_summary')
        @contextmanager
        def db():
            con=sqlite3.connect(self.path)
            try:
                with con:
                    yield con
            finally:
                con.close()
        namespace={'db':db,'now_iso':lambda:'2026-10-22','supplier_activity':supplier_activity}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'server.py','exec'),namespace)
        self.refresh=namespace['refresh_supplier_registry_summary']

    def rows(self):
        return {r['offender_code']:r for r in reference_directories.list_registry(self.path,'amcu',{})['items']}

    def test_five_cases_from_actual_summary_and_read_model(self):
        self.assertEqual(self.refresh(),3)
        rows=self.rows()
        self.assertEqual([(rows[str(i)]['in_supplier_registry'],rows[str(i)]['active_qualifications'],rows[str(i)]['has_application'])
                          for i in range(5)],[(1,1,0),(1,1,0),(1,0,0),(0,0,1),(0,0,0)])

    def test_existing_effective_activity_respects_catalogue_and_expiry(self):
        for framework in ['ended','expired']:
            with self.subTest(framework=framework):
                with closing(sqlite3.connect(self.path)) as con, con:
                    con.execute("UPDATE registry_contracts SET framework_id=? WHERE supplier_code='0'",(framework,))
                self.refresh()
                self.assertEqual(self.rows()['0']['active_qualifications'],0)
                self.assertEqual(self.rows()['0']['in_supplier_registry'],1)

    def test_listing_never_mutates_historical_rows_or_returns_raw(self):
        self.refresh()
        with closing(sqlite3.connect(self.path)) as con, con:
            before=[con.execute('SELECT * FROM '+t).fetchall() for t in ['submissions','registry_contracts','amcu_registry','supplier_registry_summary']]
        for row in self.rows().values():
            self.assertNotIn('raw_json',row)
        with closing(sqlite3.connect(self.path)) as con, con:
            after=[con.execute('SELECT * FROM '+t).fetchall() for t in ['submissions','registry_contracts','amcu_registry','supplier_registry_summary']]
        self.assertEqual(before,after)


if __name__=='__main__':
    unittest.main()
