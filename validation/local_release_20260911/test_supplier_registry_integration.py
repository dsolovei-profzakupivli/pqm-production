import json
import os
import sqlite3
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import supplier_registry_integration as integration


class FullSupplierRegistryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.create_function('DIGITS',1,integration.edr_sync_v2.normalize_code)
        self.con.executescript('''CREATE TABLE submissions(
          id TEXT PRIMARY KEY,supplier_code TEXT,supplier_name TEXT,date_published TEXT,
          status TEXT,raw_json TEXT,synced_at TEXT);
        CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,manager_name TEXT,protocol_officer TEXT,
          protocol_decision TEXT DEFAULT '',protocol_date TEXT DEFAULT '');
        CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT,decision_date TEXT);
        CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT);
        CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,supplier_code TEXT,status TEXT,framework_id TEXT,
          qualification_id TEXT);
        CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY,supplier_name TEXT,
          active_count INTEGER DEFAULT 0,suspended_count INTEGER DEFAULT 0);
        CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,manager_name TEXT,source_sheet TEXT,
          edr_checked_at TEXT DEFAULT '',edr_officer TEXT DEFAULT '',source_row INTEGER DEFAULT 0,synced_at TEXT DEFAULT '',
          edr_status TEXT DEFAULT '');
        CREATE TABLE supplier_edr_verification_events(id INTEGER PRIMARY KEY,supplier_code TEXT,
          event_type TEXT,occurred_at TEXT,snapshot_json TEXT,officer TEXT DEFAULT '',
          source TEXT DEFAULT '',source_submission_id TEXT DEFAULT '',created_at TEXT DEFAULT '');
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
        self.con.execute('INSERT INTO application_fields(submission_id,manager_name,protocol_officer) VALUES(?,?,?)',(sid,manager,officer))
        if qualification:
            qid='q'+sid;self.con.execute('INSERT INTO qualifications VALUES(?,?,?,?)',(qid,sid,qualification,date))
        if contract:
            self.con.execute('INSERT INTO registry_contracts VALUES(?,?,?,?,?)',('r'+sid,code,contract,'f',qid if qualification else None))
        self.con.execute('INSERT OR REPLACE INTO supplier_registry_summary VALUES(?,?,?,0)',
          (code,name,1 if contract=='active' else 0))
        if source:
            self.con.execute('INSERT OR REPLACE INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES(?,?,?)',(code,manager,source))
        return sid

    def items(self):return {x['supplier_code']:x for x in integration.full_registry(self.con)['items']}

    def test_monitoring_population_shared_with_register(self):
        active = self.add('00000001','ACTIVE','2026-01-01',contract='active')
        pending = self.add('00000002','PENDING','2026-01-02')
        final = self.add('00000003','FINAL','2026-01-03')
        legacy = self.add('00000004','LEGACY','2026-01-04',source='ЮО')
        self.con.execute("DELETE FROM supplier_registry_summary")
        self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count) VALUES('00000001','ACTIVE',1)")
        self.con.execute("UPDATE application_fields SET protocol_decision='reject' WHERE submission_id=?",(final,))
        got = self.items()
        self.assertEqual({code for code,item in got.items() if item['monitoring_eligible']},
                         integration.edr_sync_v2.monitoring_population_codes(self.con))
        self.assertFalse(got['00000002']['monitoring_eligible'])
        for code in ('00000001','00000003','00000004'):
            self.assertTrue(got[code]['monitoring_eligible'])
        self.assertTrue(all(type(item['monitoring_eligible']) is bool for item in got.values()))

    def test_all_freshness_buckets_and_verification_change(self):
        self.add('0013500191','SUPPLIER','2026-01-01',source='ЮО')
        cases = [('Неактивний',0,'🟣 Неактуально'),
                 ('Ще не в реєстрі',0,'🟣 Неактуально'),
                 ('Активний',29,'🟢 <30 днів'),('Активний',30,'🟡 >30 днів'),
                 ('Призупинений',60,'🟠 >60 днів'),('Активний',90,'🔴 >90 днів')]
        for status,age,expected in cases:
            checked = (date.today()-timedelta(days=age)).isoformat()
            self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at=?,edr_officer='УО' WHERE supplier_code='0013500191'",(checked,))
            with patch.object(integration.edr_sync_v2,'prozorro_statuses',return_value={'0013500191':status}):
                item=self.items()['0013500191']
                self.assertEqual(item['freshness_marker'],expected)
                self.assertEqual(item['freshness_marker'],integration.edr_sync_v2.freshness_state(status,checked)['marker'])
                self.assertEqual(item['prozorro_status_google'],integration.edr_sync_v2.google_prozorro_presentation(status))
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='',edr_officer='' WHERE supplier_code='0013500191'")
        item=self.items()['0013500191']
        self.assertEqual(item['verification_date'],'')
        self.assertEqual(item['verification_officer'],'')

    def test_google_presentation_preserves_existing_contract(self):
        self.add('00000001','ACTIVE','2026-01-01',contract='active')
        item=self.items()['00000001']
        self.assertEqual(item['prozorro_status'],'🟢 Активний')
        self.assertEqual(item['prozorro_status_google'],'✅ Активний')
        self.assertEqual(item['supplier_code'],'00000001')
        self.assertEqual(item['edr_status_current'],'Зареєстровано')

    def test_active_edr_status_uses_shared_projection_and_later_factual_check(self):
        code='46244393'
        self.add(code,'SUPPLIER','2026-09-22',qualification='active',contract='active',source='ЮО')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_status='Припинено',edr_checked_at='2026-09-01' WHERE supplier_code=?",(code,))
        item=self.items()[code]
        self.assertEqual(item['edr_status_current'],'Зареєстровано')
        self.assertEqual(item['last_application_date'],'2026-09-22')
        self.assertEqual(item['verification_date'],'2026-09-01')
        self.assertEqual(item['verification_officer'],'')
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,snapshot_json) VALUES(?,?,?,?)""",
          (code,'manual_edr','2026-09-23',json.dumps({'edr_status':'Припинено'})))
        self.assertEqual(self.items()[code]['edr_status_current'],'Припинено')

    def test_nonactive_operational_status_ui_api_parity_with_old_factual_status(self):
        import server
        inactive='00000041'
        not_registered='00000042'
        self.add(inactive,'HISTORICAL','2026-01-01',source='ЮО',
                 qualification='active',contract='terminated')
        sid=self.add(not_registered,'REJECTED','2026-01-02',source='ЮО')
        self.con.execute("UPDATE application_fields SET protocol_decision='reject' WHERE submission_id=?",(sid,))
        self.con.execute("UPDATE supplier_edr_profiles SET edr_status='Припинено' WHERE supplier_code IN (?,?)",
                         (inactive,not_registered))
        self.con.execute("DELETE FROM supplier_registry_summary WHERE supplier_code=?",(inactive,))
        with patch.object(server,'db',return_value=self.con), \
             patch.object(server,'_edr_monitoring_revision',return_value=('operational',id(self.con))):
            server.EDR_MONITORING_CACHE.update(fingerprint=None,rows=[])
            ui={row['supplier_code']:row for row in server._edr_monitoring_rows()}
        api=self.items()
        for code,expected_status in ((inactive,'Неактивний'),
                                     (not_registered,'Ще не в реєстрі')):
            with self.subTest(code=code):
                self.assertEqual(ui[code]['prozorro_status'],expected_status)
                self.assertEqual(api[code]['prozorro_status_canonical'],expected_status)
                self.assertEqual(ui[code]['edr_status'],'Неактуально')
                self.assertEqual(api[code]['edr_status_current'],'Неактуально')
                self.assertEqual(ui[code]['verification_date'],api[code]['verification_date'])
                self.assertEqual(ui[code]['verification_officer'],api[code]['verification_officer'])
        self.assertEqual(api[not_registered]['freshness_marker'],'🟣 Неактуально')
        self.assertEqual(self.con.execute("SELECT edr_status FROM supplier_edr_profiles WHERE supplier_code=?",
                                          (inactive,)).fetchone()[0],'Припинено')

    def test_non_active_edr_status_preserved_and_blank_metadata_not_substituted(self):
        code='3467208370'
        self.add(code,'SUPPLIER','2026-09-22',source='ЮО',qualification='active',contract='terminated')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_status='Неактуально' WHERE supplier_code=?",(code,))
        item=self.items()[code]
        self.assertEqual(item['edr_status_current'],'Неактуально')
        self.assertEqual(item['verification_date'],'')
        self.assertEqual(item['verification_officer'],'')
        self.assertEqual(item['last_application_date'],'2026-09-22')

    def test_reported_active_supplier_codes_have_semantic_edr_status(self):
        for code in ('3467208370','46244393'):
            with self.subTest(code=code):
                self.add(code,'SUPPLIER','2026-09-22',qualification='active',
                  contract='active',source='ЮО')
                item=self.items()[code]
                self.assertEqual(item['prozorro_status_canonical'],'Активний')
                self.assertEqual(item['edr_status_current'],'Зареєстровано')
                self.assertNotIn('✅',item['edr_status_current'])
                self.assertEqual(item['last_application_date'],'2026-09-22')
                self.assertEqual(item['verification_date'],'')
                self.assertEqual(item['verification_officer'],'')

    def test_ui_and_api_verification_projection_parity_across_sources(self):
        import server
        profile_code='00000021'
        meddata_code='00000022'
        event_code='00000023'
        self.add(profile_code,'PROFILE','2026-01-01',source='ЮО')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='2026-02-01',edr_officer='Profile UO' WHERE supplier_code=?",(profile_code,))
        sid=self.add(meddata_code,'MEDDATA','2026-01-02',source='ЮО')
        self.con.execute("UPDATE application_fields SET protocol_decision='admit',protocol_date='2026-02-02',protocol_officer='MedData UO' WHERE submission_id=?",(sid,))
        self.add(event_code,'EVENT','2026-01-03',source='ЮО')
        for kind,officer in (('google_clarity','Google UO'),('manual_edr','Manual UO')):
            self.con.execute("""INSERT INTO supplier_edr_verification_events
              (supplier_code,event_type,occurred_at,snapshot_json,officer,source,source_submission_id)
              VALUES(?,?,?,?,?,?,?)""",(event_code,kind,'2026-02-03','{}',officer,'test',''))
        with patch.object(server,'db',return_value=self.con), \
             patch.object(server,'_edr_monitoring_revision',return_value=('parity',id(self.con))):
            server.EDR_MONITORING_CACHE.update(fingerprint=None,rows=[])
            ui={row['supplier_code']:row for row in server._edr_monitoring_rows()}
        api=self.items()
        for code in (profile_code,meddata_code,event_code):
            with self.subTest(code=code):
                self.assertEqual(api[code]['verification_date'],ui[code]['verification_date'])
                self.assertEqual(api[code]['verification_officer'],ui[code]['verification_officer'])
        self.assertEqual(api[meddata_code]['verification_date'],'2026-02-02')
        self.assertEqual(api[meddata_code]['verification_officer'],'MedData UO')
        self.assertEqual(api[event_code]['verification_officer'],'Manual UO')

    def test_shared_verification_selection_preserves_blank_and_literal_identity(self):
        blank='00000031'
        foreign='39-3448689'
        domestic='393448689'
        self.add(blank,'BLANK','2026-01-01',source='ЮО')
        self.add(foreign,'FOREIGN','2026-01-01',scheme='US-EIN',source='ЮО')
        self.add(domestic,'DOMESTIC','2026-01-01',source='ФОП')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='2026-02-01',edr_officer='Domestic UO' WHERE supplier_code=?",(domestic,))
        projected=integration.edr_sync_v2.current_verification_projections(self.con,[blank,foreign,domestic])
        self.assertEqual(projected[blank]['verification_date'],'')
        self.assertEqual(projected[blank]['verification_officer'],'')
        self.assertEqual(projected[foreign]['verification_date'],'')
        self.assertEqual(projected[foreign]['verification_officer'],'')
        self.assertEqual(projected[domestic]['verification_date'],'2026-02-01')

    def test_google_supplier_name_requires_verified_edr_full_name(self):
        self.con.execute("ALTER TABLE supplier_edr_profiles ADD COLUMN full_name TEXT DEFAULT ''")
        self.add('00000001', 'LATEST APPLICATION NAME', '2026-01-01', source='ЮО')
        self.assertEqual(self.items()['00000001']['supplier_name'], '')
        self.con.execute("UPDATE supplier_edr_profiles SET full_name='VERIFIED EDR FULL NAME' WHERE supplier_code='00000001'")
        integration.reset_full_registry_cache()
        self.assertEqual(self.items()['00000001']['supplier_name'], 'VERIFIED EDR FULL NAME')

    def test_real_verification_projection_parity_and_newer_observation(self):
        code='00000001'
        self.add(code,'ACTIVE','2026-01-01',source='ЮО',contract='active')
        for age in (90,60,30,0):
            checked=(date.today()-timedelta(days=age)).isoformat()
            self.con.execute('UPDATE supplier_edr_profiles SET edr_checked_at=?,edr_officer=? WHERE supplier_code=?',
                             (checked,'УО',code))
            item=self.items()[code]
            state=integration.edr_sync_v2.canonical_supplier_edr_states(self.con,[code])[code]
            self.assertEqual(item['freshness_marker'],state['marker'])
            self.assertEqual(item['verification_date'],state['verification_date'])
            self.assertEqual(item['verification_officer'],state['verification_officer'])
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at=''")
        self.assertEqual(self.items()[code]['freshness_marker'],'⚪ Не перевірено')

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

    def test_unique_digits_profile_fallback_preserves_submission_literal_and_fop_type(self):
        self.add('AB-123456789','FOP LITERAL','2026-01-01',source='')
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('123456789','M','ФОП')")
        got=self.items()
        self.assertIn('AB-123456789',got)
        self.assertEqual(got['AB-123456789']['supplier_code'],'AB-123456789')
        self.assertEqual(got['AB-123456789']['entity_type'],'individual_entrepreneur')

    def test_digits_fallback_rejects_profile_and_submission_collisions_and_empty_digits(self):
        self.add('X-123456789','ONE','2026-01-01')
        self.add('Y-123456789','TWO','2026-01-02')
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('123456789','M','ФОП')")
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('123-456789','M','ФОП')")
        self.add('NO-DIGITS','EMPTY','2026-01-03')
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('---','M','ФОП')")
        got=self.items()
        self.assertEqual(got['X-123456789']['entity_type'],'unknown')
        self.assertEqual(got['Y-123456789']['entity_type'],'unknown')
        self.assertEqual(got['NO-DIGITS']['entity_type'],'unknown')

    def test_foreign_scheme_never_uses_digits_profile_fallback(self):
        self.add('39-3448689','FOREIGN','2026-01-01',scheme='PL-NIP')
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('393448689','M','ФОП')")
        self.assertEqual(self.items()['39-3448689']['entity_type'],'foreign_legal_entity')

    def test_unique_digits_profile_fallback_honors_yuo(self):
        self.add('AA-123456788','LEGAL','2026-01-01')
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES('123456788','M','ЮО')")
        self.assertEqual(self.items()['AA-123456788']['entity_type'],'legal_entity')

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
