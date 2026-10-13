"""Real importer and event producer on an in-memory DB; all transport is mocked."""
import copy
import json
import unittest
from unittest.mock import patch
import edr_sync_v2 as sync
import server
from validation.local_release_20260911.test_edr_sync_v2 import database


class StatusEventProducerTests(unittest.TestCase):
    def setUp(self):
        self.con=database();self.addCleanup(self.con.close)
        for field in ('pretty_id','title','dk_code','organizer_edrpou','agreement_id','date_modified','synced_at'):
            self.con.execute(f"ALTER TABLE frameworks ADD COLUMN {field} TEXT DEFAULT ''")
        for field in ('id','qualification_id','milestones_json','raw_json','synced_at'):
            self.con.execute(f"ALTER TABLE registry_contracts ADD COLUMN {field} TEXT DEFAULT ''")
        self.con.execute('CREATE TABLE framework_service_directory(framework_id TEXT,pretty_id TEXT)')
        self.framework={'id':'f','frameworkType':'electronicCatalogue','status':'active','agreementID':'a',
          'date':'2026-09-01T10:00:00+03:00','dateModified':'2026-09-01T10:00:00+03:00',
          'qualificationPeriod':{'endDate':'2026-10-01T00:00:00+03:00'},
          'procuringEntity':{'identifier':{'id':server.ORGANIZER_EDRPOU}}}
        self.con.execute("INSERT INTO frameworks(id,status,raw_json,agreement_id) VALUES('f','active',?,'a')",(json.dumps(self.framework),))
        self.contract={'id':'c','qualificationID':'q','submissionID':'s','status':'active',
          'date':'2026-09-01T11:00:00+03:00','suppliers':[{'identifier':{'id':'44368854'}}],
          'milestones':[{'id':'m-activation','type':'activation','status':'scheduled',
             'dateModified':'2026-09-01T11:00:00+03:00','dueDate':'2026-10-01T00:00:00+03:00'}]}
        self.con.execute('''INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,raw_json)
          VALUES('c','f','q','44368854','active',?)''',(json.dumps(self.contract),))
        self.con.execute("INSERT INTO submissions VALUES('s','44368854','Supplier','2026-08-19')")
        self.con.execute("INSERT INTO application_fields VALUES('s','admit','2026-09-01T11:00:00+03:00','Admission UO','')")
        self.con.execute("INSERT INTO qualifications VALUES('q','active','s')")
        self.con.execute('CREATE UNIQUE INDEX ix_contract_fixture_id ON registry_contracts(id)')
        for field in ('manager_name','manager_name_source'):
            self.con.execute(f"ALTER TABLE application_fields ADD COLUMN {field} TEXT DEFAULT ''")
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,manager_name,edr_checked_at,edr_officer,synced_at,last_google_received_at) VALUES('44368854','Verified name','Manager','2026-09-02T11:00:00+03:00','Google UO','old technical','actual Google receipt')")
        self.con.commit()

    def previous(self):
        return dict(self.con.execute('SELECT * FROM registry_contracts WHERE id=?',('c',)).fetchone())

    def changed(self,kind='exclusion'):
        result=copy.deepcopy(self.contract)
        result['date']='2026-09-03T18:47:01.015496+03:00'
        result['dateModified']='2026-10-13T20:00:00+03:00' # unrelated later supplier/document edit
        if kind=='exclusion':
            result['status']='terminated'
            result['milestones'][0].update(status='met',dateMet=result['date'],dateModified=result['dateModified'])
        else:
            result['status']='suspended'
            result['milestones'].append({'id':'m-ban','type':'ban','status':'scheduled',
              'dateModified':result['date'],'dueDate':'2026-12-03T00:00:00+02:00'})
        return result

    def record(self,current,previous=None):
        return sync.record_prozorro_contract_status_event(self.con,'f','a',previous or self.previous(),current,
                                                        '2026-10-13T21:00:00+03:00')

    def events(self):
        return [dict(x) for x in self.con.execute('SELECT * FROM supplier_edr_verification_events ORDER BY id')]

    def test_exclusion_uses_dateMet_not_document_modification_or_sync(self):
        before=dict(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone())
        self.assertEqual(self.record(self.changed())['created'],1)
        event=self.events()[0];proof=json.loads(event['snapshot_json'])
        self.assertEqual(event['event_type'],'exclusion');self.assertEqual(event['officer'],'ЕСЗ')
        self.assertEqual(event['occurred_at'],'2026-09-03T18:47:01.015+03:00')
        self.assertEqual(proof['source_timestamp'],'2026-09-03T15:47:01.015496+00:00')
        self.assertEqual(proof['timestamp_source'],'milestone.dateMet');self.assertEqual(proof['milestone_id'],'m-activation')
        self.assertEqual(dict(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone()),before)
        state=sync.current_verification_projections(self.con,['44368854'])['44368854']
        self.assertEqual(state['verification_officer'],'ЕСЗ')
        self.assertEqual(state['verification_date'],'2026-09-03T18:47:01.015+03:00')

    def test_ban_creation_uses_status_specific_contract_date_with_causal_milestone(self):
        current=self.changed('block90');self.assertEqual(self.record(current)['created'],1)
        event=self.events()[0]
        self.assertEqual(event['event_type'],'block90');self.assertEqual(event['officer'],'ЕСЗ')
        self.assertEqual(event['occurred_at'],'2026-09-03T18:47:01.015+03:00')
        self.assertEqual(json.loads(event['snapshot_json'])['source_timestamp'],'2026-09-03T15:47:01.015496+00:00')
        self.assertNotEqual(event['occurred_at'],current['milestones'][-1]['dueDate'])
        self.assertTrue(sync.freshness_state('Призупинений','2026-09-03')['monitored'])

    def test_late_arriving_ban_does_not_replace_a_later_google_check_with_sync_time(self):
        # Screenshot control case: the 03.09 suspension precedes the 11.09 check.
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='2026-09-11T12:00:00+03:00',edr_officer='Later Google UO'")
        self.assertEqual(self.record(self.changed('block90'))['created'],1)
        current=sync.current_verification_projections(self.con,['44368854'])['44368854']
        self.assertEqual(current['verification_date'],'2026-09-11T12:00:00.000+03:00')
        self.assertEqual(current['verification_officer'],'Later Google UO')
        self.assertEqual(self.con.execute('SELECT last_google_received_at FROM supplier_edr_profiles').fetchone()[0],'actual Google receipt')

    def test_identity_replay_is_append_only_even_with_document_updates_and_new_sync_time(self):
        current=self.changed();old=self.previous();self.record(current,old)
        before=self.events();current['documents']=[{'datePublished':'2026-10-13T22:00:00+03:00'}]
        current['dateModified']='2026-10-13T23:00:00+03:00'
        self.assertEqual(self.record(current,old)['reason'],'already_recorded')
        self.assertEqual(self.events(),before)

    def test_missing_naive_invalid_or_calendar_only_timestamp_has_no_event(self):
        for value in [None,'','2026-09-03','2026-09-03T18:47:01','2026-02-30T18:47:01+03:00','2026-09-03T18:47:01+15:00']:
            for kind in ['exclusion','block90']:
                current=self.changed(kind);current['date']=value
                self.assertEqual(self.record(current)['created'],0)
        self.assertEqual(self.events(),[])

    def test_general_dateModified_or_planned_deadline_never_proves_status_transition(self):
        exclusion=self.changed();del exclusion['milestones'][0]['dateMet']
        self.assertEqual(self.record(exclusion)['created'],0)
        ban=self.changed('block90');ban['milestones'][-1]['dateModified']='2026-10-13T22:00:00+03:00'
        self.assertEqual(self.record(ban)['created'],0)
        self.assertEqual(self.events(),[])

    def test_wrong_supplier_qualification_agreement_or_duplicate_milestone_fail_closed(self):
        for mutate in [lambda x:x.update(qualificationID='other'),
          lambda x:x['suppliers'][0]['identifier'].update(id='99999999'),
          lambda x:x['milestones'].append(copy.deepcopy(x['milestones'][0]))]:
            current=self.changed();mutate(current);self.assertEqual(self.record(current)['created'],0)
        self.assertEqual(sync.record_prozorro_contract_status_event(self.con,'f','wrong',self.previous(),self.changed(),'audit')['created'],0)
        self.assertEqual(self.events(),[])

    def test_first_observation_and_same_status_never_backfill(self):
        current=self.changed()
        self.assertEqual(sync.record_prozorro_contract_status_event(self.con,'f','a',None,current,'audit')['created'],0)
        old=self.previous();old['status']='terminated'
        self.assertEqual(self.record(current,old)['reason'],'status_unchanged')
        self.assertEqual(self.events(),[])

    def test_automatic_ban_expiry_is_reactivation_not_exclusion(self):
        old=self.previous();old['status']='suspended';current=self.changed('block90');current['status']='active'
        current['milestones'][-1].update(status='met',dateMet='2026-12-03T00:01:00+02:00')
        self.assertEqual(self.record(current,old)['created'],0);self.assertEqual(self.events(),[])

    def test_previous_later_status_timestamp_cannot_be_overwritten_by_earlier_event(self):
        old=self.previous();payload=json.loads(old['raw_json']);payload['date']='2026-09-04T10:00:00+03:00';old['raw_json']=json.dumps(payload)
        self.assertEqual(self.record(self.changed(),old)['reason'],'non_increasing_status_timestamp')
        self.assertEqual(self.events(),[])

    def completion(self):
        result=copy.deepcopy(self.framework);result.update(status='complete',date='2026-10-01T00:01:19+03:00',dateModified='2026-10-13T22:00:00+03:00')
        return result

    def test_real_framework_importer_completion_and_repeat_preserve_source_time(self):
        with patch.object(server,'db',return_value=self.con):
            self.assertTrue(server.save_framework(self.completion()))
            before=self.events();self.assertEqual(len(before),1)
            self.assertTrue(server.save_framework(self.completion()))
        self.assertEqual(self.events(),before)
        self.assertEqual(before[0]['event_type'],'announcement_complete');self.assertEqual(before[0]['officer'],'ЕСЗ')
        self.assertEqual(before[0]['occurred_at'],'2026-10-01T00:01:19.000+03:00')
        canonical=sync.canonical_supplier_edr_states(self.con,['44368854'])['44368854']
        self.assertEqual(canonical['verification_date'],'2026-10-01T00:01:19.000+03:00')
        self.assertEqual(json.loads(before[0]['snapshot_json'])['timestamp_source'],'framework.date')

    def test_completed_framework_without_status_time_does_not_guess_endDate_or_modified(self):
        for stamp in ['',self.framework['date'],'2026-09-30T12:00:00+03:00']:
            current=self.completion();current['date']=stamp
            old=dict(self.con.execute('SELECT * FROM frameworks').fetchone())
            self.assertEqual(sync.record_prozorro_framework_status_event(self.con,old,current,'audit')['created'],0)
        current=self.completion();current['status']='active'
        old=dict(self.con.execute('SELECT * FROM frameworks').fetchone())
        self.assertEqual(sync.record_prozorro_framework_status_event(self.con,old,current,'audit')['created'],0)
        self.assertEqual(self.events(),[])

    def test_completion_does_not_refresh_members_already_excluded(self):
        self.con.execute("UPDATE registry_contracts SET status='terminated'")
        with patch.object(server,'db',return_value=self.con):server.save_framework(self.completion())
        self.assertEqual(self.events(),[])

    def test_real_sync_importer_contract_transition_is_idempotent_with_all_network_mocked(self):
        for kind in ['exclusion','block90']:
            with self.subTest(kind=kind):
                self.con.execute('DELETE FROM supplier_edr_verification_events')
                self.con.execute("UPDATE registry_contracts SET status='active',raw_json=?",(json.dumps(self.contract),))
                current=self.changed(kind)
                with patch.object(server,'db',return_value=self.con), \
                     patch.object(server,'scoped_pages',return_value=[]), \
                     patch.object(server,'paginated_pages',return_value=[[current]]) as pages, \
                     patch.object(server,'enqueue_contract_experience_search'), \
                     patch.object(server,'api_get') as network:
                    server.sync_one_framework('f',self.framework)
                    self.assertEqual(len(self.events()),1)
                    before=self.events();server.sync_one_framework('f',self.framework)
                self.assertEqual(self.events(),before);network.assert_not_called()
                self.assertTrue(all('/agreements/a/contracts' in call.args[0] for call in pages.call_args_list))
                self.assertEqual(self.con.execute('SELECT last_google_received_at FROM supplier_edr_profiles').fetchone()[0],'actual Google receipt')
                self.assertEqual(self.con.execute('SELECT status FROM qualifications').fetchone()[0],'active')


if __name__=='__main__': unittest.main()
