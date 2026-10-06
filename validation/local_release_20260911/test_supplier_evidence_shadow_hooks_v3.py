"""Synthetic opt-in integration boundaries. No external/persistent database."""
import ast
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import edr_sync_v2 as legacy
import formed_protocols
import supplier_evidence_shadow_hooks_v3 as hooks

ROOT = Path(hooks.__file__).resolve().parent
NOW = "2026-10-06T12:00:00+03:00"
CHECK = "2026-10-05T10:00:00+03:00"
OFFICER = "Світлана НАМЯСЕНКО"
CODE = "2077003493"
ENV = {hooks.FLAG:"1","PQM_SANDBOX":"1","RENDER_SERVICE_ID":hooks.SANDBOX_ID}
DDL = """
CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT,synced_at TEXT);
CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_code TEXT,date_published TEXT,
 supplier_name TEXT,qualification_id TEXT);
CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT);
CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,protocol_officer TEXT,manager_name TEXT);
CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,supplier_code TEXT,framework_id TEXT,
 qualification_id TEXT,status TEXT,raw_json TEXT,synced_at TEXT);
CREATE TABLE supplier_edr_verification_events(id INTEGER PRIMARY KEY,supplier_code TEXT,
 event_type TEXT,occurred_at TEXT,officer TEXT,source TEXT,source_submission_id TEXT,
 source_sheet TEXT,source_row INTEGER,changed_fields TEXT,snapshot_hash TEXT,snapshot_json TEXT,
 created_at TEXT,UNIQUE(supplier_code,event_type,occurred_at,officer,snapshot_hash));
"""


def setup(con, v3=True):
    con.executescript(DDL)
    if v3:
        for name in ("20261005_supplier_evidence_v3.sql","20261006_supplier_evidence_recording_v3.sql"):
            con.executescript((ROOT/"migrations"/name).read_text(encoding="utf-8"))
    con.execute("INSERT INTO frameworks VALUES ('f','active','{}','2026-10-04T12:00:00+03:00')")
    con.commit()


class HookTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ,ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.con = sqlite3.connect(":memory:")
        setup(self.con)
        self.addCleanup(self.con.close)

    def application(self, identity="s1", stamp="2026-09-18T17:19:52.579134+03:00",
                    officer="Тетяна ФЕДЧЕНКО", status="active"):
        self.con.execute("INSERT INTO submissions VALUES (?,?,?,?,?)",(identity,CODE,stamp,"Exact supplier","q"+identity))
        self.con.execute("INSERT INTO qualifications VALUES (?,?,?)",("q"+identity,identity,status))
        self.con.execute("INSERT INTO application_fields VALUES (?,?,?)",(identity,officer,"Exact manager"))

    def contract(self, identity="c1", status="active", **fields):
        item = dict(id=identity,status=status,frameworkID="f",qualificationID="q",
            suppliers=[dict(identifier=dict(id=CODE))],**fields)
        self.con.execute("INSERT INTO registry_contracts VALUES (?,?,?,?,?,?,?)",
            (identity,CODE,"f","q",status,json.dumps(item),"2026-10-04T12:00:00+03:00"))
        return item

    def transition(self, item, status, proof=True, **evidence):
        before = hooks.capture_contract(self.con,item,NOW)
        changed = deepcopy(item)
        changed["status"] = status
        if proof:
            changed["statusHistory"] = [dict(id="transition-"+item["id"]+status,
                **{"from":item["status"],"to":status,"date":CHECK},**evidence)]
        self.con.execute("UPDATE registry_contracts SET status=?,raw_json=? WHERE id=?",
            (status,json.dumps(changed),item["id"]))
        hooks.contract_written(self.con,item=changed,previous=before,recorded_at=NOW)
        return changed, before

    def events(self):
        return self.con.execute("SELECT event_kind,source_event_at,actor_display FROM supplier_evidence_events_v3").fetchall()

    def projection(self):
        return json.loads(self.con.execute("SELECT projection_json FROM supplier_evidence_current_v3 WHERE supplier_code=?",(CODE,)).fetchone()[0])

    def check(self, stamp=CHECK, status="Зареєстровано", event_type="google_clarity"):
        return legacy._insert_event(self.con,item=dict(supplier_code=CODE,source_sheet="ЮО",source_row=5),
            event_type=event_type,occurred_at=stamp,officer=OFFICER,source="fixture",
            changed_fields=[],snapshot=dict(edr_status=status,full_name="Exact supplier"),created_at=NOW)

    def test_flag_default_off_no_schema_reads_or_writes(self):
        with patch.dict(os.environ,{hooks.FLAG:""}):
            with patch.object(hooks,"_one",side_effect=AssertionError("unexpected query")):
                hooks.application_decision(self.con,"absent","admit",NOW)
                hooks.contract_written(self.con,item={},previous=None,recorded_at=NOW)
        self.assertEqual(self.events(),[])

    def test_off_legacy_insert_unchanged_without_schema(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        setup(con,v3=False)
        with patch.dict(os.environ,{hooks.FLAG:""}):
            legacy._insert_event(con,item=dict(supplier_code=CODE),event_type="manual_edr",
                occurred_at="2026-10-05",officer=OFFICER,source="fixture",changed_fields=[],
                snapshot=dict(edr_status="Зареєстровано"),created_at=NOW)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0],1)
        self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='supplier_evidence_events_v3'").fetchone())

    def test_prod_even_flag_on_is_isolated(self):
        self.application()
        for env in ({"PQM_SANDBOX":"0"},{"RENDER_SERVICE_ID":"prod-service"},{"RENDER_SERVICE_ID":""}):
            with patch.dict(os.environ,env):
                hooks.application_decision(self.con,"s1","admit",NOW)
        self.assertEqual(self.events(),[])

    def test_admission_and_replay(self):
        self.application()
        self.contract()
        hooks.application_decision(self.con,"s1","admit",NOW)
        hooks.application_decision(self.con,"s1","admit",NOW)
        self.assertEqual(self.events(),[("admission","2026-09-18T17:19:52.579134+03:00","Тетяна ФЕДЧЕНКО")])

    def test_three_same_day_sources_exact_latest(self):
        self.contract()
        controls = [("e3edb5e958144b61b9d3320d23d2a120","17:04:21.589075"),
            ("c1939b79afce43cfbef0eadf3a0566ff","15:59:34.798180"),
            ("d27925ea7ed24af7bb4c1ec5deff4eb0","17:19:52.579134")]
        for identity, stamp in controls:
            self.application(identity,"2026-09-18T"+stamp+"+03:00")
            hooks.application_decision(self.con,identity,"admit",NOW)
        self.assertEqual(len(self.events()),3)
        self.assertEqual(self.projection()["current_event"]["provenance"]["submission_id"],controls[2][0])

    def test_missing_admission_timestamp_is_gap(self):
        self.application(stamp="2026-09-18")
        hooks.application_decision(self.con,"s1","admit",NOW)
        self.assertEqual(self.events(),[])
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_gaps_v3 WHERE gap_type='admission_date_unproven'").fetchone())

    def test_sandbox_application_fallback(self):
        self.application(officer="")
        hooks.application_decision(self.con,"s1","admit",NOW)
        self.assertEqual(self.events()[0][2],"Тестова УО SANDBOX")

    def test_never_admitted_rejection_observation_no_verification(self):
        self.application(status="unsuccessful")
        hooks.application_decision(self.con,"s1","reject",NOW)
        hooks.application_decision(self.con,"s1","reject",NOW)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.projection()["prozorro_status"],"Ще не в реєстрі")
        self.assertIsNone(self.projection()["visible_date"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_evidence_observations_v3").fetchone()[0],1)

    def test_rejection_after_admission_preserves_verification(self):
        self.test_admission_and_replay()
        previous = self.projection()["last_verification_event"]["event_id"]
        self.application("reject1", "2026-10-05T12:00:00+03:00",status="unsuccessful")
        hooks.application_decision(self.con,"reject1","reject",NOW)
        self.assertEqual(self.projection()["last_verification_event"]["event_id"],previous)
        self.assertEqual(len(self.events()),1)

    def test_clarity_unchanged_facts_new_check(self):
        self.contract()
        self.assertTrue(self.check())
        self.assertTrue(self.check("2026-10-06T10:00:00+03:00"))
        self.assertEqual(len(self.events()),2)

    def test_clarity_changed_facts(self):
        self.contract()
        self.check()
        self.check("2026-10-06T10:00:00+03:00","В стані припинення")
        self.assertEqual(self.projection()["edr_status_current"],"В стані припинення")

    def test_manual_verification_boundary(self):
        self.contract()
        self.check(event_type="manual_edr")
        self.assertEqual(self.events()[0][0],"edr_check")

    def test_real_canonical_sandbox_check_is_normal_verification(self):
        self.contract()
        legacy._insert_event(self.con,item=dict(supplier_code=CODE),event_type="manual_edr",
            occurred_at=CHECK,officer="Тестова УО SANDBOX",source="fixture",changed_fields=[],
            snapshot=dict(edr_status="Зареєстровано"),created_at=NOW)
        self.assertEqual(self.events()[0][2],"Тестова УО SANDBOX")
        self.assertEqual(self.events()[0][0],"edr_check")

    def test_system_source_cannot_be_verification_officer(self):
        # Caller must own an actual write transaction, exactly like Apply.
        self.con.execute("BEGIN")
        hooks.verification(self.con,source_id="check-system",item=dict(supplier_code=CODE),
            event_type="manual_edr",occurred_at=CHECK,officer="ЕСЗ",recorded_at=NOW,
            snapshot=dict(edr_status="Зареєстровано"))
        self.assertEqual(self.events(),[])
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_gaps_v3").fetchone())

    def test_legacy_replay_no_new_shadow(self):
        self.contract()
        self.check()
        self.assertFalse(self.check())
        self.assertEqual(len(self.events()),1)

    def test_preview_has_no_recording_hook(self):
        tree = ast.parse((ROOT/"edr_sync_v2.py").read_text(encoding="utf-8"))
        preview = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="build_preview")
        self.assertNotIn("evidence_shadow",ast.unparse(preview))
        self.assertEqual(self.events(),[])

    def test_suspension_system_actor_and_separate_last_verification(self):
        item = self.contract()
        self.check("2026-09-11")
        self.transition(item,"suspended")
        projection = self.projection()
        self.assertEqual(projection["prozorro_status"],"Припинений")
        self.assertTrue(projection["monitoring_eligible"])
        self.assertEqual(projection["last_verification_date"],"2026-09-11")
        self.assertEqual(projection["current_event_actor"]["actor_display"],"ЕСЗ")
        self.assertEqual(projection["freshness"]["age_days"],25)

    def test_new_lifecycle_preserves_proven_pre_flag_legacy_verification(self):
        item = self.contract()
        with patch.dict(os.environ,{hooks.FLAG:""}):
            self.check("2026-09-17")
        baseline = self.con.execute("SELECT * FROM supplier_edr_verification_events").fetchall()
        self.transition(item,"suspended")
        projection = self.projection()
        self.assertEqual(projection["last_verification_date"],"2026-09-17")
        self.assertEqual(projection["last_verification_officer"],OFFICER)
        self.assertEqual(projection["current_event_date"],"2026-10-05")
        self.assertEqual(projection["freshness"]["age_days"],19)
        self.assertEqual(len(self.events()),1)  # New lifecycle only, NO historical backfill.
        self.assertEqual(self.con.execute("SELECT * FROM supplier_edr_verification_events").fetchall(),baseline)
        self.assertIsNone(self.con.execute("SELECT last_verification_event_id FROM supplier_evidence_current_v3").fetchone()[0])
        self.assertEqual(projection["legacy_baseline_refs"]["last_verification"],baseline[0][0])

    def test_legacy_noncurrent_placeholder_is_not_verification_baseline(self):
        item = self.contract()
        with patch.dict(os.environ,{hooks.FLAG:""}):
            self.check("2026-09-17",status="Неактуально")
        self.transition(item,"suspended")
        self.assertIsNone(self.projection()["last_verification_date"])

    def test_resumption(self):
        item = self.contract(status="suspended")
        self.transition(item,"active")
        self.assertIn(("resumption",CHECK,"ЕСЗ"),self.events())

    def test_native_prozorro_ban_date_met_is_suspension_source(self):
        item = self.contract()
        before = hooks.capture_contract(self.con,item,NOW)
        changed = dict(item,status="suspended",milestones=[dict(id="ban-1",type="ban",status="met",dateMet=CHECK)])
        self.con.execute("UPDATE registry_contracts SET status='suspended',raw_json=? WHERE id='c1'",(json.dumps(changed),))
        hooks.contract_written(self.con,item=changed,previous=before,recorded_at=NOW)
        self.assertEqual(self.events(),[("suspension",CHECK,"ЕСЗ")])
        prov = self.projection()["current_event_provenance"]
        self.assertEqual(prov["source_field"],"milestones.dateMet")
        self.assertEqual(prov["milestone_id"],"ban-1")

    def test_other_active_inclusion_prevents_supplier_suspension(self):
        item = self.contract()
        self.contract("c2")
        self.transition(item,"suspended")
        self.assertEqual(self.events(),[])
        self.assertEqual(self.projection()["prozorro_status"],"Активний")

    def test_missing_transition_date_gap_not_date_modified(self):
        item = self.contract(dateModified=CHECK)
        self.transition(item,"suspended",proof=False)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.con.execute("SELECT gap_type,known_event_date FROM supplier_evidence_gaps_v3").fetchone(),("suspension_date_unproven",""))

    def test_partial_termination(self):
        item = self.contract()
        self.contract("c2")
        self.transition(item,"terminated",automatic=False,officer=OFFICER)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.projection()["prozorro_status"],"Активний")
        self.assertEqual(self.con.execute("SELECT event_kind FROM supplier_inclusion_history_v3").fetchone()[0],"termination")

    def test_manual_exclusion_last_inclusion(self):
        item = self.contract()
        self.transition(item,"terminated",automatic=False,officer=OFFICER)
        self.assertEqual(self.events(),[("exclusion",CHECK,OFFICER)])
        self.assertEqual(self.projection()["edr_status_current"],"Неактуально")

    def test_last_loss_timestamp_not_contract_processing_order(self):
        later = self.contract("late")
        earlier = self.contract("early")
        self.transition(later,"terminated",automatic=False,officer=OFFICER)
        proof = dict(source_object="contract",source_id="early",source_field="statusHistory",
            transition_at="2026-10-05T09:00:00+03:00",source_event_id="earlier-event",
            automatic=False,officer="Тетяна ФЕДЧЕНКО")
        before = hooks.capture_contract(self.con,earlier,NOW)
        changed = dict(earlier,status="terminated")
        self.con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='early'")
        hooks.contract_written(self.con,item=changed,previous=before,recorded_at=NOW,proof=proof)
        self.assertEqual(self.events(),[("exclusion",CHECK,OFFICER)])

    def test_last_loss_same_timestamp_is_explicit_ambiguity(self):
        first = self.contract("first")
        second = self.contract("second")
        self.transition(first,"terminated",automatic=False,officer=OFFICER)
        self.transition(second,"terminated",automatic=False,officer=OFFICER)
        self.assertEqual(self.events(),[])
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_gaps_v3 WHERE gap_type='chronology_ambiguity'").fetchone())

    def test_manual_exclusion_missing_officer_gap(self):
        item = self.contract()
        self.transition(item,"terminated",automatic=False)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.con.execute("SELECT gap_type FROM supplier_evidence_gaps_v3").fetchone()[0],"missing_attribution")

    def test_unknown_termination_type_is_gap(self):
        item = self.contract()
        self.transition(item,"terminated")
        self.assertEqual(self.events(),[])

    def test_automatic_termination_uses_expiry_source_not_transition_time(self):
        boundary = "2026-10-04T23:00:00+03:00"
        item = self.contract(expiryDate=boundary)
        before = dict(status="active",before_inclusions=[dict(supplier_code=CODE,inclusion_id="c1",state="active")])
        changed = dict(item,status="terminated")
        self.con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='c1'")
        proof = dict(source_object="contract",source_id="c1",source_field="statusHistory",
            transition_at=CHECK,source_event_id="termination",automatic=True,expiry_boundary=True)
        hooks.contract_written(self.con,item=changed,previous=before,recorded_at=NOW,proof=proof)
        self.assertEqual(self.events(),[("expiry",boundary,"ЕСЗ")])

    def test_truthy_expiry_marker_is_not_proven_boundary(self):
        item = self.contract()
        before = hooks.capture_contract(self.con,item,NOW)
        changed = dict(item,status="terminated")
        self.con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='c1'")
        proof = dict(source_object="contract",source_id="c1",source_field="statusHistory",
            transition_at=CHECK,source_event_id="termination",automatic=True,expiry_boundary=True)
        hooks.contract_written(self.con,item=changed,previous=before,recorded_at=NOW,proof=proof)
        self.assertEqual(self.events(),[])
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_gaps_v3 WHERE gap_type='termination_date_unproven'").fetchone())

    def test_expiry_observed_boundary_crossing(self):
        item = self.contract(expiryDate="2026-10-05T23:00:00+03:00")
        with patch.dict(os.environ,{hooks.FLAG:""}):
            self.check("2026-09-17")
        previous = dict(status="active",synced_at="2026-10-04T12:00:00+03:00",
            before_inclusions=[dict(supplier_code=CODE,inclusion_id="c1",state="active")])
        hooks.contract_written(self.con,item=item,previous=previous,recorded_at=NOW)
        self.assertEqual(self.events(),[("expiry","2026-10-05T23:00:00+03:00","ЕСЗ")])
        self.assertEqual(self.projection()["last_verification_date"],"2026-09-17")

    def test_already_expired_baseline_not_backfilled(self):
        item = self.contract(expiryDate="2026-10-05T23:00:00+03:00")
        hooks.contract_written(self.con,item=item,previous=dict(status="active",synced_at=NOW),recorded_at=NOW)
        self.assertEqual(self.events(),[])

    def test_shadow_failure_keeps_legacy_insert_and_logs(self):
        self.contract()
        with patch.object(hooks.recorder,"update_projection",side_effect=RuntimeError("fixture fault")):
            with self.assertLogs(hooks.LOG,level="ERROR") as logs:
                self.assertTrue(self.check())
        self.assertIn("shadow_failed_legacy_unchanged",logs.output[0])
        self.assertEqual(self.events(),[])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0],1)

    def test_legacy_outer_failure_rolls_back_shadow(self):
        self.contract()
        self.con.commit()
        with self.assertRaises(RuntimeError):
            with self.con:
                self.check()
                raise RuntimeError("legacy operation failed")
        self.assertEqual(self.events(),[])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0],0)

    def test_missing_schema_observable_no_ddl(self):
        self.con.execute("DROP TABLE supplier_evidence_current_v3")
        self.application()
        with self.assertLogs(hooks.LOG,level="ERROR"):
            hooks.application_decision(self.con,"s1","admit",NOW)
        self.assertEqual(self.events(),[])
        self.assertFalse(self.con.execute("SELECT 1 FROM sqlite_master WHERE name='supplier_evidence_current_v3'").fetchone())

    def test_targeted_queries_no_population_rebuild(self):
        self.application()
        self.contract()
        sql = []
        self.con.set_trace_callback(sql.append)
        hooks.application_decision(self.con,"s1","admit",NOW)
        for statement in sql:
            if statement.startswith("SELECT") and any(name in statement for name in
                    ("registry_contracts","submissions","supplier_evidence_events_v3")):
                self.assertIn("WHERE",statement)
        self.assertNotIn("_edr_monitoring_rows",(ROOT/"supplier_evidence_shadow_hooks_v3.py").read_text())

    def test_readonly_manual_review_export_and_selective_resolution(self):
        self.contract()
        hooks._project(self.con,CODE,NOW)
        before = self.con.total_changes
        rows = hooks.recorder.manual_review_dataset(self.con,environment="sandbox")
        self.assertEqual(self.con.total_changes,before)
        self.assertEqual(len(rows["rows"]),1)
        self.check()
        self.assertEqual(hooks.recorder.manual_review_dataset(self.con,environment="sandbox")["rows"],[])

    def test_historical_gap_not_closed_by_new_check(self):
        self.contract()
        hooks._gap(self.con,CODE,"contract","legacy",NOW,{},"termination_date_unproven","No date",history_only=True)
        self.check()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_evidence_gaps_v3").fetchone()[0],1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_evidence_gap_resolutions_v3").fetchone()[0],0)

    def test_manual_review_known_name_no_mutation_unknown_dates_blank(self):
        self.application()
        hooks._gap(self.con,CODE,"source","unknown",NOW,{},"missing_attribution","Unknown actor")
        before = self.con.total_changes
        dataset = hooks.manual_review_dataset(self.con)
        self.assertEqual(dataset["rows"][0]["supplier_name"],"Exact supplier")
        self.assertEqual(dataset["rows"][0]["known_event_dates"],[""])
        self.assertEqual(self.con.total_changes,before)

    def test_failed_shadow_explicit_source_retry_is_idempotent(self):
        self.contract()
        with patch.object(hooks.recorder,"update_projection",side_effect=RuntimeError("fault")):
            with self.assertLogs(hooks.LOG,level="ERROR"):
                self.check()
        identity = self.con.execute("SELECT id FROM supplier_edr_verification_events").fetchone()[0]
        for _ in range(2):
            hooks.verification(self.con,source_id=identity,item=dict(supplier_code=CODE,source_sheet="ЮО",source_row=5),
                event_type="google_clarity",occurred_at=CHECK,officer=OFFICER,recorded_at=NOW,
                snapshot=dict(edr_status="Зареєстровано",full_name="Exact supplier"))
        self.assertEqual(len(self.events()),1)

    def test_same_timestamp_chronology_gap_not_id_tiebreak(self):
        self.contract()
        self.application("first",CHECK)
        self.application("second",CHECK)
        for identity in ("first","second"):
            hooks.application_decision(self.con,identity,"admit",NOW)
        self.assertIsNone(self.projection()["current_event"])
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_gaps_v3 WHERE gap_type='chronology_ambiguity'").fetchone())

    def test_transition_history_uses_exact_chronology_not_list_order(self):
        item = self.contract()
        changed = dict(item,status="suspended",statusHistory=[
            {"id":"early","from":"active","to":"suspended","date":"2026-10-05T09:00:00+03:00"},
            {"id":"late","from":"active","to":"suspended","date":"2026-10-05T11:00:00+03:00"}])
        self.assertEqual(hooks.transition_provenance(changed,"active","suspended")["source_event_id"],"late")
        changed["statusHistory"].reverse()
        self.assertEqual(hooks.transition_provenance(changed,"active","suspended")["source_event_id"],"late")
        changed["statusHistory"].append(deepcopy(changed["statusHistory"][0]))
        self.assertEqual(hooks.transition_provenance(changed,"active","suspended")["source_event_id"],"late")

    def test_transition_tied_exact_timestamps_are_gap(self):
        item = self.contract()
        changed = dict(item,status="suspended",statusHistory=[
            {"id":"one","from":"active","to":"suspended","date":CHECK},
            {"id":"two","from":"active","to":"suspended","date":CHECK}])
        self.assertEqual(hooks.transition_provenance(changed,"active","suspended"),{"ambiguity":"ambiguous_same_timestamp"})

    def test_framework_expiry_convention_gap_not_poll_time_event(self):
        self.contract()
        previous = hooks.capture_framework(self.con,"f")
        item = dict(id="f",status="active",qualificationPeriod=dict(endDate="2026-10-05T23:00:00+03:00"))
        self.con.execute("UPDATE frameworks SET raw_json=? WHERE id='f'",(json.dumps(item),))
        hooks.framework_written(self.con,item=item,previous=previous,recorded_at=NOW)
        self.assertEqual(self.events(),[])
        gap = self.con.execute("SELECT gap_type,known_event_date,known_actor FROM supplier_evidence_gaps_v3").fetchone()
        self.assertEqual(gap,("expiry_boundary_requires_explicit_source_convention","","ЕСЗ"))

    def test_framework_hook_off_does_not_read_contracts(self):
        with patch.dict(os.environ,{hooks.FLAG:""}):
            with patch.object(hooks,"_project",side_effect=AssertionError("unexpected")):
                hooks.framework_written(self.con,item={},previous={},recorded_at=NOW)
        self.assertEqual(self.events(),[])

    def test_invalid_framework_source_is_observable_nonblocking(self):
        self.contract()
        with self.assertLogs(hooks.LOG,level="ERROR"):
            hooks.framework_written(self.con,item=dict(id="f",qualificationPeriod="invalid"),
                previous=dict(raw_json="{}",status="active",synced_at=CHECK),recorded_at=NOW)
        self.assertTrue(self.con.in_transaction)
        self.assertEqual(self.events(),[])

    def test_fatal_sqlite_outer_transaction_loss_is_not_hidden(self):
        self.contract()
        def fatal(*args,**kwargs):
            self.con.rollback()
            raise sqlite3.OperationalError("synthetic transaction invalidation")
        with patch.object(hooks.recorder,"append_event",side_effect=fatal):
            with self.assertLogs(hooks.LOG,level="CRITICAL"):
                with self.assertRaises(sqlite3.OperationalError):
                    self.check()
        self.assertFalse(self.con.in_transaction)

    def test_real_formed_protocol_write_boundary(self):
        self.con.row_factory=sqlite3.Row
        self.application(status="pending")
        existing = {r[1] for r in self.con.execute("PRAGMA table_info(application_fields)")}
        columns = formed_protocols.PROTECTED | {"generated_protocol_number","generated_protocol_date",
            "generated_protocol_decision","protocol_generated_at"}
        for column in sorted(columns-existing):
            self.con.execute(f"ALTER TABLE application_fields ADD COLUMN {column} TEXT DEFAULT ''")
        self.con.execute("CREATE TABLE audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)")
        formed_protocols.migrate(self.con)
        self.con.execute("UPDATE application_fields SET protocol_decision='admit',protocol_number='fixture',protocol_date='2026-10-05' WHERE submission_id='s1'")
        item = dict(self.con.execute("SELECT * FROM application_fields WHERE submission_id='s1'").fetchone(),id="s1")
        payload = dict(protocol_number="fixture",protocol_date="2026-10-05",officer="Тетяна ФЕДЧЕНКО")
        self.con.commit()
        with tempfile.TemporaryDirectory() as folder:
            def builder(_, path):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b"synthetic-docx")
            with self.con, patch.object(formed_protocols,"stamp",return_value=NOW):
                self.con.execute("BEGIN IMMEDIATE")
                result = formed_protocols.create(self.con,[item],payload,folder,builder,"fixture.user")
            self.assertTrue(result["generated"])
            self.assertEqual(self.events(),[])  # A generated draft does not change ESЗ qualification.
            self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_observations_v3 WHERE source_object='admission_pending_catalogue'").fetchone())
            with self.con:
                self.con.execute("UPDATE qualifications SET status='active' WHERE submission_id='s1'")
                hooks.application_decision(self.con,"s1","admit",NOW)
            self.assertEqual(self.events()[0][1],"2026-09-18T17:19:52.579134+03:00")

    def test_inclusion_projection_failure_all_shadow_writes_rollback(self):
        item = self.contract()
        with patch.object(hooks.recorder,"update_projection",side_effect=RuntimeError("fault")):
            with self.assertLogs(hooks.LOG,level="ERROR"):
                self.transition(item,"terminated",automatic=False,officer=OFFICER)
        self.assertEqual(self.events(),[])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_inclusion_history_v3").fetchone()[0],0)
        self.assertEqual(self.con.execute("SELECT status FROM registry_contracts").fetchone()[0],"terminated")

    def test_existing_write_boundaries_ast_no_startup_migration(self):
        server_source = (ROOT/"server.py").read_text(encoding="utf-8")
        tree = ast.parse(server_source)
        init = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="init_db")
        self.assertNotIn("evidence_shadow",ast.unparse(init))
        sync = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="sync_one_framework")
        self.assertIn("evidence_shadow.contract_written",ast.unparse(sync))
        self.assertIn("evidence_shadow.application_decision",ast.unparse(sync))
        self.assertNotIn("supplier_evidence_current_v3",server_source)

    def test_real_framework_ingestion_admission_and_rejection_hooks(self):
        # Execute the unchanged real function body, not a copied write adapter.
        # Only remote transport, ancillary workers and the old materializer are
        # fixture stubs. Its actual SQL and new hook callsites run on SQLite.
        for table, columns in {
            "submissions":{"framework_id":"TEXT","status":"TEXT","documents_json":"TEXT","raw_json":"TEXT","synced_at":"TEXT"},
            "qualifications":{"framework_id":"TEXT","decision_date":"TEXT","documents_json":"TEXT","raw_json":"TEXT","synced_at":"TEXT"},
            "application_fields":{"manager_name_source":"TEXT DEFAULT ''","manager_name_source_submission_id":"TEXT","updated_at":"TEXT","updated_by":"TEXT"},
        }.items():
            for column, definition in columns.items():
                self.con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self.con.executescript("""CREATE TABLE framework_service_directory(framework_id TEXT,responsible_officer TEXT);
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT,manager_name TEXT,edr_checked_at TEXT);
          CREATE TABLE supplier_managers(supplier_code TEXT,manager_name TEXT,is_current INTEGER,valid_from TEXT);""")
        self.con.create_function("DIGITS",1,lambda value: str(value or ""))
        @contextmanager
        def db():
            with self.con:
                yield self.con
        source = ast.parse((ROOT/"server.py").read_text(encoding="utf-8"))
        fn = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=="sync_one_framework")
        module = ast.Module(body=[fn],type_ignores=[])
        submissions = [dict(id="real-admit",datePublished=CHECK,qualificationID="qa",
            tenderers=[dict(name="Supplier",identifier=dict(id=CODE))])]
        qualifications = [dict(id="qa",submissionID="real-admit",status="active",dateModified=NOW)]
        namespace = dict(save_framework=lambda _:True,db=db,API_ROOT="fixture://no-network",
            scoped_pages=lambda _,kind,cursor:[submissions if kind=="submissions" else qualifications],
            paginated_pages=lambda *args:[],now_iso=lambda:NOW,json=json,
            ensure_submission_nazk_control=lambda *args:None,
            enqueue_contract_experience_search=lambda *args:None,
            edr_sync_v2=SimpleNamespace(materialize_effective_admission=lambda *args:False),
            evidence_shadow=hooks)
        exec(compile(module,"server.py:sync_one_framework","exec"),namespace)
        result = namespace["sync_one_framework"]("f",dict(prettyID="fixture",agreementID="a"))
        self.assertEqual(result["qualifications"],1)
        self.assertEqual(self.events()[0][1],CHECK)
        self.assertEqual(self.events()[0][2],"Тестова УО SANDBOX")
        submissions[:] = [dict(submissions[0],id="real-reject",qualificationID="qr")]
        qualifications[:] = [dict(id="qr",submissionID="real-reject",status="unsuccessful",dateModified=NOW)]
        namespace["sync_one_framework"]("f",dict(prettyID="fixture",agreementID="a"))
        self.assertEqual(len(self.events()),1)
        self.assertTrue(self.con.execute("SELECT 1 FROM supplier_evidence_observations_v3 WHERE source_object='rejection'").fetchone())

    def test_migration_fresh_upgrade_repeat_does_not_touch_legacy(self):
        self.application()
        baseline = self.con.execute("SELECT * FROM submissions").fetchall()
        for _ in range(2):
            for name in ("20261005_supplier_evidence_v3.sql","20261006_supplier_evidence_recording_v3.sql"):
                self.con.executescript((ROOT/"migrations"/name).read_text(encoding="utf-8"))
        self.assertEqual(self.con.execute("SELECT * FROM submissions").fetchall(),baseline)

    def test_concurrent_replay_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/"fixture.sqlite3")
            con = sqlite3.connect(path)
            setup(con)
            con.execute("INSERT INTO registry_contracts VALUES ('c',?,'f','q','active','{}',?)",(CODE,NOW))
            con.commit()
            con.close()
            def replay(_):
                c = sqlite3.connect(path,timeout=10)
                try:
                    with c:
                        c.execute("BEGIN IMMEDIATE")
                        return legacy._insert_event(c,item=dict(supplier_code=CODE),event_type="manual_edr",
                            occurred_at=CHECK,officer=OFFICER,source="fixture",changed_fields=[],
                            snapshot=dict(edr_status="Зареєстровано"),created_at=NOW)
                finally:
                    c.close()
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(replay,range(8))),1)
            c = sqlite3.connect(path)
            try:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM supplier_evidence_events_v3").fetchone()[0],1)
            finally:
                c.close()


if __name__=="__main__":
    unittest.main()
