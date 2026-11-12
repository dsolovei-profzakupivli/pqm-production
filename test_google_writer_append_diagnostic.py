"""Read-only SQLite and Execution contract tests for APPEND diagnostics."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import google_writer_execution as writer
import sandbox_runtime as runtime
from test_google_writer_execution import NOW


def digest(text):
    return writer._sha256_b64(text.encode('utf-8'))


class DiagnosticClient:
    environment = 'SANDBOX'

    def __init__(self, *, status='DIAGNOSED', confirmed=25, missing=251, conflict=0, unverified=0,
                 first_chunk=False, conflict_codes=None, conflict_fields=None, manifest_fields=None):
        self.status=status
        self.confirmed=confirmed
        self.missing=missing
        self.conflict=conflict
        self.unverified=unverified
        self.first_chunk=first_chunk
        self.conflict_codes=list(conflict_codes or [])
        self.conflict_fields=dict(conflict_fields or {})
        self.manifest_fields=list(manifest_fields or [])
        self.calls=[]

    def invoke(self, action, request_id, actor, **kwargs):
        self.calls.append((action,request_id,actor,kwargs))
        if kwargs.get('diagnostic_mode')=='audit':
            counts={'planned':kwargs['total_append_count'],'confirmed':self.confirmed,'missing':self.missing,
                'conflict':self.conflict,'unverified':self.unverified,
                'remaining':kwargs['total_append_count']-self.confirmed}
            conflicts=[{'code':code,'fields':[],'observed_digest':digest('observed:'+code)}
                for code in self.conflict_codes]
            return {'status':'AUDITED' if not self.unverified else 'READ_INCOMPLETE',
                'counts':counts,'reason_codes':['TARGET_CONFLICT'] if self.conflict else [],
                'conflicts':conflicts,'read_only':True,'sqlite_writes':0,
                'sheets_writes':0,'properties_writes':0}
        if kwargs.get('diagnostic_mode')=='audit_fields':
            conflicts=[{'code':item[1],'status':'ROW_CHANGED',
                'fields':self.conflict_fields.get(item[1],['value:C'])}
                for item in kwargs['audit_field_targets']]
            return {'status':'AUDIT_DETAILS','conflicts':conflicts,'read_only':True,
                'sqlite_writes':0,'sheets_writes':0,'properties_writes':0}
        counts={'planned':kwargs['total_append_count'],'confirmed':self.confirmed,
            'missing':self.missing,'conflict':self.conflict,'unverified':self.unverified,
            'remaining':kwargs['total_append_count']-self.confirmed}
        reasons=[] if self.first_chunk else ['MANIFEST_BINDING_MISMATCH']
        return {'status':'DIAGNOSED','counts':counts,
            'firstChunkRecoveryEvidence':self.first_chunk,
            'first_chunk_recovery_evidence':self.first_chunk,
            'reason_codes':reasons,'manifest_mismatch_fields':self.manifest_fields,
            'read_only':True}


class GoogleWriterAppendDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='append-diagnostic-')
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'sandbox.sqlite3')
        self.request_id='7'*32
        self.actor='diagnostic-admin'
        self.full_digest=digest('full-plan')
        self.append_digest=digest('append-plan')
        self.source_digest=digest('source-state')
        self.details=self._details(276)
        self.details_digest=writer._preview_details_digest(self.details)
        self.chunk_id='8'*32
        self.chunk_expected={'version':1,'run_id':self.request_id,'plan_id':self.request_id,
            'scope':'APPEND_ONLY','plan_digest':self.append_digest,'source_digest':self.source_digest,
            'chunk_index':0,'rows':self.details['appends'][:25]}
        self.chunk_digest=writer._sha256_b64(writer._canonical_json(self.chunk_expected).encode('utf-8'))
        with closing(sqlite3.connect(self.path)) as con, con:
            writer.migrate(con)
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?, 'SANDBOX','manual',?,1,'2026-11-11T20:00:00Z',
                'outcome_unknown',?)''',(self.request_id,self.actor,json.dumps({
                    'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY','plan_scope':'APPEND_ONLY',
                    'attempted_chunk':0,'outcome_unknown':True})))
            con.execute('''INSERT INTO google_writer_plan_journal(plan_id,request_id,environment,actor,
                plan_digest,append_only_digest,details_digest,source_digest,created_at,details_json)
                VALUES(?,?,'SANDBOX',?,?,?,?,?,1,?)''',(self.request_id,self.request_id,self.actor,
                    self.full_digest,self.append_digest,self.details_digest,self.source_digest,
                    writer._preview_details_raw(self.details)))
            con.execute('''INSERT INTO google_writer_chunk_journal(chunk_id,plan_id,run_id,environment,scope,
                plan_digest,source_digest,chunk_index,chunk_digest,status,expected_json,prepared_at,receipt_json)
                VALUES(?,?,?,'SANDBOX','APPEND_ONLY',?,?,0,?,'prepared',?,'2026-11-11T20:00:00Z','{}')''',
                (self.chunk_id,self.request_id,self.request_id,self.append_digest,self.source_digest,
                 self.chunk_digest,writer._canonical_json(self.chunk_expected)))

    def _details(self,count):
        appends=[]
        row_by_tab={'ФОП':2,'ЮО':2}
        conflict_codes=['32835814','32871061','33134397','33642588','33872747','33897714']
        for index in range(count):
            tab='ФОП' if index%2==0 else 'ЮО'
            code=conflict_codes[(index//2)%len(conflict_codes)] if tab=='ЮО' and index<12 else f'{10000000+index:08d}'
            appends.append({'operation':'APPEND','tab':tab,'row':row_by_tab[tab], 'code':code,
                'cells':[{'column':'A','new_value':f'=IF(B{row_by_tab[tab]}="","",1)','formula':True},
                    {'column':'B','new_value':code,'formula':False}]})
            row_by_tab[tab]+=1
        return {'version':1,'environment':'SANDBOX','plan_digest':self.full_digest,
            'source_digest':self.source_digest,'append_only_digest':self.append_digest,
            'counts':{'append':count,'update':0,'conflict':0,'error':0},
            'appends':appends,'updates':[],'conflicts':[],'errors':[]}

    def test_276_row_audit_confirms_first_25_and_keeps_recovery_blocked(self):
        client=DiagnosticClient()
        before=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        after=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        self.assertEqual(before,after,'read-only diagnostics must not modify SQLite')
        self.assertEqual(result['counts'],{'planned':276,'confirmed':25,'missing':251,
            'conflict':0,'unverified':0,'remaining':251})
        self.assertFalse(result['first_chunk_recovery_evidence'])
        self.assertEqual(result['recovery_status'],'BLOCKED')
        self.assertIn('MANIFEST_BINDING_MISMATCH',result['recovery_reason_codes'])
        self.assertTrue(result['read_only'])
        self.assertEqual((result['sqlite_writes'],result['sheets_writes'],result['properties_writes']),(0,0,0))
        action,request_id,actor,kwargs=client.calls[0]
        self.assertEqual((action,request_id,actor),('diagnose_append_plan',self.request_id,self.actor))
        self.assertEqual(kwargs['diagnostic_mode'],'audit')
        self.assertEqual(len(kwargs['audit_targets']),276)
        self.assertEqual(len(kwargs['audit_targets'][0]),4)
        self.assertEqual(sum(call[3].get('diagnostic_mode')=='audit' for call in client.calls),1)

    def test_conflicts_and_unverified_rows_are_reported_without_recovery_authorization(self):
        client=DiagnosticClient(confirmed=23,missing=250,conflict=2,unverified=1,first_chunk=False)
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['counts']['conflict'],2)
        self.assertEqual(result['counts']['unverified'],1)
        self.assertFalse(result['first_chunk_recovery_evidence'])

    def test_six_legal_entity_conflicts_return_only_field_names_and_manifest_mismatches(self):
        codes=['32835814','32871061','33134397','33642588','33872747','33897714']
        client=DiagnosticClient(confirmed=19,missing=251,conflict=6,unverified=0,
            conflict_codes=codes,conflict_fields={code:['value:C','formula:A'] for code in codes},
            manifest_fields=['manifest.chunkDigest','manifest.rows[3].cellsDigest'])
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['counts'],{'planned':276,'confirmed':19,'missing':251,
            'conflict':6,'unverified':0,'remaining':257})
        self.assertEqual([item['code'] for item in result['conflicts']],codes)
        self.assertTrue(all(item['fields']==['value:C','formula:A'] for item in result['conflicts']))
        self.assertEqual(result['recovery_field_mismatches'],
            ['manifest.chunkDigest','manifest.rows[3].cellsDigest'])
        self.assertFalse(result['first_chunk_recovery_evidence'])
        serialized=writer._canonical_json(result)
        self.assertNotIn('observed_digest',serialized)
        self.assertNotIn('cellsDigestValue',serialized)
        self.assertTrue(all(call[3].get('diagnostic_mode') in {'audit','audit_fields','recovery'}
            for call in client.calls))

    def test_signed_audit_fields_payload_passes_only_the_additive_sandbox_egress_shape(self):
        script_id='1Ht0jL2xQc3hsd6uWKui4uA6o1z2Oe_BAUbZq8HTXcw6C1Kpyi7JxNtmQ'
        spreadsheet=runtime.SANDBOX_EDR_SPREADSHEET_ID
        deployment='TEST_SANDBOX_DEPLOYMENT_0123456789'
        targets=[['ЮО','32835814',7447,digest('observed-row'),
            [['blank',digest(f'field-{i}')] for i in range(15)]]]
        payload={'environment':'SANDBOX','scriptId':script_id,'spreadsheetId':spreadsheet,
            'contract':'pqm-mirror-datetime-v1','action':'diagnose_append_plan','requestId':self.request_id,
            'actor':'diagnostic-admin','trigger':'manual','issuedAt':1_800_000_000,'expiresAt':1_800_000_300,
            'expectedDigest':self.append_digest,'planScope':'APPEND_ONLY','chunkIndex':0,'planId':self.request_id,
            'detailsDigest':self.details_digest,'fullPlanDigest':self.full_digest,'sourceDigest':self.source_digest,
            'totalAppendCount':276,'diagnosticMode':'audit_fields','auditFieldTargets':targets,
            'auditFieldTargetsDigest':digest(writer._canonical_json(targets))}
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        body={'function':'pqmSandboxAppendDiagnostic20261112','devMode':False,
            'parameters':[{'payload':raw,'signature':'s'*43}]}
        request=urllib.request.Request('https://script.googleapis.com/v1/scripts/'+deployment+':run',
            data=json.dumps(body).encode(),headers={'Authorization':'Bearer test'},method='POST')
        with patch.dict(os.environ,{'PQM_SANDBOX':'1','RENDER_SERVICE_ID':'srv-dalfd77f3r2c7392uub0',
                'PQM_SANDBOX_EXECUTION_READY':'1','PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID':deployment,
                'PQM_SANDBOX_EDR_GOOGLE':'1'},clear=True):
            self.assertEqual(runtime.validate_execution_request(request,'SANDBOX',script_id,spreadsheet,deployment),
                'script.googleapis.com')
            payload['auditFieldTargets'][0][4][0][1]='invalid'
            bad_raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            bad_body={'function':'pqmSandboxAppendDiagnostic20261112','devMode':False,
                'parameters':[{'payload':bad_raw,'signature':'s'*43}]}
            bad=urllib.request.Request(request.full_url,data=json.dumps(bad_body).encode(),
                headers={'Authorization':'Bearer test'},method='POST')
            with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
                runtime.validate_execution_request(bad,'SANDBOX',script_id,spreadsheet,deployment)

    def test_execution_client_accepts_only_sanitized_audit_field_and_manifest_receipts(self):
        targets=[['ЮО','32835814',7447,digest('observed'),
            [['blank',digest(f'cell-{i}')] for i in range(15)]]]
        digests={'expected':self.append_digest,'details':self.details_digest,
            'full':self.full_digest,'source':self.source_digest}
        result={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':self.request_id,'status':'AUDIT_DETAILS','diagnosticMode':'audit_fields',
            'planScope':'APPEND_ONLY','digest':digests['expected'],'detailsDigest':digests['details'],
            'fullPlanDigest':digests['full'],'sourceDigest':digests['source'],'planId':self.request_id,
            'auditFieldTargetsDigest':digest(writer._canonical_json(targets)),
            'conflicts':[{'code':'32835814','status':'ROW_CHANGED','fields':['value:C']}],
            'readOnly':True}
        client=writer.ExecutionClient('SANDBOX','TEST_SANDBOX_DEPLOYMENT_0123456789','x'*40,
            lambda env:{'environment':env,'access_token':'test-only','scopes':sorted(writer.PROJECT_SCOPES),
                'expires_at':NOW.timestamp()+3600},configured=True,
            opener=lambda request,timeout:io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode()),
            clock=lambda:NOW)
        kwargs={'trigger':'manual','digest':self.append_digest,'plan_scope':'APPEND_ONLY',
            'manual_authorized':True,'details_digest':self.details_digest,'full_plan_digest':self.full_digest,
            'source_digest':self.source_digest,'plan_id':self.request_id,'total_append_count':276,
            'diagnostic_mode':'audit_fields','audit_field_targets':targets,
            'audit_field_targets_digest':result['auditFieldTargetsDigest']}
        parsed=client.invoke('diagnose_append_plan',self.request_id,self.actor,**kwargs)
        self.assertEqual(parsed['conflicts'],[{'code':'32835814','status':'ROW_CHANGED','fields':['value:C']}])
        result['conflicts'][0]['fields']=['value:Z']
        with self.assertRaises(writer.ExecutionPreflightError):
            client.invoke('diagnose_append_plan',self.request_id,self.actor,**kwargs)

    def test_malformed_run_or_binding_is_blocked_before_apps_script_call(self):
        client=DiagnosticClient()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='failed_safe' WHERE request_id=?",(self.request_id,))
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('RUN_NOT_HELD_ON_FIRST_APPEND',result['reason_codes'])
        self.assertEqual(client.calls,[])

    def test_wrong_environment_or_untrusted_actor_is_blocked(self):
        client=DiagnosticClient();client.environment='PRODUCTION'
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(client.calls,[])

    def test_audit_row_digest_normalizes_google_date_and_datetime_values(self):
        self.assertEqual(writer._append_audit_comparable_value('14.10.2026',7),'2026-10-14')
        self.assertEqual(writer._append_audit_comparable_value('2026-10-14',7),'2026-10-14')
        self.assertEqual(writer._append_audit_comparable_value('2026-11-12T10:30:00+02:00',8),
            int(writer.datetime.fromisoformat('2026-11-12T10:30:00+02:00').timestamp()*1000))

    def test_missing_or_invalid_chunk_does_not_block_fact_audit_but_blocks_recovery(self):
        client=DiagnosticClient(first_chunk=True)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('DELETE FROM google_writer_chunk_journal WHERE run_id=?',(self.request_id,))
        result=writer.diagnose_append_only_plan(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['counts']['confirmed'],25)
        self.assertEqual(result['counts']['missing'],251)
        self.assertFalse(result['first_chunk_recovery_evidence'])
        self.assertEqual(result['recovery_status'],'BLOCKED')
        self.assertIn('RECOVERY_CHUNK_JOURNAL_CARDINALITY',result['recovery_reason_codes'])
        self.assertTrue(any(call[3].get('diagnostic_mode')=='audit' for call in client.calls))
        self.assertFalse(any(call[3].get('diagnostic_mode')=='recovery' for call in client.calls))


if __name__=='__main__':
    unittest.main()
