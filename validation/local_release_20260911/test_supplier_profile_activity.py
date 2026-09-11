"""Card KPIs must describe current qualification rows, not cached aggregates."""
import json
import sqlite3
import unittest
from unittest.mock import patch
from datetime import date,timedelta
import server
import operational_tasks


class SupplierProfileActivityTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.con.create_function('DIGITS',1,lambda value: ''.join(c for c in str(value or '') if c.isdigit()))
        self.con.create_function('NORMALIZE_NAME',1,lambda value:str(value or '').casefold())
        source=sqlite3.connect('file:data/pqm.sqlite3?mode=ro',uri=True)
        try:
            for sql, in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"):
                self.con.execute(sql)
        finally:source.close()
        self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,qualifications_count,active_count,inactive_count,refreshed_at) VALUES('3038301896','Fixture',3,3,0,'stale')")
        self.patcher=patch.object(server,'db',return_value=self.con);self.patcher.start();self.addCleanup(self.patcher.stop)

    def add(self,i,status='active',framework_status='active',days=10):
        # Match the canonical SQLite UTC date, including LOCAL midnight boundaries.
        today=date.fromisoformat(self.con.execute("SELECT date('now')").fetchone()[0])
        end=(today+timedelta(days=days)).isoformat()
        self.con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES(?,?,?,?,?)",(str(i),str(i),framework_status,json.dumps({'qualificationPeriod':{'endDate':end}}),'fixture'))
        self.con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,raw_json,synced_at) VALUES(?,?,'3038301896','Fixture','{}','fixture')",(str(i),str(i)))
        self.con.execute("INSERT INTO qualifications(id,submission_id,framework_id,status,raw_json,synced_at) VALUES(?,?,?,'active','{}','fixture')",(str(i),str(i),str(i)))
        self.con.execute("INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,raw_json,synced_at) VALUES(?,?,?,'3038301896',?,?,'fixture')",(str(i),str(i),str(i),status,json.dumps({'date':date.today().isoformat()})))

    def check(self,total,active):
        card=server.supplier_profile('3038301896')
        self.assertEqual([card['summary'][k] for k in ('qualifications_count','active_count','inactive_count')],[total,active,total-active])
        self.assertEqual(sum(q['status']=='active' for q in card['qualifications']),active)
        self.assertEqual(len(operational_tasks._effective_active_applications(self.con,'3038301896')),active)
        self.assertEqual(self.con.execute("SELECT active_count FROM supplier_registry_summary").fetchone()[0],3)

    def test_shevchuk_all_terminated_today_stale_summary(self):
        for i in range(3):self.add(i,'terminated')
        self.check(3,0)

    def test_all_active_future_period_end(self):
        for i in range(3):self.add(i)
        self.check(3,3)

    def test_mixed_and_expired_frameworks(self):
        self.add(1);self.add(2,'terminated');self.add(3,days=-1);self.add(4,framework_status='complete')
        self.check(4,1)

    def test_period_end_today_is_inclusive(self):
        self.add(1,days=0);self.check(1,1)

    def test_no_qualifications_ignores_cache(self):self.check(0,0)

if __name__=='__main__':unittest.main()
