import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import google_writer_execution as execution


NOW=datetime(2026,10,13,4,0,tzinfo=timezone.utc)


class ExecutionTransportTests(unittest.TestCase):
    def client(self,environment='PROD',**options):
        self.calls=[]
        def opener(request,timeout):
            self.calls.append((request,timeout))
            payload=json.loads(json.loads(request.data)['parameters'][0]['payload'])
            result={k:payload[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
            result.update(status='PREVIEW' if payload['action']=='preview' else 'COMPLETE',digest='a'*64,counts={'update':2.0})
            return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())
        token=lambda env:{'environment':env,'access_token':'TEST_ONLY_TOKEN','scopes':sorted(execution.PROJECT_SCOPES),'expires_at':NOW.timestamp()+3600}
        args={'configured':True,'opener':opener,'clock':lambda:NOW}|options
        return execution.ExecutionClient(environment,'TEST_DEPLOYMENT_ID_NOT_CLOUD','TEST_SECRET_NON_PRODUCTION_0123456789',token,**args)

    def test_exact_deployment_and_pinned_ids_dev_mode_false(self):
        for environment in execution.IDENTITIES:
            client=self.client(environment)
            result=client.invoke('preview','b'*32,'uo')
            request,timeout=self.calls[0];body=json.loads(request.data)
            self.assertEqual(request.full_url,'https://script.googleapis.com/v1/scripts/TEST_DEPLOYMENT_ID_NOT_CLOUD:run')
            self.assertFalse(body['devMode']);self.assertEqual(timeout,390)
            self.assertEqual(body['function'],execution.IDENTITIES[environment][2])
            message=json.loads(body['parameters'][0]['payload'])
            self.assertEqual(message['spreadsheetId'],execution.IDENTITIES[environment][1])
            self.assertEqual(result['counts'],{'update':2})
            self.assertNotIn('TEST_ONLY_TOKEN',json.dumps(result))

    def test_disabled_channel_and_invalid_apply_never_touch_network(self):
        client=self.client(configured=False)
        with self.assertRaises(execution.ExecutionConfigurationError):client.invoke('preview','a'*32,'uo')
        self.assertEqual(self.calls,[])
        client=self.client()
        with self.assertRaises(ValueError):client.invoke('apply','a'*32,'uo')
        self.assertEqual(self.calls,[])

    def test_wrong_environment_scopes_or_lifetime_never_send_token(self):
        for value in [{'environment':'SANDBOX'},{'scopes':[]},{'expires_at':NOW.timestamp()+390}]:
            client=self.client()
            client.token_provider=lambda env,v=value: {'environment':env,'scopes':execution.PROJECT_SCOPES,
                'expires_at':NOW.timestamp()+3600,'access_token':'TEST_ONLY'}|v
            with self.assertRaises(execution.ExecutionConfigurationError):client.invoke('preview','a'*32,'uo')
            self.assertEqual(self.calls,[])

    def test_ticket_actor_environment_tamper_and_expiry(self):
        client=self.client();ticket=execution.preview_ticket(client,'a'*32,'uo','b'*64)
        self.assertEqual(execution.verify_ticket(client,ticket,'uo')['digest'],'b'*64)
        for user,value in [('other',ticket),('uo',ticket+'tamper')]:
            with self.assertRaises(ValueError):execution.verify_ticket(client,value,user)
        with self.assertRaises(ValueError):execution.verify_ticket(self.client('SANDBOX'),ticket,'uo')
        client.clock=lambda:NOW+timedelta(seconds=301)
        with self.assertRaises(ValueError):execution.verify_ticket(client,ticket,'uo')

    def test_network_error_and_redirect_have_no_retry_or_secret_leak(self):
        opener=Mock(side_effect=OSError('TEST_SECRET_DO_NOT_LEAK'))
        client=self.client(opener=opener)
        with self.assertRaisesRegex(execution.ExecutionOutcomeUnknown,'no automatic retry') as error:
            client.invoke('apply','a'*32,'uo',digest='b'*64)
        self.assertNotIn('TEST_SECRET_DO_NOT_LEAK',str(error.exception));self.assertEqual(opener.call_count,1)
        with self.assertRaises(execution.ExecutionOutcomeUnknown):execution.NoRedirect().redirect_request(None,None,None,None,None,None)


class ExecutionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='writer-test-')
        self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'disposable.sqlite3'
        with closing(sqlite3.connect(self.path)) as con:
            execution.migrate(con);con.commit()

    def test_defaults_preview_no_writes_apply_revision_and_restart(self):
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(execution.settings(con),{'enabled':0,'hour':7,'minute':0,'revision':0})
            count=con.total_changes
            preview=execution.preview_settings(con,{'enabled':True,'hour':8,'minute':30},NOW)
            self.assertEqual(con.total_changes,count);self.assertEqual(preview['before']['revision'],0)
            with con:execution.save_settings(con,{'enabled':True,'hour':8,'minute':30},0,'admin',NOW)
            with self.assertRaises(RuntimeError):execution.save_settings(con,{'enabled':True,'hour':9,'minute':0},0,'other')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(execution.settings(con)['revision'],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_settings_audit').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_runs').fetchone()[0],0)

    def test_manual_independent_of_disabled_schedule_parallel_and_repeated(self):
        self.assertTrue(execution.claim_run(self.path,'PROD','a'*32,'uo','manual')['claimed'])
        self.assertFalse(execution.claim_run(self.path,'PROD','b'*32,'scheduler','scheduled',0)['claimed'])
        self.assertEqual(execution.claim_run(self.path,'PROD','b'*32,'other','manual')['status'],'another_run_or_unknown_outcome')
        with self.assertRaises(PermissionError):execution.claim_run(self.path,'SANDBOX','a'*32,'uo','manual')
        execution.finish_run(self.path,'a'*32,'complete',{'status':'COMPLETE'})
        repeat=execution.claim_run(self.path,'PROD','a'*32,'uo','manual')
        self.assertFalse(repeat['claimed']);self.assertEqual(repeat['status'],'complete')

    def test_unknown_outcome_survives_restart_and_blocks_new_run(self):
        execution.claim_run(self.path,'PROD','a'*32,'uo','manual')
        execution.finish_run(self.path,'a'*32,'outcome_unknown',{'status':'UNKNOWN'})
        self.assertFalse(execution.claim_run(self.path,'PROD','b'*32,'uo','manual')['claimed'])
        self.assertTrue(execution.status(self.path,'PROD')['blocked'])

    def test_scheduled_revision_guard(self):
        with closing(sqlite3.connect(self.path)) as con,con:
            execution.save_settings(con,{'enabled':True,'hour':7,'minute':0},0,'admin')
        self.assertFalse(execution.claim_run(self.path,'PROD','a'*32,'scheduler','scheduled',0)['claimed'])
        self.assertTrue(execution.claim_run(self.path,'PROD','a'*32,'scheduler','scheduled',1)['claimed'])

    def test_both_triggers_use_same_client_preview_apply_and_partial_status(self):
        for trigger in ['manual','scheduled']:
            run=('a' if trigger=='manual' else 'b')*32
            with closing(sqlite3.connect(self.path)) as con,con:
                config=execution.settings(con)
                execution.save_settings(con,{'enabled':True,'hour':7,'minute':0},config['revision'],'admin')
                revision=execution.settings(con)['revision']
            execution.claim_run(self.path,'PROD',run,'uo',trigger,revision)
            client=Mock();client.invoke.side_effect=[{'digest':'c'*64},{'status':'PARTIAL_SAFE_OPERATIONS_REMAIN','counts':{'update':1}}]
            execution.execute_claimed(self.path,client,run,'uo',trigger=trigger)
            self.assertEqual([call.args[0] for call in client.invoke.call_args_list],['preview','apply'])
            self.assertEqual(execution.claim_run(self.path,'PROD',run,'uo',trigger)['status'],'partial')

    def test_guard_change_blocks_remote_apply(self):
        execution.claim_run(self.path,'PROD','a'*32,'uo','manual')
        client=Mock();guard=Mock(side_effect=[True,False]);client.invoke.return_value={'digest':'b'*64}
        self.assertEqual(execution.execute_claimed(self.path,client,'a'*32,'uo',guard=guard)['status'],'CONFIGURATION_REJECTED')
        self.assertEqual(client.invoke.call_count,1)

    def test_dst_gap_skip_fold_once_and_future_apply_slot(self):
        config={'hour':3,'minute':30}
        gap=execution.next_slot(config,datetime(2026,3,28,23,tzinfo=timezone.utc))
        self.assertEqual(gap.astimezone(execution.KYIV).date().isoformat(),'2026-03-30')
        first=execution.next_slot(config,datetime(2026,10,24,23,tzinfo=timezone.utc))
        self.assertEqual(first.isoformat(),'2026-10-25T00:30:00+00:00')
        self.assertEqual(execution.next_slot(config,first+timedelta(minutes=1)).astimezone(execution.KYIV).date().isoformat(),'2026-10-26')
        self.assertGreater(execution.next_slot({'hour':7,'minute':0},NOW),NOW)

    def test_disabled_job_does_not_register_or_run(self):
        factory=Mock();scheduler=execution.Scheduler(self.path,'PROD',factory,lambda:True)
        self.assertFalse(scheduler.start());factory.assert_not_called();self.assertIsNone(scheduler.thread)

    def test_waiting_loop_wakeup_revision_reschedule_and_single_completion(self):
        with closing(sqlite3.connect(self.path)) as con,con:
            execution.save_settings(con,{'enabled':True,'hour':7,'minute':1},0,'admin',NOW)
        clock=[NOW];client=Mock();waits=[]
        scheduler=execution.Scheduler(self.path,'PROD',lambda:client,lambda:True,clock=lambda:clock[0])
        def wait(seconds):
            waits.append(seconds)
            if len(waits)==1:
                with closing(sqlite3.connect(self.path)) as con,con:
                    execution.save_settings(con,{'enabled':True,'hour':8,'minute':0},1,'admin',clock[0])
                clock[0]=NOW+timedelta(minutes=1)
                scheduler.wakeup.set()
            else: clock[0]=NOW+timedelta(hours=1)
        scheduler.wakeup.wait=wait
        def invoke(action,*args,**kwargs):
            if action=='preview': return {'digest':'c'*64}
            # Editing the schedule during an active Apply must not clear its lane.
            with closing(sqlite3.connect(self.path)) as con,con:
                execution.save_settings(con,{'enabled':False,'hour':8,'minute':0},2,'admin',clock[0])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE status='running'").fetchone()[0],1)
            return {'status':'COMPLETE','counts':{'update':1}}
        client.invoke.side_effect=invoke
        scheduler.loop()
        self.assertEqual([c.args[0] for c in client.invoke.call_args_list],['preview','apply'])
        with closing(sqlite3.connect(self.path)) as con:
            rows=con.execute('SELECT revision,status FROM google_writer_runs').fetchall()
            self.assertEqual(rows,[(2,'complete')])
        self.assertGreaterEqual(len(waits),2)

    def test_duplicate_registration_reuses_listener_without_client_execution(self):
        with closing(sqlite3.connect(self.path)) as con,con:
            execution.save_settings(con,{'enabled':True,'hour':7,'minute':0},0,'admin',NOW)
        factory=Mock();scheduler=execution.Scheduler(self.path,'PROD',factory,lambda:True,clock=lambda:NOW)
        with patch.object(execution.threading,'Thread') as thread:
            thread.return_value.is_alive.return_value=True
            self.assertTrue(scheduler.start())
            self.assertFalse(scheduler.start())
            self.assertFalse(scheduler.reschedule())
            self.assertEqual(thread.call_count,1)
            thread.return_value.start.assert_called_once()
            self.assertTrue(scheduler.wakeup.is_set())
        factory.assert_not_called()


if __name__=='__main__':unittest.main()
