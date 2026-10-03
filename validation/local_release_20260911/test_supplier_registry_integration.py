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
          status TEXT,raw_json TEXT,synced_at TEXT,qualification_id TEXT);
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
        self.con.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?)',(sid,code,name,date,'active',raw,date,None))
        self.con.execute('INSERT INTO application_fields(submission_id,manager_name,protocol_officer) VALUES(?,?,?)',(sid,manager,officer))
        if qualification:
            qid='q'+sid;self.con.execute('INSERT INTO qualifications VALUES(?,?,?,?)',(qid,sid,qualification,date))
            self.con.execute('UPDATE submissions SET qualification_id=? WHERE id=?',(qid,sid))
        if contract:
            self.con.execute('INSERT INTO registry_contracts VALUES(?,?,?,?,?)',('r'+sid,code,contract,'f',qid if qualification else None))
        self.con.execute('INSERT OR REPLACE INTO supplier_registry_summary VALUES(?,?,?,0)',
          (code,name,1 if contract=='active' else 0))
        if source:
            self.con.execute('INSERT OR REPLACE INTO supplier_edr_profiles(supplier_code,manager_name,source_sheet) VALUES(?,?,?)',(code,manager,source))
        return sid

    def items(self):return {x['supplier_code']:x for x in integration.full_registry(self.con)['items']}

    def test_sandbox_endpoint_uses_shared_projection_and_allows_unavailable_officer(self):
        sid = self.add('00000009', 'Остання заявка', '2026-09-20',
                       qualification='active', manager='Керівник')
        self.con.execute("UPDATE application_fields SET protocol_date='2026-09-20' WHERE submission_id=?", (sid,))
        result = integration.eligible_full_registry(self.con, projection_policy='sandbox')
        self.assertEqual(result['projection_contract'], 'shared_edr_v1')
        item = result['items'][0]
        self.assertEqual(item['last_application_date'], '2026-09-20')
        self.assertEqual(item['edr_status_current'], 'Зареєстровано')
        self.assertEqual(item['verification_date'], '2026-09-20')
        self.assertIsNone(item['verification_officer'])
        self.assertEqual(item['shared_projection']['provenance']['L']['officer_availability'],
                         'unavailable_in_sandbox')

    def test_verified_google_name_is_distinct_from_working_c_name(self):
        sid = self.add('00000009', 'Заявка А', '2026-09-20', qualification='active')
        self.con.execute("UPDATE application_fields SET protocol_date='2026-09-20' WHERE submission_id=?", (sid,))
        self.con.execute("ALTER TABLE supplier_edr_profiles ADD COLUMN full_name TEXT DEFAULT ''")
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name) VALUES('00000009','Назва ЄДР')")
        self.con.execute("""CREATE TABLE supplier_working_names(supplier_code TEXT PRIMARY KEY,
          working_name TEXT,source_type TEXT,source_id TEXT,event_date TEXT)""")
        self.con.execute("INSERT INTO supplier_working_names VALUES('00000009','Робоча назва Б','google_verified_name','event-1','2026-09-21')")
        item = integration.eligible_full_registry(self.con, projection_policy='sandbox')['items'][0]
        self.assertEqual(item['supplier_name'], 'Назва ЄДР')
        self.assertEqual(item['shared_projection']['working_supplier_name'], 'Робоча назва Б')
        self.assertTrue(item['shared_projection']['working_name_update_confirmed'])

    def test_sandbox_edr_ui_and_registry_share_business_state(self):
        import server
        sid = self.add('00000009', 'Заявка А', '2026-09-20', qualification='active')
        self.con.execute("UPDATE application_fields SET protocol_date='2026-09-20' WHERE submission_id=?", (sid,))
        endpoint = integration.eligible_full_registry(self.con, projection_policy='sandbox')['items'][0]
        with patch.object(server, 'SANDBOX_MODE', True), patch.object(server, 'db', return_value=self.con), \
             patch.object(server, '_edr_monitoring_revision', return_value=('sandbox-fixture',)):
            server.EDR_MONITORING_CACHE.update(fingerprint=None, rows=[])
            ui = next(row for row in server._edr_monitoring_rows() if row['supplier_code'] == '00000009')
        self.assertEqual(ui['edr_status'], endpoint['edr_status_current'])
        self.assertEqual(ui['verification_date'], endpoint['verification_date'])
        self.assertEqual(ui['verification_officer'], endpoint['verification_officer'])
        self.assertEqual(ui['latest_application_date'], endpoint['last_application_date'])
        self.assertEqual(ui['manager_name'], endpoint['current_manager_name'])

    def test_sandbox_edr_monitoring_covers_literal_population_with_outer_whitespace(self):
        import server
        self.add('00000009', 'ACTIVE', '2026-09-20', qualification='active')
        self.add('2981209581 ', 'TRAILING SPACE', '2026-09-21',
                 qualification='active', contract='active')
        self.add(' 00000010', 'LEADING SPACE', '2026-09-21', qualification='unsuccessful')
        self.add('\u200300000011\u00a0', 'UNICODE OUTER SPACE', '2026-09-21',
                 qualification='unsuccessful')
        self.add('СР 918414', 'INTERNAL SPACE', '2026-09-22', qualification='unsuccessful')
        population = integration.edr_sync_v2.monitoring_population_codes(self.con)
        with patch.object(server, 'SANDBOX_MODE', True), patch.object(server, 'db', return_value=self.con), \
             patch.object(server, '_edr_monitoring_revision', return_value=('literal-population',)):
            server.EDR_MONITORING_CACHE.update(fingerprint=None, rows=[])
            response = server.list_edr_monitoring({'page': ['1'], 'size': ['100']})
        rows = {row['supplier_code']: row for row in response['items']}
        self.assertEqual(set(rows), population)
        self.assertEqual(response['total'], len(population))
        self.assertEqual(rows['2981209581 ']['shared_projection']['supplier_code'], '2981209581 ')
        self.assertIsNone(rows['2981209581 ']['verification_date'])
        self.assertIsNone(rows['2981209581 ']['verification_officer'])
        self.assertEqual(rows['2981209581 ']['freshness'], 'not_checked')
        self.assertEqual(rows['2981209581 ']['prozorro_status'], 'Активний')
        self.assertEqual(rows[' 00000010']['shared_projection']['supplier_code'], ' 00000010')
        self.assertIsNone(rows[' 00000010']['verification_date'])
        self.assertEqual(rows['\u200300000011\u00a0']['shared_projection']['supplier_code'],
                         '\u200300000011\u00a0')
        self.assertIsNone(rows['\u200300000011\u00a0']['verification_date'])
        self.assertIn('СР 918414', rows)

    def test_resolver_retains_collision_guard_for_outer_whitespace_variants(self):
        import supplier_edr_projection
        self.add('2981209581 ', 'TRAILING', '2026-09-21', qualification='active')
        self.add('2981209581', 'PLAIN', '2026-09-22', qualification='unsuccessful')
        population = integration.edr_sync_v2.monitoring_population_codes(self.con)
        projected = supplier_edr_projection.resolve_supplier_edr_business_state(
            self.con, population, environment_policy='sandbox')
        self.assertTrue(population.issubset(projected))
        for code in population:
            self.assertEqual(projected[code]['supplier_code'], code)
            self.assertIn('outer_whitespace_identity_collision', projected[code]['conflicts'])

    def test_resolver_does_not_silently_merge_unicode_outer_whitespace_collision(self):
        import supplier_edr_projection
        self.add('00000012', 'PLAIN', '2026-09-21', qualification='active')
        self.add('\u00a000000012', 'NBSP PREFIX', '2026-09-22', qualification='unsuccessful')
        population = integration.edr_sync_v2.monitoring_population_codes(self.con)
        projected = supplier_edr_projection.resolve_supplier_edr_business_state(
            self.con, population, environment_policy='sandbox')
        self.assertTrue(population.issubset(projected))
        for code in population:
            self.assertEqual(projected[code]['supplier_code'], code)
            self.assertIn('outer_whitespace_identity_collision', projected[code]['conflicts'])

    def test_endpoint_exact_shared_set_excludes_prod_only_ten(self):
        endpoint_only = ('1922319119', '25586283', '2617901540', '3069605914',
                         '3292301719', '3315012247', '39369840', '40323076',
                         '44726167', '45614852')
        for code in endpoint_only:
            sid = self.add(code, 'PENDING', '2026-09-20')
            self.con.execute("UPDATE application_fields SET protocol_decision='reject' WHERE submission_id=?", (sid,))
        self.add('00000001', 'ADMITTED', '2026-09-21', qualification='active')
        self.add('AB-008', 'REJECTED', '2026-09-22', qualification='unsuccessful')
        self.add('2981209581 ', 'OUTER SPACE', '2026-09-23', qualification='active')
        result = integration.eligible_full_registry(self.con)
        actual = {item['supplier_code'] for item in result['items']}
        expected = {code.strip() for code in integration.edr_sync_v2.monitoring_population_codes(self.con)}
        self.assertEqual(actual, expected)
        self.assertEqual(result['count'], len(expected))
        self.assertEqual(actual, {'00000001', 'AB-008', '2981209581'})
        self.assertFalse(actual.intersection(endpoint_only))
        self.assertTrue(all(item['google_sync_eligible'] for item in result['items']))

    def test_endpoint_rejects_outer_whitespace_identity_collision(self):
        self.add('2981209581 ', 'FIRST', '2026-09-20', qualification='active')
        self.add('2981209581', 'SECOND', '2026-09-21', qualification='unsuccessful')
        with self.assertRaisesRegex(ValueError, 'Ambiguous supplier code'):
            integration.eligible_full_registry(self.con)

    def test_shared_literal_qualification_eligibility_and_active_priority(self):
        cases = {
            '00000001': ([None], None),
            '00000002': (['unsuccessful'], 'Ще не в реєстрі'),
            '00000003': (['active'], 'Активний'),
            '00000004': (['unsuccessful', None], 'Ще не в реєстрі'),
            '00000005': (['active', None], 'Активний'),
            '00000006': (['unsuccessful', 'active'], 'Активний'),
            'AB-008': (['active', 'active'], 'Активний'),
            'PENDING-X': (['pending'], None),
        }
        for code, (statuses, _) in cases.items():
            for index, status in enumerate(statuses):
                self.add(code, code, f'2026-01-{index + 1:02d}', qualification=status)
        self.con.execute("UPDATE application_fields SET protocol_decision='admit'")
        expected = {code for code, (_, status) in cases.items() if status}
        self.assertEqual(integration.edr_sync_v2.monitoring_population_codes(self.con), expected)
        endpoint = {item['supplier_code']: item for item in integration.eligible_full_registry(self.con)['items']}
        self.assertEqual(set(endpoint), expected)
        self.assertEqual({code: status for code, status in integration.edr_sync_v2.monitoring_eligibility(self.con).items()},
                         {code: status for code, (_, status) in cases.items() if status})
        self.assertEqual(endpoint['00000006']['google_sync_eligible'], True)
        self.assertNotIn('PENDING-X', endpoint)

    def test_new_confirmed_ua_edr_routes_to_legal_entity_without_profile(self):
        self.add('46130719', 'NEW LEGAL ENTITY', '2026-09-27', scheme='UA-EDR')
        self.assertEqual(self.items()['46130719']['entity_type'], 'legal_entity')
        self.assertFalse(self.items()['46130719']['monitoring_eligible'])
        self.add('12345678', 'UNCONFIRMED', '2026-09-27', scheme='')
        self.assertEqual(self.items()['12345678']['entity_type'], 'unknown')

    def test_google_sync_requires_decision_and_pending_followup_does_not_advance_h(self):
        first = self.add('00000081', 'FIRST', '2026-09-20', source='ЮО')
        pending = self.items()['00000081']
        self.assertFalse(pending['google_sync_eligible'])
        self.assertIsNone(pending['google_sync_last_decided_application_date'])
        self.con.execute("UPDATE application_fields SET protocol_decision='reject' WHERE submission_id=?", (first,))
        self.assertFalse(self.items()['00000081']['google_sync_eligible'])
        self.con.execute("INSERT INTO qualifications VALUES(?,?,?,?)", ('q'+first,first,'unsuccessful','2026-09-20'))
        self.con.execute("UPDATE submissions SET qualification_id=? WHERE id=?", ('q'+first,first))
        decided = self.items()['00000081']
        self.assertTrue(decided['google_sync_eligible'])
        self.assertEqual(decided['google_sync_last_decided_application_date'], '2026-09-20')
        self.add('00000081', 'FOLLOWUP', '2026-09-25', source='ЮО')
        followup = self.items()['00000081']
        self.assertTrue(followup['google_sync_eligible'])
        self.assertEqual(followup['last_application_date'], '2026-09-25')
        self.assertEqual(followup['google_sync_last_decided_application_date'], '2026-09-20')
        self.assertEqual(followup['prozorro_status_google'], decided['prozorro_status_google'])
        later = self.add('00000081', 'SECOND DECISION', '2026-09-27', source='ЮО')
        self.con.execute("UPDATE application_fields SET protocol_decision='admit' WHERE submission_id=?", (later,))
        self.con.execute("INSERT INTO qualifications VALUES(?,?,?,?)", ('q'+later,later,'active','2026-09-27'))
        self.con.execute("UPDATE submissions SET qualification_id=? WHERE id=?", ('q'+later,later))
        self.assertEqual(self.items()['00000081']['google_sync_last_decided_application_date'],
                         '2026-09-27')

    def test_monitoring_population_shared_with_register(self):
        active = self.add('00000001','ACTIVE','2026-01-01',qualification='active',contract='active')
        pending = self.add('00000002','PENDING','2026-01-02')
        final = self.add('00000003','FINAL','2026-01-03',qualification='unsuccessful')
        legacy = self.add('00000004','LEGACY','2026-01-04',source='ЮО')
        self.con.execute("DELETE FROM supplier_registry_summary")
        self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count) VALUES('00000001','ACTIVE',1)")
        self.con.execute("UPDATE application_fields SET protocol_decision='reject' WHERE submission_id=?",(final,))
        got = self.items()
        self.assertEqual({code for code,item in got.items() if item['monitoring_eligible']},
                         integration.edr_sync_v2.monitoring_population_codes(self.con))
        self.assertFalse(got['00000002']['monitoring_eligible'])
        for code in ('00000001','00000003'):
            self.assertTrue(got[code]['monitoring_eligible'])
        self.assertFalse(got['00000004']['monitoring_eligible'])
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
        sid=self.add(not_registered,'REJECTED','2026-01-02',source='ЮО',qualification='unsuccessful')
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
        self.add(profile_code,'PROFILE','2026-01-01',source='ЮО',qualification='active')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='2026-02-01',edr_officer='Profile UO' WHERE supplier_code=?",(profile_code,))
        sid=self.add(meddata_code,'MEDDATA','2026-01-02',source='ЮО',qualification='active')
        self.con.execute("UPDATE application_fields SET protocol_decision='admit',protocol_date='2026-02-02',protocol_officer='MedData UO' WHERE submission_id=?",(sid,))
        self.add(event_code,'EVENT','2026-01-03',source='ЮО',qualification='unsuccessful')
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
        self.assertEqual(self.items()['00000001']['latest_submission_name'], 'LATEST APPLICATION NAME')
        self.con.execute("UPDATE supplier_edr_profiles SET full_name='VERIFIED EDR FULL NAME' WHERE supplier_code='00000001'")
        integration.reset_full_registry_cache()
        self.assertEqual(self.items()['00000001']['supplier_name'], 'VERIFIED EDR FULL NAME')
        self.assertEqual(self.items()['00000001']['latest_submission_name'], 'LATEST APPLICATION NAME')

    def test_latest_submission_name_is_separate_literal_application_data(self):
        for code in ('2981209581 ', 'СР 918414', '00123456', 'AB-008'):
            self.add(code, 'OLDER', '2026-01-01', qualification='active')
            self.add(code, ' LATEST NAME ', '2026-02-01')
        self.add('EMPTY-ID', '', '2026-02-01', qualification='unsuccessful')
        items = self.items()
        for code in ('2981209581', 'СР 918414', '00123456', 'AB-008'):
            self.assertEqual(items[code]['supplier_name'], '')
            self.assertEqual(items[code]['latest_submission_name'], 'LATEST NAME')
        self.assertEqual(items['EMPTY-ID']['latest_submission_name'], '')
        self.assertEqual(items['СР 918414']['supplier_code'], 'СР 918414')
        self.assertEqual(items['00123456']['supplier_code'], '00123456')

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
