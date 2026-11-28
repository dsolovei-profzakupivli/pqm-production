import ast
import copy
import http.client
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixtures import server,sync,reset,supplier,row,snapshot,auth,DATA
import edr_monitoring_projection as projection
import edr_sync_identity as identity
import sandbox_edr_review
from run_local import validate_paths


class CurrentTests(unittest.TestCase):
    def setUp(self):
        self.con=reset();self.addCleanup(self.con.close)
        self.enterContext(patch.object(server,'SANDBOX_MODE',True))

    def plan(self,source):
        return sync.build_preview(self.con,source,sandbox_mode=True)

    def apply(self,source,**kwargs):
        self.con.commit()
        return sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,
            actor='synthetic',synced_at='2026-11-26T12:00:00+02:00',sandbox_mode=True,**kwargs)

    def test_preslitska_no_status_conflict_no_status_write(self):
        supplier(self.con,'2884318089',status='Зареєстровано')
        source=snapshot(row('2884318089',status='Неактуально',checked='2026-09-02T00:00:00+03:00'))
        plan=self.plan(source);p=plan['items'][0]
        self.assertFalse(plan['conflicts']);self.assertNotIn('edr_status',p['write_fields'])
        self.assertEqual(p['current_table_values']['edr_status'],'Неактуально')
        self.assertEqual(p['current_profile']['edr_status'],'Зареєстровано')
        result=self.apply(source);self.assertEqual(result['updated_profiles'],0)
        self.assertEqual(self.con.execute('SELECT edr_status FROM supplier_edr_profiles').fetchone()[0],'Зареєстровано')

    def test_unrelated_note_does_not_overwrite_historical_status(self):
        supplier(self.con,'2884318089')
        source=snapshot(row('2884318089',status='Неактуально',note='Нова примітка'))
        self.assertFalse(self.plan(source)['conflicts']);self.apply(source)
        stored=self.con.execute('SELECT edr_status,edr_notes FROM supplier_edr_profiles').fetchone()
        self.assertEqual(tuple(stored),('Зареєстровано','Нова примітка'))
        event=self.con.execute("SELECT snapshot_json FROM supplier_edr_verification_events WHERE event_type='google_clarity'").fetchone()
        self.assertEqual(json.loads(event[0])['edr_status'],'')
        self.assertEqual(json.loads(event[0])['google_status_observation'],'Неактуально')
        self.con.execute("UPDATE registry_contracts SET status='active'")
        self.assertEqual(projection.build(self.con)['rows'][0]['edr_status'],'Зареєстровано')

    def test_yupiter_accepts_initial_pair_despite_undated_facts(self):
        supplier(self.con,'31587803',active=True,status='Неактуально',checked='',officer='',name='',manager='ВІДОМИЙ КЕРІВНИК')
        source=snapshot(row('31587803',manager='ВІДОМИЙ КЕРІВНИК'))
        plan=self.plan(source);self.assertFalse(plan['conflicts'],plan['conflicts'])
        self.assertEqual(plan['items'][0]['datetime_gate']['reason'],'initial')
        result=self.apply(source);self.assertEqual(result['updated_profiles'],1)
        stored=self.con.execute('SELECT edr_checked_at,edr_officer FROM supplier_edr_profiles').fetchone()
        self.assertEqual(stored[0],'2026-11-16T08:50:30+02:00')
        self.assertEqual(stored[1],'Тестова УО SANDBOX')
        self.assertEqual(self.con.execute('SELECT protocol_decision FROM application_fields').fetchone()[0],'')

    def test_first_pair_missing_empty_profile_and_existing_facts(self):
        for code,profile,status in [('00000001',False,''),('00000002',True,''),('00000003',True,'Неактуально')]:
            with self.subTest(code=code):
                supplier(self.con,code,active=True,profile=profile,status=status,checked='',officer='',name='')
                source=snapshot(row(code));p=self.plan(source)
                self.assertFalse(p['conflicts'],p['conflicts']);self.apply(source)
                self.assertTrue(self.con.execute('SELECT edr_checked_at FROM supplier_edr_profiles WHERE supplier_code=?',(code,)).fetchone()[0])

    def test_empty_unknown_google_status_always_conflicts_and_is_read_only(self):
        supplier(self.con,'00110183',active=True)
        for status in ['', 'Немає інформації','⚪ Немає інформації']:
            with self.subTest(status=status):
                before='\n'.join(self.con.iterdump());source=snapshot(row('00110183',status=status));p=self.plan(source)
                self.assertIn('google_edr_status_required',p['items'][0]['conflicts'])
                self.assertEqual(before,'\n'.join(self.con.iterdump()))
                result=self.apply(source);self.assertEqual(result['skipped_conflicts'],1)
                self.assertEqual(self.con.execute('SELECT edr_status FROM supplier_edr_profiles').fetchone()[0],'Зареєстровано')

    def test_invalid_or_missing_pair_not_accepted(self):
        supplier(self.con,'31587803',active=True,status='Неактуально',checked='',officer='',name='')
        for checked,officer in [('bad-date','УО'),('','УО'),('2026-11-16T08:50:30+02:00',''),('2026-11-16T08:50:30+02:00','Не визначено')]:
            with self.subTest(checked=checked,officer=officer):
                source=snapshot(row('31587803',checked=checked,officer=officer));p=self.plan(source)['items'][0]
                self.assertNotEqual(p['row_state'],'eligible')

    def test_literal_passports_and_zeroes_never_merge(self):
        codes=['00110183','СР 918414','НВ918414','кн015121','000123456','0123456789']
        for code in codes:supplier(self.con,code,active=True,profile=False)
        source=snapshot(*[row(code) for code in codes]);p=self.plan(source)
        self.assertEqual([x['supplier_code'] for x in p['items']],codes)
        self.assertFalse(p['conflicts'],p['conflicts']);self.apply(source)
        self.assertEqual({x[0] for x in self.con.execute('SELECT supplier_code FROM supplier_edr_profiles')},set(codes))
        self.assertFalse(self.con.execute("SELECT 1 FROM supplier_edr_profiles WHERE supplier_code='918414'").fetchone())

    def test_exact_duplicate_is_blocked_but_other_passport_is_independent(self):
        for code in ['СР 918414','НВ918414']:supplier(self.con,code,active=True)
        p=self.plan(snapshot(row('СР 918414'),row('СР 918414'),row('НВ918414')))
        self.assertIn('duplicate_supplier_code',p['items'][0]['conflicts'])
        self.assertIn('duplicate_supplier_code',p['items'][1]['conflicts'])
        self.assertNotIn('duplicate_supplier_code',p['items'][2]['conflicts'])

    def test_code_keeps_outer_and_inner_spaces_and_global_normalizer_unchanged(self):
        code=' СР 001234 '
        source=snapshot(row(code));self.assertEqual(source['rows'][0]['supplier_code'],code)
        self.assertEqual(sync.source_item(source['rows'][0])['supplier_code'],code)
        self.assertEqual(sync.normalize_code(code),'001234')
        supplier(self.con,code,active=True)
        p=self.plan(source)
        self.assertTrue(p['items'][0]['matched']);self.assertFalse(p['conflicts'])

    def test_missing_literal_code_is_row_conflict_not_projection_error(self):
        supplier(self.con,'00110183',active=True)
        for code in ('','   '):
            p=self.plan(snapshot(row(code),row('00110183')))
            self.assertIn('missing_supplier_code',p['items'][0]['conflicts'])
            self.assertEqual(p['summary']['ready_to_apply'],1)

    def test_supported_native_schema_requires_registry_summary_without_repair(self):
        import sqlite3,hashlib
        from integration.safe_startup import require_current_schema
        require_current_schema(server.DB_PATH,Path(__file__).resolve().parents[2])
        path=Path(DATA.name)/'unsupported.sqlite3'
        target=sqlite3.connect(path)
        try:
            self.con.backup(target);target.execute('DROP TABLE supplier_registry_summary');target.commit()
        finally:target.close()
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RuntimeError,'migration'):
            require_current_schema(path,Path(__file__).resolve().parents[2])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_shared_table_projection_exactly_matches_baseline_for_numeric_ids(self):
        for code,active in [('00110183',True),('2884318089',False)]:supplier(self.con,code,active=active)
        self.con.commit()
        text=(Path(__file__).parent/'reference_server.txt').read_text(encoding='utf-8')
        fn=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='_edr_monitoring_rows')
        ns={**vars(server),'EDR_MONITORING_CACHE':{'fingerprint':None,'rows':[]}}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'reference-projection','exec'),ns)
        expected=ns['_edr_monitoring_rows']();server.EDR_MONITORING_CACHE['fingerprint']=None
        actual=server._edr_monitoring_rows()
        self.assertEqual(sorted([{k:v for k,v in r.items() if k!='verification_datetime_precision'} for r in actual],key=lambda r:r['supplier_code']),sorted(expected,key=lambda r:r['supplier_code']))

    def test_preview_values_equal_table_and_fallback_application_manager(self):
        supplier(self.con,'00110183',active=True,manager='')
        self.con.execute("UPDATE application_fields SET manager_name='КЕРІВНИК ІЗ ЗАЯВКИ'")
        source=snapshot(row('00110183',manager='КЕРІВНИК ІЗ ЗАЯВКИ'))
        p=self.plan(source)['items'][0];table=projection.build(self.con)['rows'][0]
        for field,key in projection.FIELD_MAP.items():self.assertEqual(p['current_table_values'][field],table.get(key,''),field)
        self.assertNotIn('manager_name',p['write_fields'])
        self.assertTrue(p['manager_restoration_allowed'])
        self.apply(source,reestablish_manager=identity.callback(server.reestablish_current_supplier_manager))
        self.assertEqual(self.con.execute('SELECT manager_name FROM supplier_managers WHERE is_current=1').fetchone()[0],'КЕРІВНИК ІЗ ЗАЯВКИ')
        fresh=self.plan(source)['items'][0]
        self.assertFalse(fresh['manager_restoration_allowed'])

    def test_table_cache_invalidates_after_committed_profile_change(self):
        supplier(self.con,'00110183',active=True);self.con.commit()
        server.EDR_MONITORING_CACHE['fingerprint']=None
        first=server._edr_monitoring_rows();self.assertEqual(first[0]['google_note'],'')
        self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='Збережено після кешування'");self.con.commit()
        second=server._edr_monitoring_rows()
        self.assertEqual(second[0]['google_note'],'Збережено після кешування')

    def test_deterministic_digits_stays_constant_inside_literal_callback(self):
        def cleanup():
            self.con.rollback();self.con.execute('DROP TABLE IF EXISTS literal_probe');self.con.commit()
        self.addCleanup(cleanup)
        self.con.execute('CREATE TABLE literal_probe(code TEXT)')
        self.con.executemany('INSERT INTO literal_probe VALUES(?)',[('СР 001234',),('НВ001234',)])
        self.con.execute('CREATE INDEX literal_probe_digits ON literal_probe(DIGITS(code))')
        before=self.con.execute("SELECT DIGITS('СР 001234')").fetchone()[0]
        def work(con):
            self.assertEqual(self.con.execute("SELECT DIGITS('СР 001234')").fetchone()[0],before)
            self.assertEqual(con.execute('SELECT code FROM literal_probe WHERE DIGITS(code)=?',('СР 001234',)).fetchall()[0][0],'СР 001234')
            self.assertEqual(con.execute("SELECT 'DIGITS(code)' AS literal").fetchone()[0],'DIGITS(code)')
        identity.callback(work)(self.con)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM literal_probe WHERE DIGITS(code)=?',('001234',)).fetchone()[0],2)

    def test_skipped_pair_difference_is_visible_without_new_event(self):
        supplier(self.con,'00110183',active=True)
        source=snapshot(row('00110183',checked='2026-08-01T12:00:00+03:00',officer='ІНША УО'))
        p=self.plan(source);plan=p['items'][0]
        self.assertFalse(plan['verification_event_change'])
        pair=next(d for d in plan['field_decisions'] if d['field']=='verification_pair')
        self.assertEqual(pair['verdict'],'skipped');self.assertEqual(pair['planned'],pair['current'])
        self.assertNotIn('edr_checked_at',plan['write_fields'])

    def test_literal_callbacks_cover_manager_and_nazk_chain(self):
        import sandbox_runtime
        self.enterContext(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
        self.enterContext(patch.dict(os.environ,{**sandbox_runtime.POLICY,'PQM_SANDBOX_LOCAL_FIXTURE':'1',
            'RENDER_SERVICE_ID':'','RENDER_SERVICE_NAME':''}))
        for code in ('СР 918414','НВ918414'):
            supplier(self.con,code,active=True,manager='СТАРИЙ КЕРІВНИК')
            self.con.execute("""INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,
                is_current,source,created_at,updated_at) VALUES(?,'СТАРИЙ КЕРІВНИК',?,1,'ЄДР','2026-09-01','2026-09-01')""",
                (code,server.normalize_manager_name('СТАРИЙ КЕРІВНИК')))
        source=snapshot(row('СР 918414',manager='НОВИЙ КЕРІВНИК'))
        result=self.apply(source,sync_manager=identity.callback(server.sync_current_supplier_manager),
            refresh_manager_controls=identity.callback(server.refresh_current_submission_nazk_controls),
            reconcile_manager_nazk=identity.callback(server.make_edr_apply_nazk_reconciler()))
        self.assertEqual(result['manager_identity_changes'],1)
        self.assertEqual(result['nazk_manager_reconciliations'],1)
        rows=dict(self.con.execute('SELECT supplier_code,manager_name FROM supplier_managers WHERE is_current=1'))
        self.assertEqual(rows,{'СР 918414':'НОВИЙ КЕРІВНИК','НВ918414':'СТАРИЙ КЕРІВНИК'})
        self.assertFalse(self.con.execute("SELECT 1 FROM submission_nazk_controls WHERE supplier_code='НВ918414'").fetchone())

    def test_edr_apply_preserves_needs_review_materialization_without_registry_summary(self):
        """The optimized callback must match the ordinary path when summary rows are absent."""
        import sandbox_runtime
        self.enterContext(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
        self.enterContext(patch.dict(os.environ,{**sandbox_runtime.POLICY,'PQM_SANDBOX_LOCAL_FIXTURE':'1',
            'RENDER_SERVICE_ID':'','RENDER_SERVICE_NAME':''}))
        old='СТАРИЙ КЕРІВНИК';new='НОВИЙ КЕРІВНИК'
        ordinary='12345678';optimized='87654321';empty='11223344'
        for code,with_check in ((ordinary,True),(optimized,True),(empty,False)):
            supplier(self.con,code,active=True,manager=old)
            self.con.execute("""INSERT INTO supplier_managers
                (supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
                VALUES(?,?,?,1,'ЄДР','2026-09-01','2026-09-01')""",
                (code,old,server.normalize_manager_name(old)))
            self.con.execute('DELETE FROM supplier_registry_summary WHERE supplier_code=?',(code,))
            if with_check:
                self.con.execute("""INSERT INTO supplier_nazk_checks
                    (supplier_code,manager_id,manager_name,workflow_status,result,started_at,comment,is_legacy,
                     created_at,created_by,updated_at,updated_by)
                    VALUES (?,NULL,?,'needs_review',NULL,'2026-11-20T10:00:00+02:00','',0,
                            '2026-11-20T10:00:00+02:00','fixture','2026-11-20T10:00:00+02:00','fixture')""",
                    (code,new))
        source=snapshot(*(row(code,manager=new) for code in (ordinary,optimized,empty)))
        optimized_callback=server.make_edr_apply_nazk_reconciler()
        def compare_paths(con,code):
            if code==ordinary:
                return server.reconcile_supplier_nazk_after_edr_manager_change(con,code)
            return optimized_callback(con,code)
        functions={k:getattr(server,v) for k,v in {
            'sync_manager':'sync_current_supplier_manager',
            'enrich_manager':'enrich_current_supplier_manager',
            'establish_manager':'establish_current_supplier_manager',
            'reestablish_manager':'reestablish_current_supplier_manager',
            'refresh_manager_controls':'refresh_current_submission_nazk_controls'}.items()}
        functions['reconcile_manager_nazk']=compare_paths
        result=self.apply(source,**identity.callbacks(self.con,functions))
        self.assertEqual(result['manager_identity_changes'],3)
        self.assertEqual(result['nazk_manager_reconciliations'],3)
        for code in (ordinary,optimized,empty):
            with self.subTest(supplier=code):
                managers=[tuple(r) for r in self.con.execute(
                    'SELECT manager_name,is_current,valid_to IS NOT NULL FROM supplier_managers WHERE supplier_code=? ORDER BY id',(code,))]
                self.assertEqual(managers,[(old,0,True),(new,1,False)])
                checks=[tuple(r) for r in self.con.execute(
                    'SELECT manager_name,workflow_status,result FROM supplier_nazk_checks WHERE supplier_code=?',(code,))]
                self.assertEqual(checks,([(new,'needs_review',None)] if code!=empty else []))
                tasks=[tuple(r) for r in self.con.execute(
                    "SELECT task_type,status FROM operational_tasks WHERE supplier_code=? AND task_type='nazk_check'",(code,))]
                self.assertEqual(tasks,([('nazk_check','in_progress')] if code!=empty else []))
                self.assertEqual(self.con.execute(
                    'SELECT COUNT(*) FROM supplier_edr_verification_events WHERE supplier_code=?',(code,)).fetchone()[0],1)
                self.assertEqual(self.con.execute(
                    'SELECT COUNT(*) FROM supplier_google_receipts WHERE supplier_code=?',(code,)).fetchone()[0],1)
        def semantic_result(code):
            profile=tuple(self.con.execute("""SELECT full_name,short_name,manager_name,edr_status,
                edr_checked_at,edr_officer,edr_notes,termination_record_date,termination_record_number
                FROM supplier_edr_profiles WHERE supplier_code=?""",(code,)).fetchone())
            managers=[tuple(r) for r in self.con.execute("""SELECT manager_name,normalized_name,valid_from,
                valid_to,is_current,source FROM supplier_managers WHERE supplier_code=? ORDER BY id""",(code,))]
            checks=[tuple(r) for r in self.con.execute("""SELECT manager_name,workflow_status,result,started_at,
                completed_at,evidence_date,covered_nazk_date,comment,is_legacy FROM supplier_nazk_checks
                WHERE supplier_code=? ORDER BY id""",(code,))]
            tasks=[]
            for task in self.con.execute("""SELECT task_type,status,priority,resolution_code,source_context,
                document_context FROM operational_tasks WHERE supplier_code=? AND task_type='nazk_check'""",(code,)):
                source=json.loads(task['source_context'] or '{}');document=json.loads(task['document_context'] or '{}')
                source.pop('detected_at',None);source.pop('active_application_ids',None)
                if 'nazk_check_id' in source:source['nazk_check_id']='<check>'
                if isinstance(document.get('nazk'),dict) and 'check_id' in document['nazk']:
                    document['nazk']['check_id']='<check>'
                tasks.append((task['task_type'],task['status'],task['priority'],task['resolution_code'],
                    json.dumps(source,ensure_ascii=False,sort_keys=True).replace(code,'<supplier>'),
                    json.dumps(document,ensure_ascii=False,sort_keys=True).replace(code,'<supplier>')))
            events=[tuple(r) for r in self.con.execute("""SELECT event_type,occurred_at,officer,source,
                source_submission_id,source_sheet,changed_fields,snapshot_json
                FROM supplier_edr_verification_events WHERE supplier_code=? ORDER BY id""",(code,))]
            normalized_events=[]
            for event in events:
                snapshot_json=json.loads(event[-1] or '{}')
                snapshot_json.pop('source_row',None)
                snapshot_json.pop('source_row_index',None)
                normalized_events.append(tuple(str(value).replace(code,'<supplier>') for value in event[:-1])+
                    (json.dumps(snapshot_json,ensure_ascii=False,sort_keys=True).replace(code,'<supplier>'),))
            events=normalized_events
            receipts=[tuple(r) for r in self.con.execute("""SELECT received_at,actor,source_sheet,source_fingerprint
                FROM supplier_google_receipts WHERE supplier_code=?""",(code,))]
            return {'profile':profile,'managers':managers,'checks':checks,'tasks':tasks,
                    'verification_events':events,'receipts':receipts}
        # The two populated suppliers differ only by their synthetic code and row index.
        # Exclude random row IDs and technical detection time; compare persisted business content.
        self.assertEqual(semantic_result(ordinary),semantic_result(optimized))

    def test_literal_nazk_positive_matches_preserve_spaces_and_other_passport(self):
        import nazk_workflow, operational_tasks, sandbox_runtime
        self.enterContext(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
        self.enterContext(patch.dict(os.environ,{**sandbox_runtime.POLICY,'PQM_SANDBOX_LOCAL_FIXTURE':'1',
            'RENDER_SERVICE_ID':'','RENDER_SERVICE_NAME':''}))
        import tempfile,sqlite3
        original=self.con;original.commit()
        temp=tempfile.TemporaryDirectory(prefix='positive-passports-',dir=DATA.name)
        path=Path(temp.name)/'pqm_sandbox.sqlite3'
        copy=sqlite3.connect(path)
        try:original.backup(copy)
        finally:copy.close()
        self.enterContext(patch.object(server,'DB_PATH',path))
        self.enterContext(patch.dict(os.environ,{'PQM_DB_PATH':str(path),'PQM_DATA_DIR':temp.name}))
        self.con=server.db()
        try:
            old='СТАРЕНКО ПЕТРО ІВАНОВИЧ';new='ТЕСТЕНКО ІВАН ІВАНОВИЧ'
            codes=(' СР 918414 ','НВ918414')
            for code in codes:
                supplier(self.con,code,active=True,manager=old)
                self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES(?,'ПРИКЛАД',1,'fixture')",(code,))
                self.con.execute("INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at) VALUES(?,?,?,1,'ЄДР','2026-09-01','2026-09-01')",(code,old,server.normalize_manager_name(old)))
            for key,name in (('old',old),('new',new)):
                self.con.execute("INSERT INTO nazk_registry(source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url,raw_json) VALUES(?,?,'synthetic offense','case','2025-01-01','2025-02-01','https://example.test/nazk','{}')",(key,name))
            state=identity.callback(nazk_workflow.reconcile_active_supplier_nazk)(self.con,apply=True,supplier_codes=list(codes))
            self.assertEqual(state['potential_needs_review'],2)
            tasks=identity.callback(operational_tasks.materialize_nazk_tasks)(self.con,'fixture',supplier_codes=list(codes))
            self.assertEqual(tasks['created'],2)
            previous_task=self.con.execute('SELECT id FROM operational_tasks WHERE supplier_code=?',(codes[0],)).fetchone()[0]
            other=[tuple(r) for r in self.con.execute('SELECT id,status,task_key FROM operational_tasks WHERE supplier_code=?',(codes[1],))]
            functions={k:getattr(server,v) for k,v in {'sync_manager':'sync_current_supplier_manager',
                'enrich_manager':'enrich_current_supplier_manager','establish_manager':'establish_current_supplier_manager',
                'reestablish_manager':'reestablish_current_supplier_manager','refresh_manager_controls':'refresh_current_submission_nazk_controls',
                'reconcile_manager_nazk':'make_edr_apply_nazk_reconciler'}.items()}
            functions['reconcile_manager_nazk']=server.make_edr_apply_nazk_reconciler()
            source=snapshot(row(codes[0],manager=new))
            self.con.commit();before='\n'.join(self.con.iterdump())
            self.con.execute('BEGIN IMMEDIATE')
            result=sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,actor='fixture',
                synced_at='2026-11-26T12:00:00+02:00',sandbox_mode=True,**identity.callbacks(self.con,functions))
            self.assertEqual(result['nazk_manager_reconciliations'],1)
            current=dict(self.con.execute('SELECT supplier_code,manager_name FROM supplier_managers WHERE is_current=1'))
            self.assertEqual(current,{codes[0]:new,codes[1]:old})
            self.assertEqual(other,[tuple(r) for r in self.con.execute('SELECT id,status,task_key FROM operational_tasks WHERE supplier_code=?',(codes[1],))])
            self.assertCountEqual([r[0] for r in self.con.execute('SELECT status FROM operational_tasks WHERE supplier_code=?',(codes[0],))],['cancelled','in_progress'])
            self.assertEqual(self.con.execute('SELECT status,resolution_code FROM operational_tasks WHERE id=?',(previous_task,)).fetchone()[:],('cancelled','manager_changed'))
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM supplier_nazk_checks WHERE supplier_code=?',(codes[0],)).fetchone()[0],2)
            self.assertFalse(self.con.execute("SELECT 1 FROM supplier_managers WHERE supplier_code IN ('918414','СР 918414')").fetchone())
            self.assertTrue(self.con.in_transaction,'Real callbacks must not commit the parent Apply transaction')
            self.con.rollback();self.assertEqual(before,'\n'.join(self.con.iterdump()))
        finally:
            self.con.close();self.con=original;temp.cleanup()

    def test_callback_script_preserves_parent_transaction_and_sql_semantics(self):
        self.con.commit();before='\n'.join(self.con.iterdump())
        self.con.execute('BEGIN IMMEDIATE')
        proxy=identity.Connection(self.con)
        proxy.executescript("""CREATE TABLE v311_script_probe(value TEXT);
          CREATE TRIGGER v311_script_trigger AFTER INSERT ON v311_script_probe
          WHEN new.value='first;quoted' BEGIN
            INSERT INTO v311_script_probe VALUES('trigger;value');
          END;
          -- A comment with a ; does not terminate a statement.
          INSERT INTO v311_script_probe VALUES('first;quoted');
          INSERT INTO v311_script_probe VALUES('second');""")
        self.assertTrue(self.con.in_transaction)
        self.assertEqual([r[0] for r in proxy.execute('SELECT value FROM v311_script_probe')],
            ['first;quoted','trigger;value','second'])
        with self.assertRaises(Exception):proxy.executescript("INSERT INTO v311_script_probe VALUES('third');INVALID SQL;")
        self.assertTrue(self.con.in_transaction)
        self.con.rollback();self.assertEqual(before,'\n'.join(self.con.iterdump()))

    def test_projection_reuses_prefetched_verification_data_exactly(self):
        for code in ('00110183','СР 918414'):supplier(self.con,code,active=True,checked='2026-09-02')
        codes={'00110183','СР 918414'}
        expected=sync.current_verification_projections(self.con,codes)
        context=projection.build(self.con,codes,sync_only=True)
        self.assertEqual(context['verifications'],expected)

    def test_google_to_pqm_excludes_a_f_h_from_comparison_plan_and_digest(self):
        supplier(self.con,'00110183',active=True)
        base=snapshot(row('00110183'))
        altered=snapshot(row('00110183'))
        # A freshness marker, F Prozorro status, and H last-application date are
        # PQM-owned / outbound-only and must not enter the inbound EDR plan.
        for source, values in ((base,['marker-one','Active','2026-01-01']),
                               (altered,['marker-two','Inactive','2030-12-31'])):
            raw=source['rows'][0]
            raw['Маркер актуальності'],raw['Статус (Prozorro)'],raw['Дата останньої заявки']=values
            source['source_fingerprint']='fixture-fingerprint-'+values[0]
        base_plan=self.plan(base);altered_plan=self.plan(altered)
        base_item,altered_item=base_plan['items'][0],altered_plan['items'][0]
        self.assertEqual(base_item['incoming'],altered_item['incoming'])
        self.assertEqual(base_item['current_table_values'],altered_item['current_table_values'])
        self.assertEqual(base_item['field_decisions'],altered_item['field_decisions'])
        self.assertEqual(base_item['write_fields'],altered_item['write_fields'])
        self.assertEqual(sync.preview_state_digest(base_plan),sync.preview_state_digest(altered_plan))
        for item in (base_item,altered_item):
            serialized=json.dumps(item,ensure_ascii=False)
            for excluded in ('Маркер актуальності','Статус (Prozorro)','Дата останньої заявки',
                             'freshness','prozorro_status','latest_application_date'):
                self.assertNotIn(excluded,serialized)

    def test_direction_matrix_is_part_of_additive_acceptance_contract(self):
        contract=json.loads((Path(__file__).parent/'contract.json').read_text(encoding='utf-8'))
        self.assertEqual(set(contract['inbound_excluded_columns']),{'A','F','H'})
        self.assertIn('source fingerprint',contract['acceptance_criteria'][1])
        self.assertIn('PQM-to-Google behavior is unchanged',contract['acceptance_criteria'])
        matrix=(Path(__file__).parent/'FIELD_MATRIX.md').read_text(encoding='utf-8')
        plan=(Path(__file__).parent/'IMPLEMENTATION_PLAN.md').read_text(encoding='utf-8')
        for col in ('A','F','H'):
            self.assertIn(f'| {col} |',matrix)
        self.assertIn('one request-local `EDRManagerReconcileContext`',plan)
        self.assertIn('Each shared full read',plan)

    def test_edr_manager_apply_batches_shared_nazk_reads_for_1_4_50_100_changes(self):
        import re
        import time
        registry_size=10_000
        self.con.executemany("""INSERT INTO nazk_registry
            (source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url,raw_json)
            VALUES(?,?,'fixture offense','case','2025-01-01','2025-02-01','https://example.test/fixture','{}')""",
            [(f'bulk-{i:05d}',f'НЕЗВІРЕНИЙ КЕРІВНИК {i:05d}') for i in range(registry_size-1)] +
            [('bulk-match','НОВИЙ КЕРІВНИК З РЕЄСТРУ')])
        results=[]
        expected_created=0
        checks_before=self.con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0]
        tasks_before=self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='nazk_check' AND status NOT IN ('completed','cancelled')").fetchone()[0]
        generated_codes=[]
        def cleanup_fixture():
            if generated_codes:
                marks=','.join('?' for _ in generated_codes)
                check_ids=[r[0] for r in self.con.execute(
                    f"SELECT id FROM supplier_nazk_checks WHERE supplier_code IN ({marks})",generated_codes)]
                task_ids=[r[0] for r in self.con.execute(
                    f"SELECT id FROM operational_tasks WHERE supplier_code IN ({marks})",generated_codes)]
                if task_ids:
                    task_marks=','.join('?' for _ in task_ids)
                    self.con.execute(f"DELETE FROM operational_task_events WHERE task_id IN ({task_marks})",task_ids)
                    self.con.execute(f"DELETE FROM operational_tasks WHERE id IN ({task_marks})",task_ids)
                if check_ids:
                    check_marks=','.join('?' for _ in check_ids)
                    for table in ('supplier_nazk_check_documents','supplier_nazk_check_matches',
                                  'supplier_nazk_check_events','supplier_nazk_check_channels',
                                  'supplier_nazk_check_evidence'):
                        self.con.execute(f"DELETE FROM {table} WHERE check_id IN ({check_marks})",check_ids)
                    self.con.execute(f"DELETE FROM supplier_nazk_checks WHERE id IN ({check_marks})",check_ids)
                for table in ('submission_nazk_controls','supplier_edr_verification_events','supplier_google_receipts',
                              'supplier_edr_profiles','supplier_managers','supplier_registry_summary','registry_contracts'):
                    self.con.execute(f"DELETE FROM {table} WHERE supplier_code IN ({marks})",generated_codes)
                for table in ('application_fields','qualifications','submissions'):
                    if table=='application_fields':
                        self.con.execute(f"DELETE FROM {table} WHERE submission_id IN ({marks})",['s-'+c for c in generated_codes])
                    elif table=='qualifications':
                        self.con.execute(f"DELETE FROM {table} WHERE id IN ({marks})",['q-'+c for c in generated_codes])
                    else:
                        self.con.execute(f"DELETE FROM {table} WHERE id IN ({marks})",['s-'+c for c in generated_codes])
                self.con.execute(f"DELETE FROM frameworks WHERE id IN ({marks})",['f-'+c for c in generated_codes])
            self.con.execute("DELETE FROM nazk_registry WHERE source_id LIKE 'bulk-%'")
            self.con.commit()
        self.addCleanup(cleanup_fixture)
        for amount in (1,4,50,100):
            expected_created+=amount
            codes=[str(98000000+amount*1000+i).zfill(8) for i in range(amount)]
            generated_codes.extend(codes)
            for code in codes:
                supplier(self.con,code,active=True,manager='СТАРИЙ КЕРІВНИК')
                self.con.execute("""INSERT INTO supplier_registry_summary
                    (supplier_code,supplier_name,qualifications_count,active_count,frameworks_count,refreshed_at)
                    VALUES(?,'СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК',1,1,1,'fixture')""",(code,))
                self.con.execute("""INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,
                    is_current,source,created_at,updated_at) VALUES(?,?,?,1,'ЄДР','2026-09-01','2026-09-01')""",
                    (code,'СТАРИЙ КЕРІВНИК',server.normalize_manager_name('СТАРИЙ КЕРІВНИК')))
            source=snapshot(*[row(code,manager='НОВИЙ КЕРІВНИК З РЕЄСТРУ') for code in codes])
            trace=[]
            self.con.commit();self.con.set_trace_callback(trace.append);started=time.perf_counter()
            self.con.execute('BEGIN IMMEDIATE')
            functions={k:getattr(server,v) for k,v in {
                'sync_manager':'sync_current_supplier_manager',
                'enrich_manager':'enrich_current_supplier_manager',
                'establish_manager':'establish_current_supplier_manager',
                'reestablish_manager':'reestablish_current_supplier_manager',
                'refresh_manager_controls':'refresh_current_submission_nazk_controls',
                'reconcile_manager_nazk':'make_edr_apply_nazk_reconciler'}.items()}
            functions['reconcile_manager_nazk']=server.make_edr_apply_nazk_reconciler()
            result=sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,actor='sql-trace-fixture',
                synced_at='2026-11-26T12:00:00+02:00',sandbox_mode=True,**identity.callbacks(self.con,functions))
            self.con.commit();elapsed=time.perf_counter()-started;self.con.set_trace_callback(None)
            self.assertEqual(result['manager_identity_changes'],amount)
            self.assertEqual(result['nazk_manager_reconciliations'],amount)
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0],checks_before+expected_created)
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='nazk_check' AND status NOT IN ('completed','cancelled')").fetchone()[0],tasks_before+expected_created)
            normalized=[' '.join(line.split()).upper() for line in trace]
            counts={
                'active_application_map':sum('FROM REGISTRY_CONTRACTS RC' in q and 'SELECT DISTINCT EDR_LITERAL(RC.SUPPLIER_CODE)' in q for q in normalized),
                'full_nazk_registry':sum('FROM NAZK_REGISTRY WHERE COALESCE(FULL_NAME' in q for q in normalized),
                'active_supplier_counts':sum('FROM SUPPLIER_REGISTRY_SUMMARY WHERE ACTIVE_COUNT>0' in q and 'SELECT SUPPLIER_CODE,ACTIVE_COUNT' in q for q in normalized),
                'active_nazk_tasks':sum('FROM OPERATIONAL_TASKS T LEFT JOIN SUPPLIER_NAZK_CHECKS' in q and "T.STATUS NOT IN ('COMPLETED','CANCELLED')" in q and 'AND T.SUPPLIER_CODE=' not in q for q in normalized),
                'targeted_task_refreshes':sum('FROM OPERATIONAL_TASKS T LEFT JOIN SUPPLIER_NAZK_CHECKS' in q and 'AND T.SUPPLIER_CODE=' in q for q in normalized),
            }
            self.assertEqual(counts,{'active_application_map':1,'full_nazk_registry':1,
                'active_supplier_counts':1,'active_nazk_tasks':1,'targeted_task_refreshes':amount},counts)
            results.append({'changes':amount,'registry_rows':registry_size,'seconds':round(elapsed,3),
                'selects':sum(q.lstrip().upper().startswith(('SELECT','WITH','PRAGMA')) for q in trace),
                'full_shared_reads':counts})
        self.sql_trace_results=results
        print('V31_1_SQL_TRACE='+json.dumps(results,ensure_ascii=False,sort_keys=True))

    def test_card_retains_day_precision_after_technical_timestamp_projection(self):
        supplier(self.con,'00110183',active=True,checked='2026-09-02');self.con.commit()
        data=server.supplier_profile('00110183')
        self.assertEqual(data['edr_profile']['verification_datetime_precision'],'day')
        self.assertEqual(projection.build(self.con)['rows'][0]['verification_datetime_precision'],'day')

    def test_legacy_midnight_without_time_evidence_is_not_presented_as_confirmed_time(self):
        from openpyxl import load_workbook
        supplier(self.con,'00110183',active=True,checked='2026-09-02T00:00:00+03:00');self.con.commit()
        self.assertEqual(projection.build(self.con)['rows'][0]['verification_datetime_precision'],'day')
        self.assertEqual(server.supplier_profile('00110183')['edr_profile']['verification_datetime_precision'],'day')
        preview=self.plan(snapshot(row('00110183',status='Немає інформації')))
        self.assertEqual(preview['items'][0]['current_verification_precision'],'day')
        values=list(load_workbook(io.BytesIO(server.supplier_edr_conflict_xlsx(preview))).active.values)
        self.assertEqual(values[1][7],'02.09.2026')
        self.con.execute("""INSERT INTO supplier_edr_verification_events(supplier_code,event_type,occurred_at,
            officer,source,snapshot_hash,snapshot_json,created_at) VALUES('00110183','google_clarity',
            '2026-09-02T00:00:00+03:00','Тестова УО SANDBOX','synthetic confirmed clock','midnight-proof',?, 'fixture')""",
            (json.dumps({'edr_checked_at_source':'02.09.2026 00:00:00','edr_status':'Зареєстровано'}),))
        self.con.commit()
        self.assertEqual(projection.build(self.con)['rows'][0]['verification_datetime_precision'],'instant')
        self.assertEqual(server.supplier_profile('00110183')['edr_profile']['verification_datetime_precision'],'instant')

    def test_mixed_worker_preview_apply_and_status_agree(self):
        for i in range(1,7):supplier(self.con,str(i).zfill(8),active=True)
        self.con.commit()
        source=snapshot(row('00000001',name='ОНОВЛЕНА НАЗВА'),row('00000002',status='Немає інформації'),
            row('00000003',checked='bad'),row('00000004',checked=''),
            row('00000005',checked='2026-09-02T00:00:00+03:00'),row('00000006'))
        preview=self.plan(source);s=preview['summary']
        self.assertEqual((s['ready_with_changes'],s['ready_unchanged'],s['conflict'],s['skipped']),(2,1,2,1))
        state=copy.deepcopy(server.SUPPLIER_EDR_SYNC_STATE)
        try:
            with patch.object(server,'supplier_edr_source_snapshot',return_value=source):
                server.supplier_edr_sync_worker(source['source_fingerprint'],'fixture',sync.preview_state_digest(preview),6)
            result=server.SUPPLIER_EDR_SYNC_STATE
            self.assertEqual(result['last_result'],'completed',result)
            self.assertEqual(result['progress_processed'],6)
            self.assertEqual(result['updated'],2)
            self.assertEqual(result['last_result_summary']['updated'],2)
            self.assertEqual(result['last_result_summary']['unchanged'],1)
            self.assertEqual(result['last_result_summary']['technical_receipts'],3)
            stored=json.loads(self.con.execute('SELECT details_json FROM supplier_edr_sync_log ORDER BY id DESC LIMIT 1').fetchone()[0])
            self.assertEqual(stored['business_updated_profiles'],s['ready_with_changes'])
            self.assertEqual(stored['ready_unchanged'],s['ready_unchanged'])
            for _ in range(3):
                fresh=self.plan(source);server.supplier_edr_conflict_xlsx(fresh)
                self.assertEqual(fresh['summary']['ready_with_changes'],0)
        finally:server.SUPPLIER_EDR_SYNC_STATE.clear();server.SUPPLIER_EDR_SYNC_STATE.update(state)

    def test_wal_reader_keeps_consistent_snapshot_during_apply(self):
        for i in range(1,101):supplier(self.con,str(i).zfill(8),active=True)
        self.con.commit();barrier=threading.Barrier(2);errors=[];seen=[]
        def read():
            try:
                with server.db() as con:
                    con.execute('BEGIN');con.execute('SELECT COUNT(*) FROM supplier_edr_profiles').fetchone()
                    barrier.wait(timeout=20);barrier.wait(timeout=20)
                    seen.extend(r['verification_date'] for r in projection.build(con)['rows'])
            except BaseException as exc:errors.append(repr(exc));barrier.abort()
        thread=threading.Thread(target=read);thread.start()
        try:
            barrier.wait(timeout=20)
            source=snapshot(*(row(str(i).zfill(8)) for i in range(1,101)))
            self.apply(source);self.con.commit();barrier.wait(timeout=20)
        finally:thread.join(timeout=20)
        self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
        self.assertEqual(len(seen),100)
        self.assertTrue(all(x.startswith('2026-09-02') for x in seen))
        self.assertTrue(all(r['verification_date'].startswith('2026-11-16') for r in projection.build(self.con)['rows']))

    def test_blocked_mirror_is_not_counted_as_available(self):
        supplier(self.con,'00110183',active=True,checked='')
        source=snapshot(row('00110183',checked='bad',note='Нова примітка'))
        p=self.plan(source);self.assertTrue(p['conflicts'])
        self.assertEqual(p['summary']['m_note_updates'],0)
        self.assertEqual(p['summary']['ready_with_changes'],0)
        self.assertTrue(all(x['action'] not in {'update','clear','accept_google_pair'} for x in sandbox_edr_review.details(p)))

    def test_counter_partition_and_receipts_are_separate(self):
        for code in ['00110183','00000002','00000003']:supplier(self.con,code,active=True)
        source=snapshot(row('00110183',checked='2026-09-02T00:00:00+03:00'),row('00000002'),row('00000003',status=''))
        p=self.plan(source);s=p['summary']
        self.assertEqual((s['ready_with_changes'],s['ready_unchanged'],s['conflict']),(1,1,1))
        self.assertEqual(s['detected_differences'],s['available_changes']+s['blocked_changes']+s['skipped_changes'])
        result=self.apply(source);self.assertEqual(result['received_suppliers'],2)

    def test_stale_table_state_digest_rejects_before_writes(self):
        supplier(self.con,'00110183',active=True);source=snapshot(row('00110183'));p=self.plan(source)
        digest=sync.preview_state_digest(p);self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='РУЧНА ЗМІНА'");self.con.commit()
        before='\n'.join(self.con.iterdump())
        with self.assertRaises(RuntimeError):self.apply(source,expected_state_digest=digest)
        self.assertEqual(before,'\n'.join(self.con.iterdump()))

    def test_callback_literal_identity_is_reset_and_thread_local(self):
        for code in ['СР 918414','НВ918414']:supplier(self.con,code,active=True)
        self.con.commit()
        def establish(code):
            return server.establish_current_supplier_manager(self.con,code,'КЕРІВНИК',observed_at='2026-11-26')
        identity.callback(establish)('СР 918414')
        self.assertEqual(self.con.execute('SELECT supplier_code FROM supplier_managers').fetchone()[0],'СР 918414')
        self.assertFalse(identity.active());self.assertEqual(identity.code('НВ918414'),'918414')
        values=[]
        def scoped():values.append(identity.code('СР 918414'));raise ValueError('synthetic')
        with self.assertRaises(ValueError):identity.callback(scoped)()
        t=threading.Thread(target=lambda:values.append(identity.code('СР 918414')));t.start();t.join()
        self.assertEqual(values,['СР 918414','918414']);self.assertFalse(identity.active())

    def test_temp_paths_reject_recursive_copy(self):
        root=Path(__file__).resolve().parents[2]
        for dest in [root,root/'tmp',root.parent]:
            with self.subTest(dest=dest),self.assertRaises(ValueError):validate_paths(root,dest)

    def test_xlsx_status_values_literal_codes_and_date_precision(self):
        from openpyxl import load_workbook
        supplier(self.con,'СР 918414',checked='2026-09-02')
        p=self.plan(snapshot(row('СР 918414',status='Немає інформації')))
        wb=load_workbook(io.BytesIO(server.supplier_edr_conflict_xlsx(p)))
        values=list(wb.active.values)
        self.assertEqual(values[1][1],'СР 918414')
        self.assertEqual(values[1][5],'Неактуально')
        self.assertEqual(values[1][6],'Немає інформації')
        self.assertEqual(values[1][7],'02.09.2026')
        self.assertEqual(values[1][8].strftime('%d.%m.%Y %H:%M:%S'),'16.11.2026 08:50:30')
        self.assertIn('статус',values[1][3].lower())

    def test_malformed_nonempty_prior_date_is_not_a_first_check(self):
        supplier(self.con,'31587803',active=True,checked='not-a-date')
        plan=self.plan(snapshot(row('31587803')))
        self.assertIn('malformed_current_verification_datetime',plan['items'][0]['conflicts'])

    def test_manual_manager_priority_plan_matches_apply(self):
        for index,updated in enumerate(('2026-11-16T06:50:29Z','2026-11-16T06:50:30Z','2026-11-16T06:50:31Z')):
            code=str(index+1).zfill(8);old='РУЧНИЙ КЕРІВНИК';new='ІНШИЙ КЕРІВНИК'
            supplier(self.con,code,active=True,manager=old)
            self.con.execute("""INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,
                valid_from,is_current,source,created_at,updated_at) VALUES(?,?,?,'2026-09-01',1,'Підтверджено УО',?,?)""",
                (code,old,server.normalize_manager_name(old),updated,updated))
            source=snapshot(row(code,manager=new));p=self.plan(source)['items'][0]
            self.assertEqual('manager_name' in p['write_fields'],index==0)
            self.apply(source,sync_manager=identity.callback(server.sync_current_supplier_manager))
            self.assertEqual(self.con.execute('SELECT manager_name FROM supplier_managers WHERE supplier_code=? AND is_current=1',(code,)).fetchone()[0],new if index==0 else old)
            self.assertEqual(self.con.execute('SELECT manager_name FROM supplier_edr_profiles WHERE supplier_code=?',(code,)).fetchone()[0],new if index==0 else old)

    def test_mid_apply_exception_rolls_back_receipts_profiles_and_events(self):
        codes=('СР 918414','НВ918414')
        for code in codes:
            supplier(self.con,code,active=True,manager='СТАРИЙ КЕРІВНИК')
            self.con.execute("""INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,
                is_current,source,created_at,updated_at) VALUES(?,'СТАРИЙ КЕРІВНИК',?,1,'ЄДР','2026-09-01','2026-09-01')""",
                (code,server.normalize_manager_name('СТАРИЙ КЕРІВНИК')))
        self.con.commit();before='\n'.join(self.con.iterdump());calls=[]
        def callback(*args):
            calls.append(args[1]);value=server.sync_current_supplier_manager(*args)
            if len(calls)==2:raise RuntimeError('synthetic second-row failure')
            return value
        source=snapshot(*(row(c,manager='НОВИЙ КЕРІВНИК') for c in codes))
        self.con.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(RuntimeError,'second-row failure'):
                sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,
                    actor='fixture',synced_at='2026-11-26T12:00:00+02:00',sandbox_mode=True,
                    sync_manager=identity.callback(callback))
        finally:self.con.rollback()
        self.assertEqual(calls,list(codes));self.assertEqual(before,'\n'.join(self.con.iterdump()))

    def test_old_google_cannot_replace_pair_or_names_but_mirror_policy_remains(self):
        supplier(self.con,'00110183',active=True)
        source=snapshot(row('00110183',checked='2026-08-01T08:50:30+03:00',name='ІНША НАЗВА',note='ПРИМІТКА'))
        p=self.plan(source)['items'][0]
        self.assertNotIn('edr_checked_at',p['write_fields']);self.assertNotIn('full_name',p['write_fields'])
        self.apply(source)
        stored=self.con.execute('SELECT full_name,edr_checked_at,edr_notes FROM supplier_edr_profiles').fetchone()
        self.assertEqual(tuple(stored),('ПРИКЛАД','2026-09-02T00:00:00+03:00','ПРИМІТКА'))

    def test_google_conflict_resolution_requires_fresh_preview(self):
        supplier(self.con,'00110183',active=True)
        invalid=snapshot(row('00110183',status='Немає інформації'))
        before=self.plan(invalid);fixed=snapshot(row('00110183'))
        self.assertNotEqual(invalid['source_fingerprint'],fixed['source_fingerprint'])
        self.assertEqual(before['summary']['ready_to_apply'],0)
        self.assertEqual(self.plan(fixed)['summary']['ready_to_apply'],1)
        with self.assertRaises(RuntimeError):
            sync.apply(self.con,fixed,invalid['source_fingerprint'],confirmed=True,actor='fixture',synced_at='fixture',sandbox_mode=True)

    def test_google_status_required_independent_of_time_and_current_status(self):
        supplier(self.con,'00110183',active=True)
        for stored in ('Зареєстровано','Неактуально','Немає інформації'):
            self.con.execute('UPDATE supplier_edr_profiles SET edr_status=?',(stored,))
            for checked in ('','2026-08-01','2026-09-02T00:00:00+03:00','2026-11-16T08:50:30+02:00'):
                for empty in ('','Немає інформації','немає інформації'):
                    with self.subTest(stored=stored,checked=checked,empty=empty):
                        p=self.plan(snapshot(row('00110183',status=empty,checked=checked)))
                        self.assertIn('google_edr_status_required',p['items'][0]['conflicts'])
                        self.assertEqual(p['summary']['ready_to_apply'],0)

    def test_equal_timestamp_fop_fills_table_placeholders_without_erasing_names(self):
        supplier(self.con,'0123456789',active=True,name='—')
        source=sync.source_snapshot({'ФОП':[list(sync.HEADERS),row('0123456789',checked='2026-09-02T00:00:00+03:00',name='ПІБ ФОП')],
            'ЮО':[list(sync.HEADERS)]})
        p=self.plan(source)['items'][0]
        self.assertEqual(p['current_table_values']['full_name'],'')
        self.assertIn('full_name',p['write_fields']);self.apply(source)
        self.assertEqual(self.con.execute('SELECT full_name FROM supplier_edr_profiles').fetchone()[0],'ПІБ ФОП')
        source=sync.source_snapshot({'ФОП':[list(sync.HEADERS),row('0123456789',name='')],'ЮО':[list(sync.HEADERS)]})
        self.apply(source)
        self.assertEqual(self.con.execute('SELECT full_name FROM supplier_edr_profiles').fetchone()[0],'ПІБ ФОП')

    def test_xlsx_cross_sheet_duplicates_keep_exact_source_coordinates(self):
        from openpyxl import load_workbook
        supplier(self.con,'СР 918414',active=True)
        source=sync.source_snapshot({'ФОП':[list(sync.HEADERS),row('СР 918414',status='')],
            'ЮО':[list(sync.HEADERS),row('СР 918414',status='Немає інформації')]})
        p=self.plan(source);self.assertEqual(len(p['conflicts']),2)
        values=list(load_workbook(io.BytesIO(server.supplier_edr_conflict_xlsx(p))).active.values)[1:]
        statuses={(v[0],v[6] or '') for v in values if v[4]=='Статус ЄДР'}
        self.assertEqual(statuses,{('ФОП',''),('ЮО','Немає інформації')})

    def test_additive_contract_and_mutations(self):
        import hashlib
        manifest=json.loads((Path(__file__).parent/'contract.json').read_text(encoding='utf-8'))
        root=Path(__file__).resolve().parents[2]
        def digest(data):return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
        for name,expected in manifest['runtime_lf_sha256'].items():
            with self.subTest(file=name):
                data=(root/name).read_bytes();self.assertEqual(digest(data),expected)
                pos=len(data)//2;mutated=data[:pos]+bytes([data[pos]^1])+data[pos+1:]
                self.assertNotEqual(digest(mutated),expected)
                self.assertNotEqual(digest(data+b' '),expected)
                self.assertNotEqual(digest(data[:-1]),expected)
        source=Path(os.environ['PQM_V311_SOURCE_ROOT'])
        for name,expected in manifest['protected_lf_sha256'].items():
            self.assertEqual(digest((source/name).read_bytes()),expected,name)

    def test_unrelated_server_and_policy_functions_are_unchanged(self):
        import subprocess
        source=Path(os.environ['PQM_V311_SOURCE_ROOT'])
        allowed={
            'server.py':{'sync_current_supplier_manager','enrich_current_supplier_manager',
                'establish_current_supplier_manager','refresh_current_submission_nazk_controls',
                'reconcile_supplier_nazk_after_edr_manager_change','supplier_google_row',
                'supplier_edr_conflict_xlsx','_supplier_edr_excel_datetime','supplier_edr_sync_worker','_edr_monitoring_rows','list_qualified_suppliers','supplier_profile'},
            'edr_sync_v2.py':{'source_snapshot','source_item','_eligible_codes','_latest_application_names',
                '_code_filter','_profiles','_current_managers','_closed_manager_history','_latest_application_managers',
                'known_manager_map','resolve_known_manager','_manager_identity_evidence','_existing_codes',
                'build_preview','current_verification_projections','current_verification_event','prozorro_statuses','canonical_prozorro_statuses',
                'canonical_supplier_edr_states','_insert_event','effective_profile_fields',
                '_conflicts_are_mirror_only','preview_state_digest','apply'},
            'nazk_workflow.py':{'reconcile_active_supplier_nazk','reconcile_supplier_nazk'},
            'operational_tasks.py':{'_digits','reconcile_irrelevant_nazk_managers','reconcile_stale_nazk_tasks','materialize_nazk_tasks'},'sandbox_edr_review.py':{'details','summary_additions'}}
        for name,changed in allowed.items():
            reference=Path(__file__).parent/('reference_server.txt' if name=='server.py' else 'reference_'+name+'.txt')
            old=ast.parse(reference.read_text(encoding='utf-8-sig'))
            current=ast.parse((source/name).read_text(encoding='utf-8-sig'))
            new={n.name:n for n in current.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
            for node in old.body:
                if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name not in changed:
                    self.assertEqual(ast.dump(node,include_attributes=False),
                        ast.dump(new[node.name],include_attributes=False),name+':'+node.name)

    def test_http_auth_attestation_preview_xlsx_and_stale_export(self):
        supplier(self.con,'2884318089');supplier(self.con,'СР 918414',active=True)
        self.con.commit()
        source=snapshot(row('2884318089',status='Неактуально'),row('СР 918414',status=''))
        import sandbox_runtime
        self.enterContext(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
        self.enterContext(patch.dict(os.environ,{**server.sandbox_runtime.POLICY,
            'PQM_SANDBOX_LOCAL_FIXTURE':'1','RENDER_SERVICE_ID':'','RENDER_SERVICE_NAME':''}))
        self.enterContext(patch.object(server,'SAFE_MODE',True))
        # The protected test database lives on D:, outside the runtime's
        # system-temp-only local-fixture allowance. Exercise HTTP routing with
        # this synthetic target accepted, and keep the explicit rejecting
        # attestation case below for unsafe refresh requests.
        self.enterContext(patch.object(server.sandbox_runtime,'attest_internal_target',
            return_value=Path(server.DB_PATH)))
        source_mock=self.enterContext(patch.object(server,'supplier_edr_source_snapshot',return_value=source))
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
        def request(path,body=None,authorized=True):
            client=http_client=http_module.HTTPConnection('127.0.0.1',http.server_address[1],timeout=20)
            headers={'Authorization':auth()} if authorized else {}
            if body is not None:headers['Content-Type']='application/json'
            try:
                client.request('POST' if body is not None else 'GET',path,
                    json.dumps(body) if body is not None else None,headers)
                response=client.getresponse();return response.status,response.read()
            finally:client.close()
        import http.client as http_module
        self.assertEqual(request('/api/edr-monitoring',None,False)[0],401)
        before='\n'.join(self.con.iterdump())
        status,raw=request('/api/supplier-edr-sync/preview',{})
        self.assertEqual(status,200,raw);data=json.loads(raw)
        self.assertEqual(data['conflicts_total'],1)
        self.assertEqual(data['summary']['ready_to_apply'],1)
        status,raw=request('/api/edr-monitoring')
        self.assertEqual(status,200,raw)
        table={item['supplier_code']:item for item in json.loads(raw)['items']}
        self.assertEqual(table['2884318089']['edr_status'],'Неактуально')
        self.assertEqual(before,'\n'.join(self.con.iterdump()))
        payload={k:data[k] for k in ('source_fingerprint','state_digest')}
        status,raw=request('/api/supplier-edr-sync/conflicts.xlsx',payload)
        self.assertEqual(status,200,raw);self.assertTrue(raw.startswith(b'PK'))
        self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='Нове ручне значення'");self.con.commit()
        self.assertEqual(request('/api/supplier-edr-sync/conflicts.xlsx',payload)[0],409)
        with patch.object(server.sandbox_runtime,'attest_internal_target',side_effect=RuntimeError('wrong target')):
            calls=source_mock.call_count
            self.assertEqual(request('/api/edr-monitoring?refresh=1')[0],503)
            self.assertEqual(source_mock.call_count,calls)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:DATA.cleanup()
