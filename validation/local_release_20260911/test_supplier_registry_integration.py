import json
import os
import sqlite3
import unittest
from unittest.mock import patch

import supplier_registry_integration as integration


class FullSupplierRegistryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.executescript('''CREATE TABLE submissions(
          id TEXT PRIMARY KEY,supplier_code TEXT,supplier_name TEXT,date_published TEXT,
          status TEXT,raw_json TEXT,synced_at TEXT);
        CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,manager_name TEXT,protocol_officer TEXT);
        CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT);
        CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT);
        CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,supplier_code TEXT,status TEXT,framework_id TEXT);
        CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY,supplier_name TEXT);
        CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,manager_name TEXT,source_sheet TEXT);
        CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,is_current INTEGER,
          updated_at TEXT,created_at TEXT);
        CREATE INDEX ix_q_status_submission ON qualifications(status,submission_id);
        CREATE INDEX ix_s_latest ON submissions(supplier_code,date_published DESC,id DESC);''')
        self.con.execute("INSERT INTO frameworks VALUES('f','active',?)",
          (json.dumps({'qualificationPeriod':{'endDate':'2099-01-01'}}),))
        self.addCleanup(self.con.close)

    def add(self,code,name,date,scheme='UA-EDR',qualification=None,officer='',manager='',source='',contract=None):
        sid=f's{self.con.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]+1}'
        raw=json.dumps({'tenderers':[{'identifier':{'id':code,'scheme':scheme}}]})
        self.con.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?)',(sid,code,name,date,'active',raw,date))
        self.con.execute('INSERT INTO application_fields VALUES(?,?,?)',(sid,manager,officer))
        if qualification:
            qid='q'+sid;self.con.execute('INSERT INTO qualifications VALUES(?,?,?)',(qid,sid,qualification))
        if contract:
            self.con.execute('INSERT INTO registry_contracts VALUES(?,?,?,?)',('r'+sid,code,contract,'f'))
        self.con.execute('INSERT OR REPLACE INTO supplier_registry_summary VALUES(?,?)',(code,name))
        if source:
            self.con.execute('INSERT OR REPLACE INTO supplier_edr_profiles VALUES(?,?,?)',(code,manager,source))
        return sid

    def items(self):return {x['supplier_code']:x for x in integration.full_registry(self.con)['items']}

    def test_dates_activity_uo_and_history_semantics(self):
        self.add('00000001','ACTIVE LLC','2026-01-01',qualification='active',officer='УО 1',source='ЮО',contract='active')
        self.add('00000002','REJECTED','2026-01-02',qualification='unsuccessful',source='ЮО')
        self.add('00000003','MIXED','2026-01-01',qualification='active',officer='УО OLD',source='ЮО',contract='terminated')
        self.add('00000003','MIXED NEW','2026-02-01',qualification='unsuccessful',officer='УО REJECT',source='ЮО')
        self.add('00000004','RETURNED','2026-01-01',qualification='active',officer='',source='ЮО',contract='terminated')
        self.add('00000004','RETURNED','2026-03-01',qualification='active',officer='УО NEW',source='ЮО',contract='active')
        got=self.items()
        self.assertEqual(got['00000001']['prozorro_status'],'🟢 Активний')
        self.assertEqual(got['00000002']['prozorro_status'],'🔴 Неактивний')
        self.assertIsNone(got['00000002']['last_approved_application_date'])
        self.assertEqual(got['00000003']['last_application_date'],'2026-02-01')
        self.assertEqual(got['00000003']['last_approved_application_date'],'2026-01-01')
        self.assertEqual(got['00000003']['last_approved_application_uo'],'УО OLD')
        self.assertEqual(got['00000004']['last_approved_application_date'],'2026-03-01')
        self.assertEqual(got['00000004']['last_approved_application_uo'],'УО NEW')
        self.assertEqual(got['00000004']['prozorro_status'],'🟢 Активний')

    def test_entity_identity_string_and_safe_unknown(self):
        self.add('01234567','LEGAL','2026-01-01',source='ЮО',manager='LEGAL MANAGER')
        self.add('1234567890','FOP','2026-01-01',source='ФОП',manager='FOP PERSON')
        self.add('9462717843','FOREIGN','2026-01-01',scheme='PL-NIP',source='ЮО')
        self.add('9876543210','UNKNOWN TEN DIGITS','2026-01-01',scheme='UA-EDR')
        got=self.items()
        self.assertIsInstance(got['01234567']['supplier_code'],str)
        self.assertEqual(got['01234567']['entity_type'],'legal_entity')
        self.assertEqual(got['1234567890']['entity_type'],'individual_entrepreneur')
        self.assertEqual(got['1234567890']['current_manager_name'],'FOP PERSON')
        self.assertEqual(got['9462717843']['entity_type'],'foreign_legal_entity')
        self.assertEqual(got['9876543210']['entity_type'],'unknown')

    def test_unknown_officer_and_one_row_per_supplier(self):
        self.add('11111111','OLD','2026-01-01',qualification='active',source='ЮО')
        self.add('11111111','NEW','2026-02-01',qualification='active',source='ЮО')
        response=integration.full_registry(self.con)
        self.assertEqual(response['count'],1)
        self.assertEqual(response['items'][0]['last_application_date'],'2026-02-01')
        self.assertEqual(response['items'][0]['last_approved_application_uo'],'НЕ ВИЗНАЧЕНО')


class IntegrationAuthenticationTests(unittest.TestCase):
    def handler(self,header):
        import server
        item=server.Handler.__new__(server.Handler);item.headers={'Authorization':header};item.result=None
        item.send_json=lambda body,status=200:setattr(item,'result',(body,status))
        return item

    def test_bearer_required_and_secret_not_defaulted(self):
        import server
        with patch.dict(os.environ,{},clear=True):
            item=self.handler('Bearer anything');self.assertFalse(item._authorize_supplier_registry_integration())
            self.assertEqual(item.result[1],503)
        with patch.dict(os.environ,{server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV:'secret'}):
            for header in ('','Basic c2VjcmV0','Bearer wrong'):
                item=self.handler(header);self.assertFalse(item._authorize_supplier_registry_integration());self.assertEqual(item.result[1],401)
            self.assertTrue(self.handler('Bearer secret')._authorize_supplier_registry_integration())


if __name__=='__main__':unittest.main()
