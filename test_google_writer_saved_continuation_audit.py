"""Read-only saved APPEND continuation audit contract tests."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import ast
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import google_writer_execution as writer


def sha(value):
    return writer._sha256_b64(value.encode('utf-8'))


class SavedContinuationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='saved-cont-audit-')
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'audit.sqlite3')
        self.actor='saved-audit-admin'
        self.source_id=writer.APPEND_CONTINUATION_SOURCE_REQUEST_ID
        self.request_id='c1dc13464f0247c5a727204ebf28f8cc'
        self.source_plan_digest=sha('source-plan-full')
        self.source_append_digest=sha('source-plan-append')
        self.source_digest=sha('source-payload')
        self.current_plan_digest=sha('continuation-full')
        self.current_append_digest=sha('continuation-append')
        self.source_ops=self._operations(276)
        self.updates=[{'operation':'UPDATE','tab':'ФОП','row':7000,'code':'20000001',
            'cells':[{'column':'C','old_value':'old','new_value':'new','formula':False}]},
            {'operation':'UPDATE','tab':'ЮО','row':7001,'code':'20000002',
             'cells':[{'column':'C','old_value':'old','new_value':'new','formula':False}]}]
        self.conflicts=[{'tab':'ФОП','code':'30000001','reason':'routing_mismatch'},
            {'tab':'ЮО','code':'30000002','reason':'routing_mismatch'}]
        self.source_details={'version':1,'environment':'SANDBOX','plan_digest':self.source_plan_digest,
            'append_only_digest':self.source_append_digest,'source_digest':self.source_digest,
            'counts':{'append':276,'update':2,'conflict':2,'error':0},'appends':self.source_ops,
            'updates':self.updates,'conflicts':self.conflicts,'errors':[]}
        self.source_details_digest=writer._preview_details_digest(self.source_details)
        self.exclusions=writer._append_continuation_v2_exclusions(self.source_details)
        self.continuation_ops=self.source_ops[25:]
        self.preserved_rows=[{'tab':item['tab'],'row':item['row'],
            'identity_digest':sha(writer._canonical_json([item['tab'],item['row'],item['code']])),
            'row_digest':sha('preserved-row:'+item['code']),'service_digest':sha('preserved-service:'+item['code'])}
            for item in self.source_ops[:25]]
        self.meta={'version':2,'source_request_id':self.source_id,
            'source_plan_digest':self.source_plan_digest,'source_details_digest':self.source_details_digest,
            'source_append_digest':self.source_append_digest,'source_payload_digest':self.source_digest,
            'sheet_snapshot_digest':sha('old-sheet-snapshot'),
            'operation_digest':writer._append_continuation_operations_digest(self.continuation_ops),
            'confirmed_count':25,'excluded_count':25,'missing_count':251,
            'preserved_rows':self.preserved_rows,'source_excluded_counts':{'update':2,'conflict':2,'error':0},
            'source_exclusions_digest':self.exclusions['digest'],
            'source_update_exclusions_digest':self.exclusions['update_digest'],
            'source_conflict_exclusions_digest':self.exclusions['conflict_digest'],
            'excluded_updates':self.exclusions['update_records'],
            'excluded_conflicts':self.exclusions['conflict_records'],'conflict_rows_unavailable':2}
        self.current_details={'version':1,'environment':'SANDBOX','plan_digest':self.current_plan_digest,
            'append_only_digest':self.current_append_digest,'source_digest':self.source_digest,
            'counts':{'append':251,'update':0,'conflict':0,'error':0},'appends':self.continuation_ops,
            'updates':[],'conflicts':[],'errors':[],'append_continuation':self.meta}
        with closing(sqlite3.connect(self.path)) as con, con:
            writer.migrate(con)
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?, 'SANDBOX','manual',?,1,'2026-11-11T20:00:00Z',
                'closed_unknown',?)''',(self.source_id,self.actor,json.dumps({'plan_scope':'APPEND_ONLY',
                    'attempted_chunk':0,'outcome_unknown':True})))
            con.execute('''INSERT INTO google_writer_plan_journal(plan_id,request_id,environment,actor,
                plan_digest,append_only_digest,details_digest,source_digest,created_at,details_json)
                VALUES(?,?,'SANDBOX',?,?,?,?,?,1,?)''',(self.source_id,self.source_id,self.actor,
                    self.source_plan_digest,self.source_append_digest,self.source_details_digest,
                    self.source_digest,writer._preview_details_raw(self.source_details)))
        writer.store_preview_plan(self.path,self.request_id,self.actor,self.current_details)

    def _operations(self,count):
        rows={'ФОП':2,'ЮО':2};items=[]
        for index in range(count):
            tab='ФОП' if index%2==0 else 'ЮО';row=rows[tab];code=f'{10000000+index:08d}'
            items.append({'operation':'APPEND','tab':tab,'row':row,'code':code,
                'cells':[{'column':'A','new_value':f'=IF(B{row}="","",1)','formula':True},
                         {'column':'B','new_value':code,'formula':False}]})
            rows[tab]+=1
        return items

    def _audit_reply(self, *, conflict_at=None, duplicate=False, unverified_at=None):
        statuses=[];conflicts=[]
        for index,item in enumerate(self.source_ops):
            status='CONFIRMED' if index<25 else 'MISSING'
            if index==conflict_at:status='CONFLICT'
            if index==unverified_at:status='UNVERIFIED'
            statuses.append({'code':item['code'],'status':status})
            if status=='CONFLICT':conflicts.append({'code':item['code'],
                'fields':['duplicate'] if duplicate else ['value:A'],'detail_status':'VERIFIED'})
        counts={key:sum(row['status']==state for row in statuses) for key,state in
            (('confirmed','CONFIRMED'),('missing','MISSING'),('conflict','CONFLICT'),('unverified','UNVERIFIED'))}
        return {'status':'READ_INCOMPLETE' if counts['unverified'] else 'DIAGNOSED',
            'request_id':self.source_id,
            'counts':{'planned':276,**counts},'target_statuses':statuses,
            'continuation_guard_rows':self.preserved_rows,'conflicts':conflicts,
            'recovery_status':'BLOCKED','recovery_reason_codes':['MANIFEST_BINDING_MISMATCH'],
            'manifest_mismatch_fields':['manifest.chunkIndex'],
            'first_chunk_recovery_evidence':False,
            'read_only':True,'sqlite_writes':0,'sheets_writes':0,'properties_writes':0}

    def _run(self, audit):
        before=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        with patch.object(writer,'validate_append_continuation_closed',return_value={'closed':True,
                'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED'}), \
             patch.object(writer,'diagnose_append_only_plan',return_value=audit) as call:
            result=writer.audit_saved_append_continuation(self.path,
                type('Client',(),{'environment':'SANDBOX'})(),self.request_id,self.actor)
        after=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        self.assertEqual(before,after,'the audit must not modify SQLite')
        if call.called:
            self.assertEqual(call.call_args.args[2],self.source_id)
            self.assertEqual(call.call_args.kwargs,{'audit_only':True,'include_target_statuses':True,
                'allow_closed_unknown':True})
        return result

    def test_full_saved_plan_audit_verifies_25_and_251_without_creating_state(self):
        result=self._run(self._audit_reply())
        self.assertEqual(result['status'],'VERIFIED')
        self.assertTrue(all(item['status']=='MATCH' for item in result['checks'].values()))
        self.assertEqual(result['checks']['source_chunks_unresolved']['count'],0)
        self.assertEqual(result['checks']['continuation_chunks_unresolved']['count'],0)
        self.assertEqual(result['checks']['additional_saved_previews']['count'],0)
        self.assertEqual(result['checks']['continuation_preview']['state'],'preview_saved')
        self.assertEqual(result['source'],{'planned':276,'confirmed':25,'missing':251,'conflict':0,'unverified':0})
        self.assertEqual(result['preserved'],{'planned':25,'confirmed':25,'missing':0,'conflict':0,'unverified':0})
        self.assertEqual(result['continuation'],{'planned':251,'present':0,'missing':251,
            'conflict':0,'unverified':0,'duplicate':0})
        self.assertEqual(result['related']['source_run'],'closed_unknown')
        self.assertEqual(result['related']['continuation_runs'],[])
        self.assertEqual(result['related']['continuation_chunks']['count'],0)
        self.assertEqual(result['related']['continuation_verified_receipts'],0)
        self.assertEqual((result['sqlite_writes'],result['sheets_writes'],result['properties_writes']),(0,0,0))
        self.assertFalse(result['preview_created']);self.assertFalse(result['ticket_created']);self.assertFalse(result['writer_started'])
        self.assertEqual(result['request_id'],self.request_id)

    def test_each_saved_audit_blocking_condition_has_a_safe_specific_diagnostic(self):
        values={'plan_matches':True,'preserved_match':True,'source_expected':True,
            'preserved_expected':True,'source_chunks_unresolved':0,
            'continuation_chunks_unresolved':0,'additional_saved_previews':0,
            'preview_state':'preview_saved','linked_runs_unresolved':0,
            'continuation_conflicts':0,'continuation_unverified':0,'competing_attempts':0}
        expected={'plan_matches','preserved_match','source_counts','preserved_counts',
            'source_chunks_unresolved','continuation_chunks_unresolved','additional_saved_previews',
            'continuation_preview','linked_runs_unresolved','competing_attempts',
            'continuation_conflicts','continuation_unverified'}
        baseline=writer._saved_continuation_audit_checks(**values)
        self.assertEqual(set(baseline),expected)
        self.assertTrue(all(check['status']=='MATCH' for check in baseline.values()))
        self.assertFalse(writer._saved_continuation_audit_checks_block(baseline))
        cases={
            'plan_matches':('plan_matches',False),
            'preserved_match':('preserved_match',False),
            'source_chunks_unresolved':('source_chunks_unresolved',1),
            'continuation_chunks_unresolved':('continuation_chunks_unresolved',1),
            'additional_saved_previews':('additional_saved_previews',1),
            'continuation_preview':('preview_state','complete'),
            'source_counts':('source_expected',False),
            'preserved_counts':('preserved_expected',False),
            'linked_runs_unresolved':('linked_runs_unresolved',1),
            'competing_attempts':('competing_attempts',1),
            'continuation_conflicts':('continuation_conflicts',1),
            'continuation_unverified':('continuation_unverified',1)}
        for check_name,(field,value) in cases.items():
            with self.subTest(check=check_name):
                changed=dict(values);changed[field]=value
                result=writer._saved_continuation_audit_checks(**changed)
                self.assertEqual(result[check_name]['status'],'MISMATCH')
                self.assertEqual([key for key,item in result.items() if item['status']=='MISMATCH'],[check_name])
                self.assertTrue(writer._saved_continuation_audit_checks_block(result))

    def test_duplicate_and_conflict_in_saved_targets_are_blocked(self):
        for duplicate,expected_duplicate in ((True,1),(False,0)):
            with self.subTest(duplicate=duplicate):
                result=self._run(self._audit_reply(conflict_at=30,duplicate=duplicate))
                self.assertEqual(result['status'],'BLOCKED')
                self.assertEqual(result['continuation']['missing'],250)
                self.assertEqual(result['continuation']['conflict'],1)
                self.assertEqual(result['continuation']['duplicate'],expected_duplicate)

    def test_incomplete_apps_script_read_is_unavailable_not_verified(self):
        result=self._run(self._audit_reply(unverified_at=40))
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['continuation']['unverified'],1)
        self.assertEqual(result['reason_codes'],['GOOGLE_SHEETS_READ_INCOMPLETE'])

    def test_apps_script_refusal_is_unavailable_and_does_not_change_sqlite(self):
        with patch.object(writer,'validate_append_continuation_closed',return_value={'closed':True}), \
             patch.object(writer,'diagnose_append_only_plan',side_effect=writer.ExecutionOutcomeUnknown('timeout')):
            before=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
            result=writer.audit_saved_append_continuation(self.path,
                type('Client',(),{'environment':'SANDBOX'})(),self.request_id,self.actor)
            after=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        self.assertEqual(before,after)
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['reason_codes'],['APPS_SCRIPT_AUDIT_UNAVAILABLE'])
        self.assertFalse(result['preview_created']);self.assertFalse(result['writer_started'])

    def test_apps_script_response_binding_mismatch_is_unavailable(self):
        reply=self._audit_reply();reply['request_id']='f'*32
        result=self._run(reply)
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['reason_codes'],['READ_ONLY_AUDIT_CONTRACT_UNCONFIRMED'])

    def test_malformed_apps_script_target_identity_is_unavailable(self):
        reply=self._audit_reply();reply['target_statuses'][0]['code']=['not','a','code']
        result=self._run(reply)
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['reason_codes'],['APPS_SCRIPT_AUDIT_BINDING_INVALID'])

    def test_missing_chunk_receipt_blocks_even_when_sheet_audit_is_exact(self):
        expected={'version':1,'plan_id':self.request_id,'run_id':self.request_id,'scope':'APPEND_ONLY',
            'plan_digest':self.current_append_digest,'source_digest':self.source_digest,'chunk_index':0,
            'rows':self.continuation_ops[:25]}
        chunk_digest=writer._sha256_b64(writer._canonical_json(expected).encode('utf-8'))
        chunk_id=hashlib.sha256((self.request_id+'|'+self.request_id+'|APPEND_ONLY|0|'+chunk_digest).encode()).hexdigest()[:32]
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?, 'SANDBOX','manual',?,1,'2026-11-15T00:00:00Z',
                'running',?)''',(self.request_id,self.actor,json.dumps({'plan_scope':'APPEND_ONLY',
                    'plan_digest':self.current_append_digest,'attempted_chunk':0})))
            con.execute('''INSERT INTO google_writer_chunk_journal(chunk_id,plan_id,run_id,environment,scope,
                plan_digest,source_digest,chunk_index,chunk_digest,status,expected_json,prepared_at,verified_at,receipt_json)
                VALUES(?,?,?,'SANDBOX','APPEND_ONLY',?,?,0,?,'verified',?, '2026-11-15T00:00:00Z',
                '2026-11-15T00:01:00Z','{}')''',(chunk_id,self.request_id,self.request_id,
                    self.current_append_digest,self.source_digest,chunk_digest,writer._canonical_json(expected)))
        result=self._run(self._audit_reply())
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['related']['continuation_verified_receipts'],0)
        self.assertEqual(result['continuation']['missing'],251)

    def _insert_unresolved_source_chunk(self, *, journal_index=0, manifest_index=None, status='outcome_unknown', receipt='{}'):
        if manifest_index is None: manifest_index=journal_index
        rows=self.source_ops[journal_index*writer.APPEND_JOURNAL_PAGE_ROWS:
            (journal_index+1)*writer.APPEND_JOURNAL_PAGE_ROWS]
        expected={'version':1,'plan_id':self.source_id,'run_id':self.source_id,'scope':'APPEND_ONLY',
            'plan_digest':self.source_append_digest,'source_digest':self.source_digest,
            'chunk_index':manifest_index,'rows':rows}
        chunk_digest=writer._sha256_b64(writer._canonical_json(expected).encode('utf-8'))
        chunk_id=hashlib.sha256((self.source_id+'|'+self.source_id+'|APPEND_ONLY|'+
            str(journal_index)+'|'+chunk_digest).encode('utf-8')).hexdigest()[:32]
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''INSERT INTO google_writer_chunk_journal(chunk_id,plan_id,run_id,environment,scope,
                plan_digest,source_digest,chunk_index,chunk_digest,status,expected_json,prepared_at,receipt_json)
                VALUES(?,?,?,'SANDBOX','APPEND_ONLY',?,?,?,?,?,?,?,?)''',
                (chunk_id,self.source_id,self.source_id,self.source_append_digest,self.source_digest,
                 journal_index,chunk_digest,status,writer._canonical_json(expected),
                 '2026-11-11T20:01:00Z',receipt))

    def test_unresolved_source_chunk_details_are_read_only_and_bind_to_first_25(self):
        self._insert_unresolved_source_chunk()
        result=self._run(self._audit_reply())
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['checks']['source_chunks_unresolved'],{'status':'MISMATCH','count':1})
        details=result['related']['source_unresolved_chunk_details']
        self.assertEqual(len(details),1)
        chunk=details[0]
        self.assertEqual((chunk['state'],chunk['chunk_index'],chunk['scope'],chunk['phase']),
            ('outcome_unknown',0,'APPEND_ONLY','append'))
        self.assertEqual((chunk['expected_operations'],chunk['plan_operations_matched'],
            chunk['operations_match'],chunk['manifest_binding']), (25,25,'MATCH','MATCH'))
        self.assertEqual(chunk['sheet_status'],'MATCH')
        self.assertEqual(chunk['sheet_counts'],{'confirmed':25,'missing':0,'conflict':0,'unverified':0})
        self.assertEqual(chunk['receipt_state'],'MISSING')
        self.assertEqual(result['related']['source_recovery'],{'status':'BLOCKED',
            'reason_codes':['MANIFEST_BINDING_MISMATCH'],'manifest_mismatch_fields':['manifest.chunkIndex'],
            'first_chunk_recovery_evidence':False})
        self.assertEqual(result['related']['source_run_evidence'],{'scope':'APPEND_ONLY',
            'attempted_chunk':0,'outcome_unknown':True})
        self.assertEqual(result['related']['source_close'],{'status':'VALIDATED','closed':True,
            'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED','receipt_verified':True})
        self.assertEqual((result['sqlite_writes'],result['sheets_writes'],result['properties_writes']),(0,0,0))

    def test_unresolved_source_chunk_reports_manifest_index_and_rows_mismatch_without_values(self):
        self._insert_unresolved_source_chunk(journal_index=0,manifest_index=1)
        result=self._run(self._audit_reply())
        chunk=result['related']['source_unresolved_chunk_details'][0]
        self.assertEqual(chunk['manifest_binding'],'MISMATCH')
        self.assertEqual(chunk['bindings']['manifest_chunk_index'],'MISMATCH')
        self.assertEqual(chunk['bindings']['plan_operations'],'MATCH')
        self.assertEqual(chunk['sheet_status'],'MATCH')
        self.assertEqual(chunk['sheet_counts'],{'confirmed':25,'missing':0,'conflict':0,'unverified':0})
        serialized=json.dumps(result['related'],ensure_ascii=False)
        self.assertNotIn(self.source_ops[25]['code'],serialized)
        self.assertNotIn(self.source_append_digest,serialized)

    def test_unresolved_continuation_run_blocks_without_repeating_any_operation(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?, 'SANDBOX','manual',?,1,'2026-11-15T00:00:00Z',
                'outcome_unknown',?)''',(self.request_id,self.actor,json.dumps({'plan_scope':'APPEND_ONLY',
                    'plan_digest':self.current_append_digest,'attempted_chunk':0,'outcome_unknown':True})))
        result=self._run(self._audit_reply())
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason_codes'],['CONTINUATION_AUDIT_MISMATCH_OR_UNRESOLVED_STATE'])
        self.assertEqual(result['related']['continuation_runs'],[{'status':'outcome_unknown',
            'scope':'APPEND_ONLY','attempted_chunk_present':True}])

    def test_invalid_saved_plan_binding_fails_closed_before_apps_script(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_plan_journal SET source_digest=? WHERE request_id=?",
                (sha('tampered-source'),self.request_id))
        before=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        with patch.object(writer,'validate_append_continuation_closed') as validate:
            result=writer.audit_saved_append_continuation(self.path,
                type('Client',(),{'environment':'SANDBOX'})(),self.request_id,self.actor)
        after=hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        self.assertEqual(before,after)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason_codes'],['CONTINUATION_PLAN_BINDING_MISMATCH'])
        self.assertTrue(all(item['status']=='NOT_CHECKED' for item in result['checks'].values()))
        validate.assert_not_called()

    def test_get_route_is_sandbox_scoped_and_requires_both_permissions(self):
        server_source=(Path(__file__).parent/'server.py').read_text(encoding='utf-8')
        tree=ast.parse(server_source)
        handler=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Handler')
        get_method=next(node for node in handler.body if isinstance(node,ast.FunctionDef) and node.name=='_do_GET')
        source=ast.get_source_segment(server_source,get_method)
        self.assertIn("saved-continuation-audit/([0-9a-f]{32})",source)
        self.assertIn("if not SANDBOX_MODE or google_writer_environment()!='SANDBOX'",source)
        self.assertIn("not permissions.get('admin.manage') or not permissions.get('google.writer.execute')",source)
        self.assertIn('audit_saved_append_continuation(',source)


if __name__=='__main__':
    unittest.main()
