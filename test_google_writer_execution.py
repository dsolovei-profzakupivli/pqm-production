import io
import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock, patch
import google_writer_execution as execution
import execution_apply_contract
import auth_access


NOW=datetime(2026,10,13,4,0,tzinfo=timezone.utc)
TEST_DIGEST=base64.urlsafe_b64encode(hashlib.sha256(b'PQM synthetic Preview digest').digest()).decode().rstrip('=')


class ExecutionTransportTests(unittest.TestCase):
    def client(self,environment='PROD',**options):
        self.calls=[]
        def opener(request,timeout):
            self.calls.append((request,timeout))
            payload=json.loads(json.loads(request.data)['parameters'][0]['payload'])
            result={k:payload[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
            result.update(status='PREVIEW' if payload['action']=='preview' else 'COMPLETE',digest=TEST_DIGEST,counts={'update':2.0})
            if payload['action']=='preview' and payload['environment']=='SANDBOX':
                result['counts']={'append':1,'update':1,'conflict':1,'error':0}
                result['planDetails']={'version':1,'environment':'SANDBOX','plan_digest':TEST_DIGEST,
                    'append_only_digest':execution.is_canonical_sha256_b64url(TEST_DIGEST) and
                        base64.urlsafe_b64encode(hashlib.sha256(b'append-only').digest()).decode().rstrip('='),
                    'counts':result['counts'],'appends':[{'operation':'APPEND','cells':[
                        {'column':'A','formula':True},{'column':'B','formula':False}]}],
                    'updates':[{'operation':'UPDATE','cells':[{'column':'E','formula':False}]}],
                    'conflicts':[{'reason':'routing_mismatch'}],'errors':[]}
            if payload['action']=='apply' and execution_apply_contract.checkpoint_apply_enabled(payload['environment']):
                result.update(chunkIndex=payload['chunkIndex'],nextChunk=payload['chunkIndex']+1,
                    more=False,phase='append',checkpointDigest=TEST_DIGEST)
                if payload['environment']=='SANDBOX':
                    result['planScope']=payload['planScope']
                    if payload['planScope']=='APPEND_ONLY':result['counts']={'append':1,'update':0,'conflict':1,'error':0}
            if payload['action']=='resume_check':
                result.update(status='RESUME_READY',digest=payload['expectedDigest'],planScope='APPEND_ONLY',
                    chunkIndex=payload['chunkIndex'],nextChunk=payload['chunkIndex'],
                    checkpointDigest=payload['expectedCheckpointDigest'],
                    counts={'append':1,'update':0,'conflict':0,'error':0,'remaining_safe':1})
                result['planDetails']={'version':1,'environment':'SANDBOX','plan_digest':payload['expectedDigest'],
                    'remaining_plan_digest':TEST_DIGEST,'counts':{'append':1,'update':0,'conflict':0,'error':0},
                    'appends':[{'operation':'APPEND','cells':[{'column':'A','formula':True}]}],
                    'updates':[],'conflicts':[],'errors':[]}
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
            self.assertEqual(result['counts'],{'append':1,'update':1,'conflict':1,'error':0}
                if environment=='SANDBOX' else {'update':2})
            self.assertNotIn('TEST_ONLY_TOKEN',json.dumps(result))

    def test_production_apply_keeps_legacy_single_call_receipt_contract(self):
        client=self.client('PROD')
        result=client.invoke('apply','f'*32,'uo',digest=TEST_DIGEST)
        payload=json.loads(json.loads(self.calls[0][0].data)['parameters'][0]['payload'])
        self.assertNotIn('chunkIndex',payload)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertNotIn('nextChunk',result)

    def test_shared_checkpoint_architecture_can_be_enabled_by_environment_only(self):
        self.assertTrue(execution_apply_contract.checkpoint_apply_enabled('SANDBOX'))
        self.assertFalse(execution_apply_contract.checkpoint_apply_enabled('PROD'))
        with patch.object(execution_apply_contract,'CHECKPOINT_APPLY_ENVIRONMENTS',frozenset({'SANDBOX','PROD'})):
            self.assertTrue(execution_apply_contract.checkpoint_apply_enabled('PROD'))
            client=self.client('PROD')
            result=client.invoke('apply','e'*32,'uo',digest=TEST_DIGEST,chunk_index=4)
            payload=json.loads(json.loads(self.calls[0][0].data)['parameters'][0]['payload'])
            self.assertEqual(payload['chunkIndex'],4)
            self.assertEqual(result['nextChunk'],5)
            self.assertNotIn('planScope',payload)
            self.assertNotIn('planScope',result)

    def test_sandbox_preview_requires_bound_detail_receipt(self):
        client=self.client('SANDBOX')
        result=client.invoke('preview','b'*32,'uo',manual_authorized=True)
        payload=json.loads(json.loads(self.calls[0][0].data)['parameters'][0]['payload'])
        self.assertEqual(payload['action'],'preview')
        self.assertEqual(len(result['planDetails']['appends']),1)
        self.assertEqual(result['planDetails']['counts']['update'],1)

    def test_append_only_cannot_fall_back_to_unscoped_legacy_transport(self):
        with patch.object(execution_apply_contract,'CHECKPOINT_APPLY_ENVIRONMENTS',frozenset()):
            client=self.client('SANDBOX')
            with self.assertRaises(execution.ExecutionConfigurationError):
                client.invoke('apply','b'*32,'uo',digest=TEST_DIGEST,plan_scope='APPEND_ONLY')
            self.assertEqual(self.calls,[])

    def test_resume_check_is_sandbox_manual_read_only_and_digest_bound(self):
        client=self.client('SANDBOX')
        result=client.invoke('resume_check','c'*32,'uo',trigger='manual',digest=TEST_DIGEST,
            plan_scope='APPEND_ONLY',manual_authorized=True,chunk_index=3,
            expected_checkpoint_digest=TEST_DIGEST)
        payload=json.loads(json.loads(self.calls[0][0].data)['parameters'][0]['payload'])
        self.assertEqual(payload['action'],'resume_check')
        self.assertEqual(payload['planScope'],'APPEND_ONLY')
        self.assertEqual(payload['expectedCheckpointDigest'],TEST_DIGEST)
        self.assertEqual(result['status'],'RESUME_READY')
        self.assertEqual(result['counts']['update'],0)
        self.assertEqual(result['planDetails']['updates'],[])
        with self.assertRaises(ValueError):
            client.invoke('resume_check','c'*32,'uo',digest=TEST_DIGEST,plan_scope='ALL',
                manual_authorized=True,chunk_index=3,expected_checkpoint_digest=TEST_DIGEST)
        prod=self.client('PROD')
        with self.assertRaises(ValueError):
            prod.invoke('resume_check','c'*32,'uo',digest=TEST_DIGEST,plan_scope='APPEND_ONLY',
                manual_authorized=True,chunk_index=3,expected_checkpoint_digest=TEST_DIGEST)

    def test_http_503_timeout_and_lost_response_after_apply_are_unknown_without_retry(self):
        for failure in (TimeoutError('synthetic timeout'),HTTPError('https://script.googleapis.com',503,'Service Unavailable',{},io.BytesIO()),
                        OSError('synthetic lost response')):
            opener=Mock(side_effect=failure);client=self.client('SANDBOX',opener=opener)
            with self.assertRaises(execution.ExecutionOutcomeUnknown):
                client.invoke('apply','d'*32,'uo',digest=TEST_DIGEST,plan_scope='APPEND_ONLY',
                    manual_authorized=True,expected_checkpoint_digest=None)
            self.assertEqual(opener.call_count,1)

    def test_token_failure_is_known_before_execution_api_call(self):
        client=self.client('SANDBOX')
        client.token_provider=lambda env: (_ for _ in ()).throw(OSError('oauth unavailable'))
        with self.assertRaises(execution.ExecutionPreflightError):
            client.invoke('apply','e'*32,'uo',digest=TEST_DIGEST,plan_scope='APPEND_ONLY',
                manual_authorized=True)
        self.assertEqual(self.calls,[])

    def test_resume_check_503_or_timeout_is_read_only_preflight_not_unknown_apply(self):
        for failure in (TimeoutError('synthetic timeout'),HTTPError('https://script.googleapis.com',503,'Service Unavailable',{},io.BytesIO())):
            opener=Mock(side_effect=failure);client=self.client('SANDBOX',opener=opener)
            with self.assertRaises(execution.ExecutionPreflightError):
                client.invoke('resume_check','f'*32,'uo',trigger='manual',digest=TEST_DIGEST,
                    plan_scope='APPEND_ONLY',manual_authorized=True,chunk_index=1,
                    expected_checkpoint_digest=TEST_DIGEST)
            self.assertEqual(opener.call_count,1,'read-only preflight is attempted once without retry')


class PreviewPlanScopeTests(ExecutionTransportTests):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='preview-plan-test-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'preview.sqlite3'
        with closing(sqlite3.connect(self.path)) as con:
            execution.migrate(con);con.commit()
        self.scope_client=ExecutionTransportTests().client('SANDBOX')
        self.details={'version':1,'environment':'SANDBOX','plan_digest':TEST_DIGEST,
            'append_only_digest':base64.urlsafe_b64encode(hashlib.sha256(b'append-scope').digest()).decode().rstrip('='),
            'counts':{'append':1,'update':1,'conflict':1,'error':0},
            'appends':[{'operation':'APPEND','code':'000123','cells':[
                {'column':'A','formula':True,'new_value':'=TODAY()'},
                {'column':'B','formula':False,'new_value':'000123'}]}],
            'updates':[{'operation':'UPDATE','code':'000124','cells':[
                {'column':'E','formula':False,'old_value':'old','new_value':'new'}]}],
            'conflicts':[{'reason':'routing_mismatch'}],'errors':[]}
        self.request_id='a'*32
        self.stored=execution.store_preview_plan(self.path,self.request_id,'uo',self.details,now=NOW)
        self.all_ticket=execution.preview_ticket(self.scope_client,self.request_id,'uo',TEST_DIGEST,
            plan_scope='ALL',parent_digest=TEST_DIGEST,details_digest=self.stored['details_digest'])

    def test_details_read_and_scope_mutation_use_the_existing_writer_permission(self):
        self.assertEqual(auth_access.permission_key('GET','/api/google-writer/preview-details/'+'a'*32),
            'google.writer.execute')
        self.assertEqual(auth_access.permission_key('POST','/api/google-writer/preview-scope'),
            'google.writer.execute')
        self.assertEqual(auth_access.permission_key('POST','/api/google-writer/resume-preview'),
            'google.writer.execute')
        self.assertEqual(auth_access.permission_key('POST','/api/google-writer/resume-append-only'),
            'google.writer.execute')
        self.assertIsNone(auth_access.permission_key('GET','/api/google-writer/preview-details/not-a-request-id'))

    def test_immutable_snapshot_is_actor_digest_and_ttl_bound(self):
        loaded=execution.load_preview_plan(self.path,self.request_id,'uo',TEST_DIGEST,
            details_digest=self.stored['details_digest'],now=NOW)
        self.assertEqual(loaded['details'],self.details)
        with self.assertRaises(ValueError):execution.load_preview_plan(self.path,self.request_id,'other',TEST_DIGEST,now=NOW)
        with self.assertRaises(ValueError):execution.load_preview_plan(self.path,self.request_id,'uo',
            base64.urlsafe_b64encode(hashlib.sha256(b'wrong').digest()).decode().rstrip('='),now=NOW)
        with self.assertRaises(ValueError):execution.load_preview_plan(self.path,self.request_id,'uo',TEST_DIGEST,
            details_digest=base64.urlsafe_b64encode(hashlib.sha256(b'wrong details').digest()).decode().rstrip('='),now=NOW)
        with self.assertRaises(ValueError):execution.load_preview_plan(self.path,self.request_id,'uo',TEST_DIGEST,
            details_digest=self.stored['details_digest'],now=NOW+timedelta(seconds=300))

    def test_append_only_ticket_binds_scope_and_excludes_updates_server_side(self):
        parent=execution.verify_ticket(self.scope_client,self.all_ticket,'uo')
        full=execution.load_preview_plan(self.path,parent['request_id'],'uo',parent['parent_digest'],
            details_digest=parent['details_digest'],now=NOW)
        self.assertEqual(execution.validate_preview_plan_scope(full,parent),
            {'scope':'ALL','append':1,'update':1,'conflict':1,'error':0})
        append_ticket=execution.preview_ticket(self.scope_client,self.request_id,'uo',full['append_only_digest'],
            plan_scope='APPEND_ONLY',parent_digest=full['plan_digest'],details_digest=full['details_digest'])
        scoped=execution.verify_ticket(self.scope_client,append_ticket,'uo')
        selected=execution.validate_preview_plan_scope(full,scoped)
        self.assertEqual(selected,{'scope':'APPEND_ONLY','append':1,'update':0,'conflict':1,'error':0})
        with self.assertRaises(ValueError):execution.validate_preview_plan_scope(full,scoped|{'digest':TEST_DIGEST})
        with self.assertRaises(ValueError):execution.verify_ticket(self.scope_client,append_ticket+'tamper','uo')

    def test_resume_ticket_is_bound_to_checkpoint_details_and_strict_five_minute_ttl(self):
        ticket=execution.append_only_resume_ticket(self.scope_client,self.request_id,'uo',TEST_DIGEST,2,
            TEST_DIGEST,self.stored['details_digest'])
        value=execution.verify_append_only_resume_ticket(self.scope_client,ticket,'uo')
        self.assertEqual(value['next_chunk'],2)
        self.assertEqual(value['checkpoint_digest'],TEST_DIGEST)
        with self.assertRaises(ValueError):execution.verify_append_only_resume_ticket(self.scope_client,ticket,'other')
        with self.assertRaises(ValueError):execution.verify_append_only_resume_ticket(self.scope_client,ticket+'x','uo')
        self.scope_client.clock=lambda:NOW+timedelta(seconds=301)
        with self.assertRaises(ValueError):execution.verify_append_only_resume_ticket(self.scope_client,ticket,'uo')

    def test_snapshot_rejects_update_in_append_list_and_update_of_column_a(self):
        bad=self.details|{'appends':[{'operation':'UPDATE','cells':[{'column':'A','formula':True}]}],
            'counts':self.details['counts']|{'append':1}}
        with self.assertRaises(ValueError):execution.store_preview_plan(self.path,'b'*32,'uo',bad,now=NOW)
        bad=self.details|{'updates':[{'operation':'UPDATE','cells':[{'column':'A','formula':True}]}]}
        with self.assertRaises(ValueError):execution.store_preview_plan(self.path,'c'*32,'uo',bad,now=NOW)

    def test_snapshot_tamper_and_scope_reuse_fail_closed(self):
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_preview_plans SET details_json='{}' WHERE request_id=?",(self.request_id,))
        with self.assertRaises(ValueError):execution.load_preview_plan(self.path,self.request_id,'uo',TEST_DIGEST,now=NOW)
        self.assertTrue(execution.claim_run(self.path,'SANDBOX','d'*32,'uo','manual',manual_authorized=True,
            plan_scope='APPEND_ONLY',plan_digest=self.details['append_only_digest'])['claimed'])
        with self.assertRaises(PermissionError):execution.claim_run(self.path,'SANDBOX','d'*32,'uo','manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=TEST_DIGEST)

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
        client=self.client();ticket=execution.preview_ticket(client,'a'*32,'uo',TEST_DIGEST)
        self.assertEqual(execution.verify_ticket(client,ticket,'uo')['digest'],TEST_DIGEST)
        for user,value in [('other',ticket),('uo',ticket+'tamper')]:
            with self.assertRaises(ValueError):execution.verify_ticket(client,value,user)
        with self.assertRaises(ValueError):execution.verify_ticket(self.client('SANDBOX'),ticket,'uo')
        client.clock=lambda:NOW+timedelta(seconds=301)
        with self.assertRaises(ValueError):execution.verify_ticket(client,ticket,'uo')

    def test_network_error_and_redirect_have_no_retry_or_secret_leak(self):
        opener=Mock(side_effect=OSError('TEST_SECRET_DO_NOT_LEAK'))
        client=self.client(opener=opener)
        with self.assertRaisesRegex(execution.ExecutionOutcomeUnknown,'no automatic retry') as error:
            client.invoke('apply','a'*32,'uo',digest=TEST_DIGEST)
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
            client=Mock();client.invoke.side_effect=[{'digest':TEST_DIGEST},{'status':'PARTIAL_SAFE_OPERATIONS_REMAIN','counts':{'update':1}}]
            execution.execute_claimed(self.path,client,run,'uo',trigger=trigger)
            self.assertEqual([call.args[0] for call in client.invoke.call_args_list],['preview','apply'])
            self.assertEqual(execution.claim_run(self.path,'PROD',run,'uo',trigger)['status'],'partial')

    def test_chunked_apply_persists_verified_checkpoints_and_advances_in_order(self):
        run='c'*32
        execution.claim_run(self.path,'SANDBOX',run,'uo','manual')
        calls=[]
        def invoke(action,*args,**kwargs):
            if action=='preview': return {'digest':TEST_DIGEST}
            calls.append(kwargs['chunk_index'])
            if kwargs['chunk_index']==0:
                return {'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,
                    'chunkIndex':0,'nextChunk':1,'more':True,'phase':'append',
                    'planScope':'ALL','checkpointDigest':TEST_DIGEST,
                    'counts':{'append':25,'update':0,'batches':1}}
            if kwargs['chunk_index']==1:
                with closing(sqlite3.connect(self.path)) as con:
                    row=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()
                checkpoint=json.loads(row[1])
                self.assertEqual(row[0],'running')
                self.assertEqual(checkpoint['next_chunk'],1)
                self.assertEqual(checkpoint['verified_totals']['append'],25)
                return {'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,
                    'chunkIndex':1,'nextChunk':2,'more':True,'phase':'append',
                    'planScope':'ALL','checkpointDigest':TEST_DIGEST,
                    'counts':{'append':10,'update':0,'batches':1}}
            with closing(sqlite3.connect(self.path)) as con:
                checkpoint=json.loads(con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()[0])
            self.assertEqual(checkpoint['verified_totals']['append'],35)
            return {'status':'COMPLETE','digest':TEST_DIGEST,'chunkIndex':2,'nextChunk':3,
                'more':False,'phase':'update','counts':{'append':35,'update':2,'batches':3}}
        client=Mock();client.environment='SANDBOX';client.invoke.side_effect=invoke
        result=execution.execute_claimed(self.path,client,run,'uo',manual_authorized=True)
        self.assertEqual(calls,[0,1,2])
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual([call.kwargs.get('chunk_index') for call in client.invoke.call_args_list if call.args[0]=='apply'],[0,1,2])
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()
        self.assertEqual(row[0],'complete')
        self.assertEqual(json.loads(row[1])['counts']['append'],35)

    def test_append_only_stops_at_verified_boundary_and_resumes_same_run_from_next_chunk(self):
        run='1'*32;checkpoint=base64.urlsafe_b64encode(hashlib.sha256(b'checkpoint zero').digest()).decode().rstrip('=')
        next_checkpoint=base64.urlsafe_b64encode(hashlib.sha256(b'checkpoint one').digest()).decode().rstrip('=')
        self.assertTrue(execution.claim_run(self.path,'SANDBOX',run,'uo','manual',manual_authorized=True,
            plan_scope='APPEND_ONLY',plan_digest=TEST_DIGEST,details_digest=TEST_DIGEST)['claimed'])
        calls=[]
        def invoke(action,*args,**kwargs):
            if action=='resume_check':
                return {'status':'RESUME_READY','checkpointDigest':checkpoint,'nextChunk':1,
                    'planDetails':{'appends':[{},{}],'updates':[]},'counts':{'append':2,'update':0}}
            index=kwargs['chunk_index'];calls.append((index,kwargs.get('expected_checkpoint_digest')))
            if index==0:
                return {'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,'chunkIndex':0,'nextChunk':1,
                    'more':True,'phase':'append','planScope':'APPEND_ONLY','checkpointDigest':checkpoint,
                    'counts':{'append':25,'update':0,'batches':1}}
            return {'status':'COMPLETE','digest':TEST_DIGEST,'chunkIndex':1,'nextChunk':2,
                'more':False,'phase':'append','planScope':'APPEND_ONLY','checkpointDigest':next_checkpoint,
                'counts':{'append':50,'update':0,'batches':2}}
        client=Mock(environment='SANDBOX');client.invoke.side_effect=invoke
        first=execution.execute_claimed(self.path,client,run,'uo',digest=TEST_DIGEST,
            manual_authorized=True,plan_scope='APPEND_ONLY',max_append_chunks=1)
        self.assertEqual(first['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        candidate=execution.load_append_only_resume_candidate(self.path,run,'uo')
        self.assertEqual(candidate['next_chunk'],1)
        self.assertEqual(candidate['verified_totals']['append'],25)
        self.assertEqual(execution.claim_run(self.path,'SANDBOX','2'*32,'uo','manual',manual_authorized=True,
            plan_scope='APPEND_ONLY',plan_digest=TEST_DIGEST)['status'],'append_only_resume_required')
        preflight=client.invoke('resume_check',run,'uo',digest=TEST_DIGEST,plan_scope='APPEND_ONLY',
            manual_authorized=True,chunk_index=1,expected_checkpoint_digest=checkpoint)
        self.assertEqual(preflight['status'],'RESUME_READY')
        self.assertTrue(execution.claim_append_only_resume(self.path,candidate)['claimed'])
        self.assertFalse(execution.claim_append_only_resume(self.path,candidate)['claimed'],
            'the same checkpoint cannot be claimed twice')
        resumed=execution.execute_claimed(self.path,client,run,'uo',digest=TEST_DIGEST,manual_authorized=True,
            plan_scope='APPEND_ONLY',start_chunk=candidate['next_chunk'],
            checkpoint_digest=candidate['checkpoint_digest'])
        self.assertEqual(resumed['status'],'COMPLETE')
        self.assertEqual(calls,[(0,None),(1,checkpoint)])
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()
        self.assertEqual(row[0],'complete')
        self.assertEqual(json.loads(row[1])['counts']['update'],0)

    def test_uncertain_resume_chunk_remains_hold_and_cannot_be_resumed_again(self):
        run='3'*32;checkpoint=base64.urlsafe_b64encode(hashlib.sha256(b'checkpoint').digest()).decode().rstrip('=')
        execution.claim_run(self.path,'SANDBOX',run,'uo','manual',manual_authorized=True,
            plan_scope='APPEND_ONLY',plan_digest=TEST_DIGEST,details_digest=TEST_DIGEST)
        client=Mock(environment='SANDBOX')
        client.invoke.side_effect=[{'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,'chunkIndex':0,'nextChunk':1,
            'more':True,'phase':'append','planScope':'APPEND_ONLY','checkpointDigest':checkpoint,
            'counts':{'append':25,'update':0,'batches':1}},execution.ExecutionOutcomeUnknown('simulated timeout')]
        initial=execution.execute_claimed(self.path,client,run,'uo',digest=TEST_DIGEST,manual_authorized=True,
            plan_scope='APPEND_ONLY',max_append_chunks=1)
        self.assertEqual(initial['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        candidate=execution.load_append_only_resume_candidate(self.path,run,'uo')
        self.assertTrue(execution.claim_append_only_resume(self.path,candidate)['claimed'])
        result=execution.execute_claimed(self.path,client,run,'uo',digest=TEST_DIGEST,manual_authorized=True,
            plan_scope='APPEND_ONLY',start_chunk=1,checkpoint_digest=checkpoint)
        self.assertEqual(result['status'],'OUTCOME_UNKNOWN_HOLD_NO_RETRY')
        with self.assertRaises(ValueError):execution.load_append_only_resume_candidate(self.path,run,'uo')
        self.assertEqual(client.invoke.call_count,2)

    def test_lost_chunk_response_holds_run_and_preserves_verified_progress_without_retry(self):
        run='d'*32
        execution.claim_run(self.path,'SANDBOX',run,'uo','manual')
        client=Mock();client.environment='SANDBOX';client.invoke.side_effect=[{'digest':TEST_DIGEST},
            {'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,'chunkIndex':0,'nextChunk':1,
             'more':True,'phase':'append','planScope':'ALL','checkpointDigest':TEST_DIGEST,
             'counts':{'append':25,'update':0,'batches':1}},
            execution.ExecutionOutcomeUnknown('network response unavailable')]
        result=execution.execute_claimed(self.path,client,run,'uo',manual_authorized=True)
        self.assertEqual(result['status'],'OUTCOME_UNKNOWN_HOLD_NO_RETRY')
        self.assertEqual(client.invoke.call_count,3)
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()
        state=json.loads(row[1])
        self.assertEqual(row[0],'outcome_unknown')
        self.assertEqual(state['verified_totals']['append'],25)
        self.assertEqual(state['next_chunk'],1)
        self.assertEqual(state['attempted_chunk'],1)
        self.assertFalse(execution.claim_run(self.path,'SANDBOX','e'*32,'uo','manual')['claimed'])

    def test_guard_change_after_checkpoint_stops_before_next_chunk_and_keeps_progress(self):
        run='f'*32
        execution.claim_run(self.path,'SANDBOX',run,'uo','manual')
        client=Mock();client.environment='SANDBOX';client.invoke.return_value={'status':'APPLY_CHUNK_VERIFIED','digest':TEST_DIGEST,
            'chunkIndex':0,'nextChunk':1,'more':True,'phase':'append',
            'planScope':'ALL','checkpointDigest':TEST_DIGEST,
            'counts':{'append':25,'update':0,'batches':1}}
        guard=Mock(side_effect=[True,True,False])
        result=execution.execute_claimed(self.path,client,run,'uo',digest=TEST_DIGEST,
            guard=guard,manual_authorized=True)
        self.assertEqual(result['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        self.assertEqual(client.invoke.call_count,1)
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(run,)).fetchone()
        state=json.loads(row[1])
        self.assertEqual(row[0],'partial')
        self.assertEqual(state['verified_totals']['append'],25)
        self.assertEqual(state['next_chunk'],1)

    def test_guard_change_blocks_remote_apply(self):
        execution.claim_run(self.path,'PROD','a'*32,'uo','manual')
        client=Mock();guard=Mock(side_effect=[True,False]);client.invoke.return_value={'digest':TEST_DIGEST}
        self.assertEqual(execution.execute_claimed(self.path,client,'a'*32,'uo',guard=guard)['status'],'PRECALL_REJECTED_NO_REMOTE_CALL')
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
            if action=='preview': return {'digest':TEST_DIGEST}
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
