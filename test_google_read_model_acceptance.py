"""Read-model acceptance on disposable fixtures; no historical/live rewrites."""
import json
import os
import unittest
from unittest.mock import patch
from datetime import date
import edr_sync_v2 as sync
from google_verification_contract import verification_timestamp
from validation.local_release_20260911 import test_supplier_registry_integration as fixtures
from validation.local_release_20260911.test_edr_sync_v2 import row, snapshot
import supplier_registry_integration as integration


class ReadModelAcceptance(unittest.TestCase):
    setUp = fixtures.FullSupplierRegistryTests.setUp
    add = fixtures.FullSupplierRegistryTests.add
    items = fixtures.FullSupplierRegistryTests.items

    def protocol(self, sid, decision, stamp, officer=''):
        self.con.execute('UPDATE application_fields SET protocol_decision=?,protocol_date=?,protocol_officer=? WHERE submission_id=?',
                         (decision, stamp, officer, sid))

    def event(self, code, kind, stamp, officer=''):
        self.con.execute('''INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,snapshot_json,officer,source)
          VALUES(?,?,?,?,?,?)''',(code,kind,stamp,json.dumps({'event_type':kind,'occurred_at':stamp}),officer,'Prozorro persisted event'))

    def test_first_pending_and_first_rejected_never_infer_verification_from_submission_or_rejection(self):
        pending=self.add('00000001','Pending','2026-10-13T12:00:00+03:00',qualification='pending')
        rejected=self.add('00000002','Rejected','2026-10-12T12:00:00+03:00',qualification='unsuccessful',source='ЮО')
        self.con.execute('''CREATE TABLE supplier_edr_sync_log(id INTEGER PRIMARY KEY,
          started_at TEXT,status TEXT,finished_at TEXT,processed INTEGER DEFAULT 0,
          inserted INTEGER DEFAULT 0,updated INTEGER DEFAULT 0,error TEXT DEFAULT '')''')
        for field in ('valid_to','valid_from','normalized_name'):
            self.con.execute(f'ALTER TABLE supplier_managers ADD COLUMN {field} TEXT')
        sync.migrate(self.con)
        # Internal controls contradict Prozorro: neither is evidence of admission.
        self.protocol(pending,'admit','2026-10-13T14:00:00+03:00','UO')
        self.protocol(rejected,'admit','2026-10-13T15:00:00+03:00','UO')
        # A rejected application remains eligible for EDR refresh, but an
        # undated Google row that changes facts must be blocked before Apply.
        source=snapshot(row(code='00000002',checked='',officer=''))
        before=self.con.total_changes
        for attempt in range(2):
            preview=sync.build_preview(self.con,source)
            self.assertIn('verification_date_required',preview['items'][0]['conflicts'])
            with self.assertRaisesRegex(ValueError,'preview'):
                sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,
                           actor='fixture',synced_at=f'2026-10-13T20:0{attempt}:00+03:00')
            self.assertEqual(self.con.total_changes,before)
        got=self.items()
        self.assertFalse(got['00000001']['google_sync_eligible'])
        self.assertTrue(got['00000002']['google_sync_eligible'])
        for code in got:
            self.assertEqual(got[code]['verification_date'],'')
            self.assertEqual(got[code]['verification_officer'],'')
            self.assertEqual(got[code]['freshness_marker'],'🟣 Неактуально')
        self.assertFalse(sync.record_admission_event(self.con,rejected,'2026-10-13T20:00:00+03:00'))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0],0)

    def test_admission_and_repeat_keep_exact_decision_time_distinct_from_submission(self):
        code='36738466'
        first=self.add(code,'First','2026-10-09T09:00:00+03:00',qualification='active',contract='active')
        self.protocol(first,'admit','2026-10-12T17:03:00+03:00','Дмитро САВВА')
        got=self.items()[code]
        self.assertEqual(got['verification_date'],'2026-10-12T17:03:00.000+03:00')
        self.assertEqual(got['last_application_date'],'2026-10-09')
        self.assertEqual(got['verification_officer'],'Дмитро САВВА')
        self.assertEqual(got['verification_datetime_precision'],'instant')
        rejected=self.add(code,'Rejected follow-up','2026-10-13T09:00:00+03:00',qualification='unsuccessful')
        self.protocol(rejected,'reject','2026-10-13T10:00:00+03:00','Other UO')
        self.event(code,'rejection','2026-10-13T10:00:00+03:00','Other UO')
        self.assertEqual(self.items()[code]['verification_date'],got['verification_date'])
        self.assertEqual(self.items()[code]['verification_officer'],got['verification_officer'])
        second=self.add(code,'Second admission','2026-10-13T11:00:00+03:00',qualification='active',contract='active')
        self.protocol(second,'admit','2026-10-13T12:01:09+03:00','New admission UO')
        got=self.items()[code]
        self.assertEqual(got['verification_date'],'2026-10-13T12:01:09.000+03:00')
        self.assertEqual(got['verification_officer'],'New admission UO')
        self.assertEqual(got['last_application_date'],'2026-10-13')

    def test_existing_prozorro_decision_source_needs_no_separate_signature_fetch(self):
        sid=self.add('00000003','Admitted','2026-10-09',qualification='active',contract='active')
        self.protocol(sid,'admit','','UO')
        self.con.execute("UPDATE qualifications SET decision_date='2026-10-12T17:03:00+03:00' WHERE submission_id=?",(sid,))
        self.assertEqual(self.items()['00000003']['verification_date'],'2026-10-12T17:03:00.000+03:00')
        self.assertEqual(self.con.execute('SELECT status FROM qualifications').fetchone()[0],'active')

    def test_active_suspended_parity_and_all_terminated_keep_historical_verification(self):
        sid=self.add('45669283','Supplier','2026-10-01',qualification='active',contract='active')
        self.protocol(sid,'admit','2026-10-02T12:05:07+03:00','UO')
        active=self.items()['45669283']
        self.con.execute("UPDATE registry_contracts SET status='suspended'")
        suspended=self.items()['45669283']
        self.assertEqual(active['freshness_marker'],suspended['freshness_marker'])
        self.assertEqual(suspended['prozorro_status_canonical'],'Призупинений')
        self.assertTrue(sync.freshness_state('Призупинений','2026-10-02',date(2026,10,13))['monitored'])
        self.con.execute("UPDATE registry_contracts SET status='terminated'")
        inactive=self.items()['45669283']
        self.assertEqual(inactive['freshness_marker'],'🟣 Неактуально')
        self.assertEqual(inactive['verification_date'],active['verification_date'])
        self.assertFalse(sync.freshness_state('Неактивний',active['verification_date'])['monitored'])

    def test_exclusion_block_and_completion_officer_provenance_without_other_event_substitution(self):
        sid=self.add('45669283','Supplier','2026-10-01',qualification='active',contract='terminated')
        self.protocol(sid,'admit','2026-10-02T10:00:00+03:00','Admission UO')
        for kind,officer,expected,day in [('exclusion','Known exclusion UO','Known exclusion UO',3),
          ('exclusion','','ЕСЗ',4),('block90','','ЕСЗ',5),('announcement_complete','','ЕСЗ',6)]:
            with self.subTest(kind=kind,officer=officer):
                stamp=f'2026-10-{day:02d}T11:12:13+03:00'
                self.event('45669283',kind,stamp,officer)
                item=self.items()['45669283']
                self.assertEqual(item['verification_date'],verification_timestamp(stamp))
                self.assertEqual(item['verification_officer'],expected)
                self.assertEqual(item['verification_event_type'],kind)
                self.assertEqual(item['freshness_marker'],'🟣 Неактуально')

    def test_unknown_admission_officer_separated_between_prod_and_sandbox(self):
        sid=self.add('00000004','Historical','2024-03-19',qualification='active',contract='active')
        self.protocol(sid,'admit','2024-03-19T12:00:00+02:00')
        for env,expected in [('0','Не визначено'),('1','Тестова УО SANDBOX')]:
            with patch.dict(os.environ,{'PQM_SANDBOX':env}):
                integration.reset_full_registry_cache()
                item=self.items()['00000004']
                self.assertEqual(item['verification_officer'],expected)
                self.assertEqual(item['verification_date'],'2024-03-19T12:00:00.000+02:00')

    def test_named_pending_followup_and_verified_edr_name_are_not_overwritten(self):
        self.con.execute("ALTER TABLE supplier_edr_profiles ADD COLUMN full_name TEXT DEFAULT ''")
        first=self.add('37325707','Decided name','2025-10-13',qualification='active',contract='active',source='ЮО')
        self.protocol(first,'admit','2025-10-14','Old UO')
        self.con.execute("UPDATE supplier_edr_profiles SET full_name='Verified EDR full name',edr_checked_at='2026-09-01T12:00:00+03:00',edr_officer='Світлана НАМЯСЕНКО',synced_at='2026-10-13T17:06:00+03:00'")
        self.add('37325707','Pending renamed application','2026-10-12',qualification='pending')
        item=self.items()['37325707']
        self.assertEqual(item['last_application_date'],'2025-10-13')
        self.assertEqual(item['supplier_name'],'Verified EDR full name')
        self.assertEqual(item['verification_date'],'2026-09-01T12:00:00.000+03:00')
        self.assertEqual(item['verification_officer'],'Світлана НАМЯСЕНКО')
        self.assertEqual(self.con.execute('SELECT supplier_name FROM submissions ORDER BY date_published DESC LIMIT 1').fetchone()[0],'Pending renamed application')

    def test_admissions_same_day_compare_instants_not_id_or_offset_strings(self):
        code='00000006'
        one=self.add(code,'Earlier decision','2026-10-01',qualification='active',contract='active')
        self.protocol(one,'admit','2026-10-12T17:03:00+03:00','Earlier UO')
        two=self.add(code,'Later decision','2026-10-02',qualification='active',contract='active')
        self.protocol(two,'admit','2026-10-12T14:04:00Z','Later UO')
        projected=sync.current_verification_projections(self.con,[code])[code]
        canonical=sync.canonical_supplier_edr_states(self.con,[code])[code]
        self.assertEqual(projected['verification_date'],'2026-10-12T17:04:00.000+03:00')
        self.assertEqual(projected['verification_officer'],'Later UO')
        self.assertEqual(canonical['verification_date'],projected['verification_date'])

    def test_edr_ui_and_writer_api_share_exclusion_date_and_esZ_provenance(self):
        import server
        sid=self.add('00000007','Supplier','2026-10-01',qualification='active',contract='terminated')
        self.protocol(sid,'admit','2026-10-02T12:00:00+03:00','Admission UO')
        self.event('00000007','exclusion','2026-10-13T12:01:02+03:00')
        with patch.object(server,'db',return_value=self.con), \
             patch.object(server,'_edr_monitoring_revision',return_value=('acceptance',id(self.con))):
            server.EDR_MONITORING_CACHE.update(fingerprint=None,rows=[])
            ui={x['supplier_code']:x for x in server._edr_monitoring_rows()}['00000007']
        api=self.items()['00000007']
        self.assertEqual(ui['verification_date'],api['verification_date'])
        self.assertEqual(ui['verification_officer'],'ЕСЗ')
        self.assertEqual(api['verification_officer'],'ЕСЗ')


if __name__ == '__main__': unittest.main()
