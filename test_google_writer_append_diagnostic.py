"""Read-only SQLite and Execution contract tests for APPEND diagnostics."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import google_writer_execution as writer


def digest(text):
    return writer._sha256_b64(text.encode('utf-8'))


class DiagnosticClient:
    environment = 'SANDBOX'

    def __init__(self, *, status='DIAGNOSED', confirmed=25, missing=251, conflict=0, unverified=0,
                 first_chunk=False):
        self.status=status
        self.confirmed=confirmed
        self.missing=missing
        self.conflict=conflict
        self.unverified=unverified
        self.first_chunk=first_chunk
        self.calls=[]

    def invoke(self, action, request_id, actor, **kwargs):
        self.calls.append((action,request_id,actor,kwargs))
        if kwargs.get('diagnostic_mode')=='audit':
            counts={'planned':kwargs['total_append_count'],'confirmed':self.confirmed,'missing':self.missing,
                'conflict':self.conflict,'unverified':self.unverified,
                'remaining':kwargs['total_append_count']-self.confirmed}
            return {'status':'AUDITED' if not self.unverified else 'READ_INCOMPLETE',
                'counts':counts,'reason_codes':[],'read_only':True,'sqlite_writes':0,
                'sheets_writes':0,'properties_writes':0}
        counts={'planned':kwargs['total_append_count'],'confirmed':self.confirmed,
            'missing':self.missing,'conflict':self.conflict,'unverified':self.unverified,
            'remaining':kwargs['total_append_count']-self.confirmed}
        reasons=[] if self.first_chunk else ['MANIFEST_BINDING_MISMATCH']
        return {'status':'DIAGNOSED','counts':counts,
            'firstChunkRecoveryEvidence':self.first_chunk,
            'first_chunk_recovery_evidence':self.first_chunk,
            'reason_codes':reasons,'read_only':True}


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
        for index in range(count):
            tab='ФОП' if index%2==0 else 'ЮО'
            code=f'{10000000+index:08d}'
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
