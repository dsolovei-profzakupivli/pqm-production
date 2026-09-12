import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import nazk_workflow as workflow
import operational_tasks
import server


class NazkWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
        server.init_reference_tables(server.DB_PATH)

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def seed_supplier(self, code="10000001", active=1, manager="КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ",
                      registry=True):
        with server.db() as con:
            con.execute("""INSERT INTO supplier_registry_summary
              (supplier_code,supplier_name,active_count,refreshed_at) VALUES (?,?,?,?)""",
              (code, code, active, server.now_iso()))
            manager_id = None
            if manager is not None:
                cursor = con.execute("""INSERT INTO supplier_managers
                  (supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
                  VALUES (?,?,?,1,'test',?,?)""",
                  (code, manager, workflow.normalize_name(manager), server.now_iso(), server.now_iso()))
                manager_id = cursor.lastrowid
            if registry and manager:
                con.execute("""INSERT INTO nazk_registry
                  (source_id,full_name,court_case_number,sentence_date,punishment_start,raw_json)
                  VALUES (?,?,?,?,?,?)""",
                  (f"nazk-{code}", manager, "1/1/26", "2026-01-10", "2026-02-10", "{}"))
        return manager_id

    def seed_submission(self, code="10000001", manager="КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ",
                        submission_id="submission-1"):
        document = {"id": "doc-1", "title": "Довідка.pdf", "url": "https://example/doc-1"}
        with server.db() as con:
            con.execute("""INSERT OR IGNORE INTO frameworks
              (id,pretty_id,status,raw_json,synced_at)
              VALUES ('framework-1','UA-F-TEST','active',?,?)""",
              (json.dumps({"period": {"endDate": "2099-12-31T00:00:00"}}), server.now_iso()))
            qualification_id = f"qualification-{submission_id}"
            con.execute("INSERT OR IGNORE INTO qualifications(id,status) VALUES (?,'pending')",
                        (qualification_id,))
            con.execute("""INSERT INTO submissions
              (id,framework_id,supplier_code,supplier_name,qualification_id,documents_json,raw_json,synced_at)
              VALUES (?,?,?,?,?,?,'{}',?)""",
              (submission_id, "framework-1", code, code, qualification_id,
               json.dumps([document]), server.now_iso()))
            con.execute("INSERT INTO application_fields(submission_id,manager_name) VALUES (?,?)",
                        (submission_id, manager))
        return document

    def state(self, code="10000001"):
        with server.db() as con:
            return workflow.get_supplier_nazk_state(con, code)

    def link_check(self, con, check_id, source_id="nazk-10000001"):
        con.execute("""INSERT INTO supplier_nazk_check_matches
          (check_id,nazk_source_id,match_status,created_at)
          VALUES (?,?,'candidate',?)""", (check_id, source_id, server.now_iso()))

    def test_manager_tax_id_reused_and_audited_across_submissions(self):
        mid=self.seed_supplier()
        for i in range(20):self.seed_submission(submission_id=f'reuse-{i}')
        with server.db() as con:
            self.assertEqual(workflow.submission_manager_tax_context(con,'reuse-0')['value'],'')
            workflow.save_submission_manager_tax_id(con,'reuse-0','1234567890','Officer A',mid)
            for i in range(20):
                context=workflow.submission_manager_tax_context(con,f'reuse-{i}')
                self.assertEqual(context['value'],'1234567890');self.assertEqual(context['source'],'manager')
            workflow.save_submission_manager_tax_id(con,'reuse-1','1234567891','Officer B',mid)
            workflow.save_submission_manager_tax_id(con,'reuse-1','1234567891','Officer B',mid)
            events=con.execute("SELECT * FROM audit_log WHERE field_name=? ORDER BY id",(f'manager_tax_id:{mid}',)).fetchall()
            self.assertEqual(len(events),2);self.assertEqual(events[-1]['changed_by'],'Officer B')
            self.assertEqual(events[-1]['old_value'],'1234567890');self.assertTrue(events[-1]['changed_at'])
            with self.assertRaises(ValueError):workflow.save_submission_manager_tax_id(con,'reuse-1','bad','test',mid)
            with self.assertRaises(ValueError):workflow.save_submission_manager_tax_id(con,'reuse-1','1234567892','test',mid+1)

    def test_changed_manager_does_not_inherit_tax_id(self):
        mid=self.seed_supplier();self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con,'submission-1')
            workflow.save_submission_manager_tax_id(con,'submission-1','1234567890','test',mid)
            con.execute('UPDATE supplier_managers SET is_current=0 WHERE id=?',(mid,))
            con.execute("INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at) VALUES('10000001','ІНША ОСОБА','ІНША ОСОБА',1,'test','now','now')")
            context=workflow.submission_manager_tax_context(con,'submission-1')
            self.assertEqual(context['value'],'');self.assertFalse(context['editable'])
            with self.assertRaises(ValueError):workflow.save_submission_manager_tax_id(con,'submission-1','1234567891','test',mid)
            self.assertEqual(con.execute('SELECT manager_tax_id FROM supplier_managers WHERE id=?',(mid,)).fetchone()[0],'1234567890')

    def test_inactive_supplier_is_not_reconciled(self):
        self.seed_supplier(active=0)
        self.assertEqual(self.state()["state"], "inactive")

    def test_supplier_badge_priorities_cover_legacy_and_submission_cases(self):
        present = workflow.get_supplier_nazk_presentation_state
        self.assertEqual(present("not_required", "", registry_match=True), "inactive")
        self.assertEqual(present("not_required", "waiting_response", registry_match=True),
                         "waiting_response")
        self.assertEqual(present("needs_check", "", registry_match=True), "needs_check")
        self.assertEqual(present("not_required", "needs_review", registry_match=True),
                         "needs_supplier_review")
        self.assertEqual(present("refuted", "", registry_match=True), "refuted")
        self.assertEqual(present("not_required", "completed", registry_match=True,
                                 legacy_result="refuted"), "refuted")
        self.assertEqual(present("not_required", "completed", registry_match=True,
                                 legacy_result="confirmed"), "confirmed")
        self.assertEqual(present("needs_check", "completed", registry_match=True,
                                 legacy_result="refuted"), "refuted")
        self.assertEqual(present("needs_check", "needs_review", registry_match=True,
                                 legacy_result="refuted"), "needs_supplier_review")
        self.assertEqual(present("needs_check", "waiting_response", registry_match=True),
                         "waiting_response")
        self.assertEqual(present(
            "not_required", "waiting_response", registry_match=False,
            registry_record_no_longer_present=True,
        ), "inactive")
        self.assertEqual(present(
            "not_required", "waiting_response", registry_match=True,
            registry_record_no_longer_present=False,
        ), "waiting_response")

    def test_current_match_materializes_supplier_check_and_operational_task(self):
        self.seed_supplier()
        self.seed_submission()
        with server.db() as con:
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('qualification-submission-1','framework-1','submission-1','active','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("UPDATE submissions SET qualification_id='qualification-submission-1' WHERE id='submission-1'")
            con.execute("UPDATE frameworks SET raw_json=? WHERE id='framework-1'", (
                json.dumps({"qualificationPeriod": {"endDate": "2099-12-31T00:00:00"}}),
            ))
            con.execute("""INSERT INTO registry_contracts
              (id,framework_id,qualification_id,supplier_code,status,milestones_json,raw_json,synced_at)
              VALUES ('contract-1','framework-1','qualification-submission-1','10000001','active','[]','{}',?)""",
              (server.now_iso(),))
            created = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            first = operational_tasks.materialize_nazk_tasks(
                con, "test", supplier_codes=["10000001"])
            second = operational_tasks.materialize_nazk_tasks(
                con, "test repeat", supplier_codes=["10000001"])
            task = con.execute("""SELECT status,task_type FROM operational_tasks
              WHERE supplier_code='10000001' AND task_type='nazk_check'""").fetchall()
        self.assertTrue(created["created"])
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual([tuple(row) for row in task], [("in_progress", "nazk_check")])

    def test_check_evidence_is_shared_by_active_closed_task_and_supplier_profile(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('qualification-submission-1','framework-1','submission-1','active','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("UPDATE submissions SET qualification_id='qualification-submission-1' WHERE id='submission-1'")
            con.execute("UPDATE frameworks SET raw_json=? WHERE id='framework-1'",(
                json.dumps({"qualificationPeriod":{"endDate":"2099-12-31T00:00:00"}}),))
            con.execute("""INSERT INTO registry_contracts
              (id,framework_id,qualification_id,supplier_code,status,milestones_json,raw_json,synced_at)
              VALUES ('contract-1','framework-1','qualification-submission-1','10000001','active','[]','{}',?)""",
              (server.now_iso(),))
            created=workflow.reconcile_supplier_nazk(con,"10000001",apply=True)
            operational_tasks.materialize_nazk_tasks(con,"test",supplier_codes=["10000001"])
            task_id=con.execute("SELECT id FROM operational_tasks WHERE task_type='nazk_check'").fetchone()[0]
            officer_id=con.execute("""INSERT INTO authorized_officers(full_name,role,active,created_at,updated_at)
              VALUES ('УО ТЕСТ','УО',1,?,?)""",(server.now_iso(),server.now_iso())).lastrowid
            operational_tasks.update(con,task_id,{"assigned_officer_id":officer_id},"УО ТЕСТ")
            operational_tasks.set_task_manager_tax_id(con,task_id,"1234567890","УО ТЕСТ")
            operational_tasks.record_channel_sent(con,task_id,"supplier",{
                "sent_at":"2026-09-12","outgoing_number":"12","reference_url":"https://example/request",
                "comment":"Направлено постачальнику"},"УО ТЕСТ")
            operational_tasks.add_response(con,task_id,{
                "source":"supplier","response_date":"2026-09-12","incoming_number":"34",
                "reference_url":"https://example/evidence","document_reference":"response.pdf",
                "summary":"Отримано довідку","information_result":"neutral"},"УО ТЕСТ")
            active=operational_tasks.detail(con,task_id)
            self.assertEqual(active["nazk_check_id"],created["check_id"])
            self.assertEqual(active["nazk_current_state"]["person_tax_id"],"1234567890")
            self.assertEqual(active["assigned_officer_name"],"УО ТЕСТ")
            self.assertEqual(active["responses"][0]["incoming_number"],"34")
            payload=active["nazk_evidence"]
            self.assertEqual(payload["person_rnokpp"],"1234567890")
            self.assertEqual(payload["responsible_officer"]["name"],"УО ТЕСТ")
            self.assertEqual(payload["registry_source_ids"],["nazk-10000001"])
            self.assertEqual(payload["responses_info"][0]["source_task_id"],task_id)
            self.assertEqual(payload["provenance"]["operational_tasks"][0]["task_id"],task_id)
            evidence_id=active["responses"][0]["id"]
            operational_tasks.update_response(con,task_id,evidence_id,{
                "source":"supplier","response_date":"2026-09-12","incoming_number":"34-A",
                "reference_url":"https://example/evidence-updated","document_reference":"response.pdf",
                "summary":"Уточнена довідка","comment":"Перевірено","information_result":"neutral"},"УО ТЕСТ")
            edited=operational_tasks.detail(con,task_id)
            self.assertEqual(edited["responses"][0]["incoming_number"],"34-A")
            self.assertEqual(edited["responses"][0]["comment"],"Перевірено")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_nazk_check_evidence WHERE check_id=?",
                                         (created["check_id"],)).fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events WHERE task_id=? AND event_type='response_information_edited'",
                                         (task_id,)).fetchone()[0],1)
            operational_tasks.set_nazk_result(con,task_id,"refuted","УО ТЕСТ")
            closed=operational_tasks.detail(con,task_id)
            self.assertEqual(closed["nazk_evidence"]["evidence"],edited["nazk_evidence"]["evidence"])
            with self.assertRaisesRegex(ValueError,"лише для перегляду"):
                operational_tasks.update_response(con,task_id,evidence_id,{"source":"supplier"},"УО ТЕСТ")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_responses").fetchone()[0],0)
        profile=server.supplier_profile("10000001")
        check=next(item for item in profile["supplier_nazk_checks"] if item["id"]==created["check_id"])
        self.assertEqual(check["evidence_set"]["evidence"],closed["nazk_evidence"]["evidence"])
        self.assertEqual(check["evidence_set"]["channels"],closed["nazk_evidence"]["channels"])
        self.assertEqual(check["evidence_set"]["registry_records"],closed["nazk_evidence"]["registry_records"])

    def test_legacy_task_evidence_backfill_is_idempotent(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            check_id=con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              SELECT '10000001',id,manager_name,'needs_review',NULL,?,0,?,'test',?,'test'
              FROM supplier_managers WHERE supplier_code='10000001' AND is_current=1""",
              (server.now_iso(),server.now_iso(),server.now_iso())).lastrowid
            task_id='legacy-task'
            con.execute("""INSERT INTO operational_tasks
              (id,task_key,task_type,supplier_code,status,priority,created_at,updated_at,source_context)
              VALUES (?,?, 'nazk_check','10000001','in_progress','high',?,?,?)""",
              (task_id,'legacy-key',server.now_iso(),server.now_iso(),json.dumps({'nazk_check_id':check_id})))
            con.execute("""INSERT INTO operational_task_responses
              (task_id,source,response_date,incoming_number,reference_url,document_reference,summary,
               information_result,post_close,recorded_at,recorded_by)
              VALUES (?,'supplier','2026-09-01','1','https://example/e','legacy.pdf','Legacy evidence',
                      'neutral',0,?,'test')""",(task_id,server.now_iso()))
            import nazk_evidence
            nazk_evidence.migrate(con); nazk_evidence.migrate(con)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_nazk_check_evidence WHERE check_id=?",
                                         (check_id,)).fetchone()[0],1)

    def test_supplier_profile_returns_registry_fact_independently_of_workflow(self):
        manager_id = self.seed_supplier()
        self.seed_submission()
        with server.db() as con:
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
               is_legacy,created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-08-20','2026-08-21',
                      0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
        profile = server.supplier_profile("10000001")
        self.assertEqual(len(profile["nazk"]), 1)
        self.assertEqual(profile["nazk"][0]["court_case_number"], "1/1/26")
        self.assertEqual(profile["supplier_nazk_checks"][0]["result"], "refuted")

    def test_active_supplier_without_manager(self):
        self.seed_supplier(manager=None, registry=False)
        self.assertEqual(self.state()["state"], "missing_manager")

    def test_active_manager_without_registry_match(self):
        self.seed_supplier(registry=False)
        self.assertEqual(self.state()["state"], "no_matches")

    def test_current_match_without_history_needs_review(self):
        self.seed_supplier()
        self.assertEqual(self.state()["action"], "create_needs_review")

    def test_legacy_refuted_without_coverage_needs_new_review(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-01-01',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
        self.assertEqual(self.state()["reason"], "legacy_refuted_without_coverage")

    def test_nonlegacy_factual_result_with_exact_registry_relation_covers_cycle(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            check_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
               evidence_date,covered_nazk_date,is_legacy,created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-03-01','2026-03-01',
                      '2026-03-01','2026-02-10',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            self.link_check(con, check_id)
        self.assertEqual(self.state()["state"], "refuted")
        self.assertEqual(self.state()["check_id"], 1)

    def test_current_confirmed_is_current_state(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            check_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','confirmed','2026-03-01','2026-03-01',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            self.link_check(con, check_id)
        self.assertEqual(self.state()["state"], "confirmed")

    def test_historical_confirmed_is_not_transferred(self):
        current_id = self.seed_supplier(manager="НОВИЙ КЕРІВНИК", registry=True)
        with server.db() as con:
            old = con.execute("""INSERT INTO supplier_managers
              (supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
              VALUES ('10000001','СТАРИЙ КЕРІВНИК',?,0,'test',?,?)""",
              (workflow.normalize_name("СТАРИЙ КЕРІВНИК"), server.now_iso(), server.now_iso())).lastrowid
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,'СТАРИЙ КЕРІВНИК','completed','confirmed','2026-01-01','2026-01-01',1,?,'УО',?,'УО')""",
              (old, server.now_iso(), server.now_iso()))
        self.assertNotEqual(current_id, old)
        self.assertEqual(self.state()["state"], "needs_review")

    def test_current_waiting_response_is_preserved(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'waiting_response','2026-01-01',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
        self.assertEqual(self.state()["state"], "waiting_response")

    def test_legacy_archived_current_match_needs_review(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'legacy_archived','2026-01-01',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
        self.assertEqual(self.state()["reason"], "legacy_archived_current_match")

    def test_reconciliation_is_idempotent(self):
        self.seed_supplier()
        with server.db() as con:
            first = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            second = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            total = con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0]
        self.assertTrue(first["created"])
        self.assertIsNone(second.get("action"))
        self.assertEqual(total, 1)

    def test_not_current_covers_only_the_same_registry_cycle(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            check_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'not_current',NULL,'2026-09-12',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            con.execute("""INSERT INTO supplier_nazk_check_matches
              (check_id,nazk_source_id,match_status,created_at) VALUES (?,'nazk-10000001','candidate',?)""",
              (check_id, server.now_iso()))
            same = workflow.get_supplier_nazk_state(con, "10000001")
            con.execute("""INSERT INTO nazk_registry(source_id,full_name,court_case_number,sentence_date,
              punishment_start,decision_url,raw_json)
              VALUES ('nazk-new','КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ','2/2/26','2026-09-11',
                      '2026-09-12','https://example.test/new','{}')""")
            newer = workflow.get_supplier_nazk_state(con, "10000001")
        self.assertEqual(same["state"], "inactive")
        self.assertIsNone(same["action"])
        self.assertEqual(newer["action"], "create_needs_review")

    def test_same_person_factual_cycle_archives_redundant_check_without_changing_result(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            factual_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
               evidence_date,is_legacy,created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-03-01','2026-03-01',
                      '2026-03-01',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            self.link_check(con, factual_id)
            duplicate_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'needs_review',NULL,'2026-09-10',0,?,'PQM',?,'PQM')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            state = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            repeat = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            factual = con.execute("SELECT workflow_status,result FROM supplier_nazk_checks WHERE id=?", (factual_id,)).fetchone()
            duplicate = con.execute("SELECT workflow_status,result FROM supplier_nazk_checks WHERE id=?", (duplicate_id,)).fetchone()
            events = con.execute("SELECT COUNT(*) FROM supplier_nazk_check_events WHERE check_id=? AND event_type='duplicate_cycle_reconciled_to_existing_factual'", (duplicate_id,)).fetchone()[0]
        self.assertEqual(state["archived"], 1)
        self.assertIsNone(repeat.get("action"))
        self.assertEqual(tuple(factual), ("completed", "refuted"))
        self.assertEqual(tuple(duplicate), ("legacy_archived", None))
        self.assertEqual(events, 1)

    def test_newer_registry_fact_is_not_covered_by_older_factual_result(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            con.execute("UPDATE nazk_registry SET punishment_start='2026-12-01' WHERE source_id='nazk-10000001'")
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
               evidence_date,is_legacy,created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-03-01','2026-03-01',
                      '2026-03-01',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
            state = workflow.get_supplier_nazk_state(con, "10000001")
        self.assertEqual(state["action"], "create_needs_review")
        self.assertEqual(state["reason"], "refuted_without_coverage")

    def test_refuted_materialization_only_completes_its_own_check_cycle(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            refuted_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-01-01','2026-01-02',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            other_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'needs_review',NULL,'2026-09-10',0,?,'PQM',?,'PQM')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            task_a, _ = operational_tasks._create(con, "cycle-a", "nazk_check", "10000001", "high",
                {"nazk_check_id": refuted_id}, {}, "in_progress")
            task_b, _ = operational_tasks._create(con, "cycle-b", "nazk_check", "10000001", "high",
                {"nazk_check_id": other_id}, {}, "in_progress")
            operational_tasks.materialize_nazk_tasks(con, "test", supplier_codes=["10000001"],
                active_applications={"10000001": [{"id": "a"}]}, supplier_names={"10000001": "Supplier"})
            states = {row["id"]: row["status"] for row in con.execute("SELECT id,status FROM operational_tasks WHERE id IN (?,?)", (task_a, task_b))}
        self.assertEqual(states[task_a], "completed")
        self.assertEqual(states[task_b], "in_progress")

    def test_targeted_duplicate_task_correction_is_nonfactual_and_idempotent(self):
        manager_id = self.seed_supplier()
        with server.db() as con:
            factual_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,evidence_date,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-03-01','2026-03-01','2026-03-01',0,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            self.link_check(con, factual_id)
            duplicate_id = con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'needs_review',NULL,'2026-09-10',0,?,'PQM',?,'PQM')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso())).lastrowid
            task_id, _ = operational_tasks._create(con, "duplicate-cycle", "nazk_check", "10000001", "high",
                {"nazk_check_id": duplicate_id}, {}, "completed")
            con.execute("UPDATE operational_tasks SET resolution_code='nazk_refuted' WHERE id=?", (task_id,))
            first = operational_tasks.reconcile_duplicate_nazk_tasks(con, [task_id], "test", apply=True)
            second = operational_tasks.reconcile_duplicate_nazk_tasks(con, [task_id], "test repeat", apply=True)
            task = con.execute("SELECT status,resolution_code,source_context FROM operational_tasks WHERE id=?", (task_id,)).fetchone()
            factual = con.execute("SELECT result FROM supplier_nazk_checks WHERE id=?", (factual_id,)).fetchone()[0]
            duplicate = con.execute("SELECT workflow_status,result FROM supplier_nazk_checks WHERE id=?", (duplicate_id,)).fetchone()
        self.assertEqual((first["changed"], second["changed"]), (1, 0))
        self.assertEqual((task["status"], task["resolution_code"]), ("cancelled", "duplicate_cycle_existing_factual"))
        self.assertIn(str(factual_id), task["source_context"])
        self.assertEqual(factual, "refuted")
        self.assertEqual(tuple(duplicate), ("legacy_archived", None))

    def test_supplier_level_request_and_refuted_completion(self):
        self.seed_supplier()
        with server.db() as con:
            created = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            sent = workflow.mark_supplier_nazk_request_sent(
                con, created["check_id"], changed_by="УО", comment="Запит направлено")
            queued = con.execute("SELECT workflow_status FROM supplier_nazk_checks WHERE id=?",
                                 (created["check_id"],)).fetchone()[0]
            completed = workflow.complete_supplier_nazk_check(
                con, created["check_id"], result="refuted", evidence_date="2026-08-24",
                document_url="https://example/response", checked_by="УО", comment="Спростовано")
            row = con.execute("SELECT workflow_status,result FROM supplier_nazk_checks WHERE id=?",
                              (created["check_id"],)).fetchone()
            documents = con.execute("SELECT COUNT(*) FROM supplier_nazk_check_documents WHERE check_id=?",
                                    (created["check_id"],)).fetchone()[0]
        self.assertTrue(sent["changed"])
        self.assertEqual(queued, "waiting_response")
        self.assertTrue(completed["changed"])
        self.assertEqual(tuple(row), ("completed", "refuted"))
        self.assertEqual(documents, 1)

    def test_supplier_level_confirmed_never_changes_qualification(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('supplier-level-q','framework-1','submission-1','active','[]','{}',?)""",
              (server.now_iso(),))
            created = workflow.reconcile_supplier_nazk(con, "10000001", apply=True)
            workflow.mark_supplier_nazk_request_sent(con, created["check_id"], changed_by="УО")
            before = con.execute("SELECT status FROM qualifications WHERE id='supplier-level-q'").fetchone()[0]
            workflow.complete_supplier_nazk_check(
                con, created["check_id"], result="confirmed", evidence_date="2026-08-24",
                document_url="https://example/response", checked_by="УО")
            after = con.execute("SELECT status FROM qualifications WHERE id='supplier-level-q'").fetchone()[0]
        self.assertEqual((before, after), ("active", "active"))

    def test_submission_without_match_not_required(self):
        self.seed_supplier(registry=False); self.seed_submission()
        with server.db() as con:
            control = workflow.ensure_submission_nazk_control(con, "submission-1")
        self.assertEqual(control["nazk_certificate_required"], 0)

    def test_submission_with_match_is_required_and_unchecked(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            control = workflow.ensure_submission_nazk_control(con, "submission-1")
        self.assertEqual((control["nazk_certificate_required"], control["nazk_certificate_checked"]), (1, 0))

    def test_old_refuted_does_not_check_new_submission(self):
        manager_id = self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
               created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-01-01',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
            control = workflow.ensure_submission_nazk_control(con, "submission-1")
        self.assertEqual((control["nazk_certificate_required"], control["nazk_certificate_checked"]), (1, 0))

    def test_autofilled_manager_still_creates_fresh_control(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            con.execute("""UPDATE application_fields SET manager_name_source='previous_application',
              manager_name_source_submission_id='old-submission' WHERE submission_id='submission-1'""")
            control = workflow.ensure_submission_nazk_control(con, "submission-1")
        self.assertEqual((control["nazk_certificate_required"], control["nazk_certificate_checked"]), (1, 0))

    def test_manager_change_resets_control(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            con.execute("UPDATE submission_nazk_controls SET nazk_certificate_checked=1 WHERE submission_id='submission-1'")
            control = workflow.ensure_submission_nazk_control(con, "submission-1", "ІНША ЛЮДИНА")
        self.assertEqual((control["nazk_certificate_required"], control["nazk_certificate_checked"]), (0, 0))

    def test_change_to_matching_manager_requires_new_check(self):
        self.seed_supplier(); self.seed_submission(manager="ІНША ЛЮДИНА")
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            control = workflow.ensure_submission_nazk_control(con, "submission-1", "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ")
        self.assertEqual((control["nazk_certificate_required"], control["nazk_certificate_checked"]), (1, 0))

    def test_certificate_completion_and_repeat_are_idempotent(self):
        self.seed_supplier(); document = self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            first = workflow.complete_submission_nazk_check(
                con, "submission-1", document_id=document["id"], document_url=document["url"],
                evidence_date="2026-08-24", checked_by="Світлана НАМЯСЕНКО")
            second = workflow.complete_submission_nazk_check(
                con, "submission-1", document_id=document["id"], document_url=document["url"],
                evidence_date="2026-08-24", checked_by="Світлана НАМЯСЕНКО")
            counts = (con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0],
                      con.execute("SELECT COUNT(*) FROM supplier_nazk_check_documents").fetchone()[0],
                      con.execute("SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?",
                                  (first["check_id"],)).fetchone()[0])
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(counts, (1, 1, 1))

    def test_submission_check_rejects_document_from_another_submission(self):
        self.seed_supplier(); self.seed_submission(submission_id="submission-current")
        self.seed_submission(submission_id="submission-foreign")
        foreign_document = {
            "id": "doc-foreign", "title": "Чужа довідка.pdf",
            "url": "https://example/doc-foreign",
        }
        with server.db() as con:
            con.execute("UPDATE submissions SET documents_json=? WHERE id='submission-foreign'",
                        (json.dumps([foreign_document]),))
            workflow.ensure_submission_nazk_control(con, "submission-current")
            with self.assertRaisesRegex(ValueError, "документ не знайдено"):
                workflow.complete_submission_nazk_check(
                    con, "submission-current", document_id=foreign_document["id"],
                    document_url=foreign_document["url"], evidence_date="2026-08-25",
                    checked_by="УО")
            control = con.execute("""SELECT nazk_certificate_checked,supplier_nazk_check_id
              FROM submission_nazk_controls WHERE submission_id='submission-current'""").fetchone()
        self.assertEqual(tuple(control), (0, None))

    def test_submission_state_required_unchecked_needs_check(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            state = workflow.get_submission_nazk_state(con, "submission-1")
        self.assertEqual(state["state"], "needs_check")
        self.assertFalse(state["can_approve"])

    def test_framework_marker_is_strictly_submission_specific(self):
        present = workflow.get_submission_nazk_presentation_state
        self.assertEqual(present({"control_id": 1, "state": "needs_check", "registry_match": True}),
                         "needs_check")
        self.assertEqual(present({"control_id": 2, "state": "refuted", "registry_match": True}),
                         "refuted")
        self.assertEqual(present({"control_id": 3, "state": "confirmed", "registry_match": True}),
                         "confirmed")
        self.assertEqual(present({"control_id": None, "state": "needs_check", "registry_match": True}),
                         "possible")
        self.assertEqual(present({"control_id": None, "state": "not_required", "registry_match": False}),
                         "")
        # An older application or a supplier-level result is not an input to
        # another submission's presentation state.
        old_submission = {"control_id": 4, "state": "refuted", "registry_match": True}
        new_submission = {"control_id": None, "state": "needs_check", "registry_match": True}
        supplier_level_refuted = {"workflow_status": "completed", "result": "refuted"}
        self.assertEqual(present(old_submission), "refuted")
        self.assertEqual(present(new_submission), "possible")
        self.assertEqual(present(supplier_level_refuted), "")

    def test_existing_but_unselected_document_does_not_unlock_approval(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            state = workflow.get_submission_nazk_state(con, "submission-1")
        self.assertEqual(state["reason"], "submission_check_incomplete")
        self.assertFalse(state["can_approve"])

    def test_completed_refuted_submission_unlocks_approval_and_history(self):
        self.seed_supplier(); document = self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            workflow.complete_submission_nazk_check(
                con, "submission-1", document_id=document["id"], document_url=document["url"],
                evidence_date="2026-08-21", checked_by="Світлана НАМЯСЕНКО", comment="Перевірено")
            state = workflow.get_submission_nazk_state(con, "submission-1")
        self.assertEqual(state["state"], "refuted")
        self.assertTrue(state["can_approve"])
        profile = server.supplier_profile("10000001")
        self.assertEqual(len(profile["nazk_check_history"]), 1)
        self.assertEqual(profile["nazk_check_history"][0]["result"], "refuted")

    def test_batch_submission_states_match_single_state_results(self):
        self.seed_supplier(code="10000001", registry=True)
        self.seed_submission(code="10000001", submission_id="submission-batch-1")
        self.seed_supplier(code="10000002", manager="ІНШИЙ КЕРІВНИК", registry=False)
        self.seed_submission(code="10000002", manager="ІНШИЙ КЕРІВНИК",
                             submission_id="submission-batch-2")
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-batch-1")
            workflow.ensure_submission_nazk_control(con, "submission-batch-2")
            registry_names = {workflow.normalize_name(row[0]) for row in con.execute(
                "SELECT full_name FROM nazk_registry")}
            expected = {
                submission_id: workflow.get_submission_nazk_state(
                    con, submission_id, registry_names
                )
                for submission_id in ("submission-batch-1", "submission-batch-2")
            }
            actual = workflow.get_submission_nazk_states(
                con, ["submission-batch-1", "submission-batch-2"], registry_names
            )
        self.assertEqual(actual, expected)

    def test_old_refuted_new_submission_needs_check_wins_supplier_state(self):
        self.seed_supplier(); old_document = self.seed_submission(submission_id="submission-old")
        self.seed_submission(submission_id="submission-new")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-20' WHERE id='submission-old'")
            con.execute("UPDATE submissions SET date_published='2026-08-24' WHERE id='submission-new'")
            workflow.ensure_submission_nazk_control(con, "submission-old")
            workflow.complete_submission_nazk_check(
                con, "submission-old", document_id=old_document["id"], document_url=old_document["url"],
                evidence_date="2026-08-20", checked_by="УО")
            workflow.ensure_submission_nazk_control(con, "submission-new")
            state = workflow.get_supplier_application_nazk_state(con, "10000001")
        self.assertEqual(state["submission_id"], "submission-new")
        self.assertEqual(state["state"], "needs_check")
        self.assertFalse(state["can_approve"])

    def test_completed_framework_control_is_not_current_supplier_action(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            con.execute("UPDATE frameworks SET status='complete' WHERE id='framework-1'")
            state = workflow.get_supplier_application_nazk_state(con, "10000001")
        self.assertEqual(state["state"], "not_required")
        self.assertEqual(state["submission_id"], "")

    def test_no_document_never_creates_confirmed_and_rejected_remains_valid_value(self):
        self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            state = workflow.get_submission_nazk_state(con, "submission-1")
            checks = con.execute("SELECT COUNT(*) FROM supplier_nazk_checks WHERE result='confirmed'").fetchone()[0]
        self.assertEqual((state["state"], checks), ("needs_check", 0))
        self.assertIn("rejected", server.COMPLIANCE_STATUSES)

    def test_new_submission_uses_current_edr_manager_when_application_manager_is_empty(self):
        manager = "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ"
        self.seed_supplier(manager=manager)
        self.seed_submission(manager="", submission_id="submission-new")
        with server.db() as con:
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,manager_name,synced_at) VALUES (?,?,?)""",
              ("10000001", manager, server.now_iso()))
            control = workflow.ensure_submission_nazk_control(con, "submission-new")
        self.assertEqual(control["manager_name"], manager)
        self.assertEqual(control["nazk_certificate_required"], 1)
        self.assertEqual(control["nazk_certificate_checked"], 0)

    def test_transitional_backfill_dry_run_is_read_only_and_application_specific(self):
        self.seed_supplier()
        self.seed_submission(submission_id="active-2026")
        with server.db() as con:
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('qualification-1','framework-1','active-2026','active','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("""UPDATE submissions SET date_published='2026-08-24T10:00:00+03:00',
              qualification_id='qualification-1' WHERE id='active-2026'""")
            before = con.execute("SELECT COUNT(*) FROM submission_nazk_controls").fetchone()[0]
            first = workflow.transitional_submission_backfill_dry_run(con, 2026)
            second = workflow.transitional_submission_backfill_dry_run(con, 2026)
            after = con.execute("SELECT COUNT(*) FROM submission_nazk_controls").fetchone()[0]
        self.assertEqual(first, second)
        self.assertEqual((before, after, first["writes_performed"]), (0, 0, 0))
        self.assertEqual(first["candidate_count"], 1)
        self.assertEqual(first["candidates"][0]["submission_id"], "active-2026")

    def test_transitional_backfill_excludes_unsuccessful_qualification(self):
        self.seed_supplier()
        self.seed_submission(submission_id="unsuccessful-2026")
        with server.db() as con:
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('qualification-2','framework-1','unsuccessful-2026','unsuccessful','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("""UPDATE submissions SET date_published='2026-08-24T10:00:00+03:00',
              qualification_id='qualification-2' WHERE id='unsuccessful-2026'""")
            result = workflow.transitional_submission_backfill_dry_run(con, 2026)
        self.assertEqual(result["candidate_count"], 0)

    def test_supplier_contacts_come_from_submission_and_are_deduplicated(self):
        self.seed_supplier()
        self.seed_submission(submission_id="contact-new")
        self.seed_submission(submission_id="contact-old")
        payload = json.dumps({"tenderers": [{"contactPoint": {
            "name": "Тестова Особа", "email": "test@example.com",
            "telephone": "+380441112233", "url": "https://example.com"
        }}]}, ensure_ascii=False)
        with server.db() as con:
            con.execute("UPDATE submissions SET raw_json=?,date_published='2026-08-24' WHERE id='contact-new'",
                        (payload,))
            con.execute("UPDATE submissions SET raw_json=?,date_published='2025-08-24' WHERE id='contact-old'",
                        (payload,))
        profile = server.supplier_profile("10000001")
        self.assertEqual(profile["contacts"]["current"]["email"], "test@example.com")
        self.assertEqual(profile["contacts"]["history"], [])
        self.assertEqual(profile["edr_profile"].get("manager_name", ""), "")

    def test_supplier_profile_groups_individual_applications_by_framework(self):
        self.seed_supplier()
        self.seed_submission(submission_id="attempt-current")
        self.seed_submission(submission_id="attempt-old")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-25' WHERE id='attempt-current'")
            con.execute("UPDATE submissions SET date_published='2026-08-20' WHERE id='attempt-old'")
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('history-current','framework-1','attempt-current','pending','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES ('history-old','framework-1','attempt-old','unsuccessful','[]','{}',?)""",
              (server.now_iso(),))
            con.execute("UPDATE submissions SET qualification_id='history-current' WHERE id='attempt-current'")
            con.execute("UPDATE submissions SET qualification_id='history-old' WHERE id='attempt-old'")
            con.execute("""UPDATE application_fields SET protocol_remarks='Не відповідає вимогам'
              WHERE submission_id='attempt-old'""")
        groups = server.supplier_profile("10000001")["application_history_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["applications_count"], 2)
        self.assertEqual(groups[0]["rejected_count"], 1)
        self.assertEqual([row["id"] for row in groups[0]["applications"]],
                         ["attempt-current", "attempt-old"])
        self.assertEqual(groups[0]["applications"][1]["protocol_remarks"],
                         "Не відповідає вимогам")

    def test_supplier_profile_uses_final_qualification_when_submission_link_is_stale(self):
        self.seed_supplier()
        self.seed_submission(submission_id="stale-failed")
        with server.db() as con:
            con.execute("""UPDATE qualifications SET framework_id='framework-1',
              submission_id='stale-failed',status='pending' WHERE id='qualification-stale-failed'""")
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,decision_date,documents_json,raw_json,synced_at)
              VALUES ('final-failed','framework-1','stale-failed','unsuccessful','2026-08-25',
                      '[]','{}',?)""", (server.now_iso(),))
            con.execute("""UPDATE application_fields SET protocol_remarks='Історичне зауваження',
              protocol_officer='ІСТОРИЧНА УО' WHERE submission_id='stale-failed'""")
        application = server.supplier_profile("10000001")["application_history_groups"][0]["applications"][0]
        self.assertEqual(application["qualification_status"], "unsuccessful")
        self.assertEqual(application["protocol_remarks"], "Історичне зауваження")
        self.assertEqual(application["protocol_officer"], "ІСТОРИЧНА УО")

    def test_submission_nazk_context_keeps_supplier_result_context_only(self):
        manager_id = self.seed_supplier(); self.seed_submission()
        with server.db() as con:
            workflow.ensure_submission_nazk_control(con, "submission-1")
            con.execute("""INSERT INTO supplier_nazk_checks
              (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
               comment,is_legacy,created_at,created_by,updated_at,updated_by)
              VALUES ('10000001',?,?,'completed','refuted','2026-08-20','2026-08-21',
                      'Попередня перевірка',1,?,'УО',?,'УО')""",
              (manager_id, "КЕРІВНИК ТЕСТОВИЙ ІВАНОВИЧ", server.now_iso(), server.now_iso()))
            context = server.submission_nazk_context(con, "submission-1")
            state = workflow.get_submission_nazk_state(con, "submission-1")
        self.assertEqual(context["manager"]["previous"], "")
        self.assertIn("offense_name", context["registry_matches"][0])
        self.assertEqual(context["latest_supplier_check"]["result"], "refuted")
        self.assertEqual(state["state"], "needs_check")

    def test_previous_known_manager_prefers_previous_submission(self):
        self.seed_supplier(); self.seed_submission(submission_id="current")
        self.seed_submission(manager="ПОПЕРЕДНІЙ КЕРІВНИК", submission_id="previous")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-25' WHERE id='current'")
            con.execute("UPDATE submissions SET date_published='2026-08-20' WHERE id='previous'")
            workflow.ensure_submission_nazk_control(con, "current")
            context = server.submission_nazk_context(con, "current")
        self.assertEqual(context["manager"]["previous"], "ПОПЕРЕДНІЙ КЕРІВНИК")
        self.assertEqual(context["manager"]["previous_source"], "previous_submission")

    def test_previous_known_manager_falls_back_to_earlier_edr_check(self):
        manager = "КЕРІВНИК З ЄДР"
        self.seed_supplier(manager=manager); self.seed_submission(manager=manager, submission_id="current")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-25' WHERE id='current'")
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,manager_name,edr_checked_at,synced_at) VALUES (?,?,?,?)""",
              ("10000001", manager, "17.08.2026", server.now_iso()))
            workflow.ensure_submission_nazk_control(con, "current")
            context = server.submission_nazk_context(con, "current")
        self.assertEqual(context["manager"]["previous"], manager)
        self.assertEqual(context["manager"]["previous_source"], "edr_profile")
        self.assertEqual(context["manager"]["previous_date"], "17.08.2026")

    def test_edr_check_after_submission_is_not_previous_known_state(self):
        manager = "КЕРІВНИК ПІСЛЯ ЗАЯВКИ"
        self.seed_supplier(manager=manager); self.seed_submission(manager=manager, submission_id="current")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-25' WHERE id='current'")
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,manager_name,edr_checked_at,synced_at) VALUES (?,?,?,?)""",
              ("10000001", manager, "26.08.2026", server.now_iso()))
            con.execute("""UPDATE supplier_managers SET created_at='2026-08-27',updated_at='2026-08-27'
              WHERE supplier_code='10000001'""")
            workflow.ensure_submission_nazk_control(con, "current")
            context = server.submission_nazk_context(con, "current")
        self.assertEqual(context["manager"]["previous"], "")

    def test_previous_known_manager_stays_empty_without_trusted_prior_source(self):
        manager = "ЛИШЕ ПОТОЧНИЙ КЕРІВНИК"
        self.seed_supplier(manager=manager); self.seed_submission(manager=manager, submission_id="current")
        with server.db() as con:
            con.execute("UPDATE submissions SET date_published='2026-08-25' WHERE id='current'")
            con.execute("""UPDATE supplier_managers SET created_at='2026-08-27',updated_at='2026-08-27'
              WHERE supplier_code='10000001'""")
            workflow.ensure_submission_nazk_control(con, "current")
            context = server.submission_nazk_context(con, "current")
        self.assertEqual(context["manager"]["previous"], "")
        self.assertEqual(context["manager"]["previous_source"], "")

    def test_date_only_renderer_does_not_add_timezone_time(self):
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("if(/^\\d{4}-\\d{2}-\\d{2}$/.test(String(value).trim()))return displayDateOnly(value)",
                      source)
        self.assertIn("return`${iso[3]}.${iso[2]}.${iso[1]}`", source)

    def test_submission_nazk_modal_uses_two_column_overflow_safe_layout(self):
        css = Path("styles.css").read_text(encoding="utf-8")
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:minmax(0,1.35fr) minmax(330px,.8fr)", css)
        self.assertIn("grid-template-columns:auto minmax(0,1fr) auto", css)
        self.assertIn("overflow-x:hidden", css)
        self.assertIn("submission-nazk-decision-link", source)

    def test_supplier_profile_deduplicates_submission_checks_from_supplier_history(self):
        source = Path("app.js").read_text(encoding="utf-8")
        css = Path("styles.css").read_text(encoding="utf-8")
        self.assertIn("submissionNazkCheckIds", source)
        self.assertIn("supplierOnlyNazkHistory=supplierNazkHistory.filter", source)
        self.assertIn("supplier-nazk-completed-history", source)
        self.assertIn(".supplier-nazk-completed-history", css)
        self.assertIn("latestFactualSupplierNazkCheck", source)
        self.assertIn("item.workflow_status==='completed'&&['confirmed','refuted'].includes(item.result)", source)
        self.assertIn("operational-edit-response", source)

    def test_application_renderer_keeps_completed_nazk_badge_and_editable_trusted_manager_value(self):
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("row.nazkState==='refuted'", source)
        self.assertIn("НАЗК · Спростовано", source)
        self.assertNotIn("Збіг не підтверджено", source)
        self.assertIn('data-result="refuted">Спростовано</button>', source)
        self.assertIn("managerName:x.manager_name||x.manager_name_display||''", source)
        self.assertIn("managerName:'manager_name'", source)

    def test_applications_api_exposes_manager_fallback_without_overwriting_subject_field(self):
        source = Path("server.py").read_text(encoding="utf-8")
        self.assertIn('item["manager_name_display"] = item.get("manager_name") or submission_nazk.get("manager_name", "")', source)
        self.assertIn('item["manager_name_display_source"] = "edr_fallback"', source)

    def test_supplier_card_icon_and_code_copy_are_independent_actions(self):
        source = Path("app.js").read_text(encoding="utf-8")
        edrpou_branch = source.split("if(col.key==='edrpou')", 1)[1].split("if(col.key==='clarity')", 1)[0]
        participant_branch = source.split("if(col.key==='participant')", 1)[1].split("if(col.key==='edrpou')", 1)[0]
        self.assertIn('data-copy-key="edrpou"', edrpou_branch)
        self.assertIn('supplier-history-open supplier-profile-icon', edrpou_branch)
        self.assertIn('Всі заявки постачальника', edrpou_branch)
        self.assertNotIn('supplier-profile-open', participant_branch)

    def test_supplier_profile_prepares_truthful_violation_summary_without_threshold_guess(self):
        source = Path("server.py").read_text(encoding="utf-8")
        self.assertIn("SUM(CASE WHEN status='satisfied' THEN 1 ELSE 0 END) satisfied", source)
        self.assertIn("violation_threshold_summary(satisfied_decision_dates)", source)
        self.assertIn('"violation_summary": violation_summary', source)

    def test_violation_threshold_summary_uses_inclusive_rolling_calendar_months_and_decision_date(self):
        dates = [
            "2026-02-28", "2026-03-01", "2026-03-05", "2026-04-05",
            "2026-06-05", "2026-06-07", "2026-07-07", "2026-08-25",
        ]
        result = server.violation_threshold_summary(
            dates, datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(result["current_month"], 1)
        self.assertEqual(result["three_calendar_months"], 4)
        self.assertEqual(result["current_month_from"], "2026-07-25")
        self.assertEqual(result["three_calendar_months_from"], "2026-05-25")
        self.assertEqual(result["calculated_to"], "2026-08-25")
        self.assertEqual(result["date_basis"], "decision_date")

    def test_supplier_profile_is_summary_first_and_procurements_are_on_demand(self):
        server_source = Path("server.py").read_text(encoding="utf-8")
        profile_source = server_source.split("def supplier_profile", 1)[1].split(
            "def supplier_procurements", 1
        )[0]
        self.assertNotIn('"procurements":', profile_source)
        self.assertIn('COUNT(DISTINCT b.tender_id) participations', profile_source)
        self.assertIn('last_participation_date', profile_source)
        self.assertIn('def supplier_procurements', server_source)
        self.assertIn('/api/supplier-procurements/', server_source)

    def test_review_officer_is_audit_field_not_protocol_assignment(self):
        source = Path("server.py").read_text(encoding="utf-8")
        self.assertIn("review_officer TEXT DEFAULT ''", source)
        self.assertIn('if field == "protocol_decision"', source)
        self.assertIn("UPDATE application_fields SET review_officer=?", source)
        self.assertIn("{effective_officer_sql()} protocol_officer", source)
        self.assertNotIn("review_officer,''),NULLIF(fo.officer", source)

    def test_supplier_list_completed_submission_nazk_result_has_presentation_precedence(self):
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn(
            "completedApplicationNazk=['refuted','confirmed'].includes(applicationNazk.state)?applicationNazk.state:''",
            source,
        )

    def test_edr_manager_refresh_is_current_submission_scoped_and_history_safe(self):
        source = Path("server.py").read_text(encoding="utf-8")
        refresh = source.split("def refresh_current_submission_nazk_controls", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("q.status='active'", refresh)
        self.assertIn("lower(coalesce(f.status,''))='active'", refresh.lower())
        self.assertIn("$.qualificationPeriod.endDate", refresh)
        self.assertIn("ensure_submission_nazk_control", refresh)
        self.assertNotIn("UPDATE submission_nazk_controls", refresh)
        app_source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn(
            "nazkState=completedApplicationNazk||item.nazk_presentation_state",
            app_source,
        )

    def test_framework_resync_reconciles_existing_submission_nazk_control(self):
        source = Path("server.py").read_text(encoding="utf-8")
        sync_fragment = source.split("def sync_one_framework", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('ensure_submission_nazk_control(con, item["id"])', sync_fragment)
        self.assertNotIn("submission_is_new", sync_fragment)

    def test_admin_template_list_uses_existing_date_formatter_and_hides_raw_errors(self):
        source = Path("app.js").read_text(encoding="utf-8")
        fragment = source.split("async function loadAdminTemplates", 1)[1].split(
            "async function loadAdminDocumentMetadata", 1
        )[0]
        self.assertIn("displayDate(x.modified_at)", fragment)
        self.assertNotIn("fmtDateTime", fragment)
        self.assertIn("Не вдалося завантажити шаблони", fragment)
        self.assertNotIn("${esc(error.message)}", fragment)


if __name__ == "__main__":
    unittest.main()
