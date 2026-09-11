import json
import unittest
import operational_tasks as op
from test_nazk_task_relevance import NazkTaskPersonRelevanceTests

def fixture():
    base=NazkTaskPersonRelevanceTests();base.setUp();c=base.con
    c.execute("INSERT INTO authorized_officers VALUES(1,'Тестова УО',1)")
    c.execute("UPDATE registry_contracts SET status='blocked'")
    c.execute("INSERT INTO violation_reports VALUES('v','UA-D-FIXTURE','satisfied','2026-09-01','12345678','','','Test customer','UA-CONTRACT')")
    tid,_=op._create(c,'warning-fixture','warning_block','12345678','high',{'blocking_start_date':'2026-09-03','blocking_end_date':'2099-12-31','threshold_type':'3_in_1_rolling_month'}, {},status='in_progress',supplier_name='TEST ONLY')
    c.execute('INSERT INTO operational_task_warnings(task_id,violation_report_id,warning_date,sequence_no) VALUES(?,?,?,?)',(tid,'v','2026-09-01',1))
    return c,tid

PAYLOAD={'decision_date':'2026-09-01','protocol_number':'TEST-1','prozorro_url':'https://prozorro.gov.ua/uk/test-decision'}

class WarningTaskCardTests(unittest.TestCase):
    def setUp(self): self.c,self.tid=fixture()
    def tearDown(self): self.c.close()
    def test_assignment_attach_reload_idempotence_marker_and_completion(self):
        item=op.update(self.c,self.tid,{'assigned_officer_id':1},'test')
        self.assertEqual(item['assigned_officer_id'],1)
        self.assertTrue(any(e['event_type']=='assigned' for e in item['events']))
        op.attach_blocking_decision(self.c,self.tid,PAYLOAD,'test')
        op.attach_blocking_decision(self.c,self.tid,PAYLOAD,'test')
        item=op.detail(self.c,self.tid)
        self.assertEqual(item['status'],'in_progress');self.assertEqual(item['blocking_factual_state'],'blocked')
        self.assertEqual(item['blocking_decision']['protocol_number'],'TEST-1')
        self.assertEqual(sum(e['event_type']=='protocol_decision_attached' for e in item['events']),1)
        self.assertTrue(op.warning_marker_map(self.c)['UA-D-FIXTURE']['used_for_blocking'])
        op.complete_legacy_blocking(self.c,self.tid,'test')
        self.assertTrue(op.warning_marker_map(self.c)['UA-D-FIXTURE']['highlighting_active'])
        with self.assertRaisesRegex(ValueError,'лише для перегляду'):op.update(self.c,self.tid,{'assigned_officer_id':None},'test')
    def test_marker_period_and_shared_link_data(self):
        op.attach_blocking_decision(self.c,self.tid,PAYLOAD,'test')
        op.complete_legacy_blocking(self.c,self.tid,'test')
        self.assertEqual(op.detail(self.c,self.tid)['warnings'][0]['contract_pretty_id'],'UA-CONTRACT')
        for day,expected in [('2026-09-02',False),('2026-09-03',True),('2099-12-31',True),('2100-01-01',False)]:
            marker=op.warning_marker_map(self.c,day)['UA-D-FIXTURE']
            self.assertEqual(marker['highlighting_active'],expected)
            self.assertTrue(marker['used_for_blocking'])
    def test_invalid_missing_and_no_protocol(self):
        for key in ('decision_date','protocol_number','prozorro_url'):
            with self.subTest(key=key),self.assertRaises(ValueError):op.attach_blocking_decision(self.c,self.tid,{**PAYLOAD,key:''},'test')
        for url in ('https://','bad','https://evil.example/path','https://prozorro.gov.ua.evil.example'):
            with self.subTest(url=url),self.assertRaises(ValueError):op.attach_blocking_decision(self.c,self.tid,{**PAYLOAD,'prozorro_url':url},'test')
        with self.assertRaises(ValueError):op.complete_legacy_blocking(self.c,self.tid,'test')
        self.assertFalse(op.detail(self.c,self.tid)['blocking_decision'])

if __name__=='__main__':unittest.main()
