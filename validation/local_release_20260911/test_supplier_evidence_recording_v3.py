"""Stage 3 standalone recording: synthetic in-memory databases only."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest

import supplier_evidence_recording_v3 as r

ROOT = Path(r.__file__).resolve().parent
STAMP = "2026-10-06T12:00:00+03:00"
OFFICER = {"actor_type":"officer", "actor_display":"Світлана НАМЯСЕНКО", "officer_id":"fixture.officer"}
SYSTEM = {"actor_type":"system", "actor_display":"ЕСЗ"}


def check(identity="check-1", code="33345054", **updates):
    event = dict(supplier_code=code,kind="edr_check",effective_date="2026-10-05",
        source_event_at="2026-10-05T10:00:00+03:00",recorded_at=STAMP,
        actor=OFFICER,source_system="fixture",source_event_id=identity,
        snapshot={"edr_status":"Зареєстровано","full_name":"Exact name"},
        provenance={"check_run_id":identity},environment="sandbox")
    event.update(updates)
    return event


def context(code="33345054", **updates):
    result = dict(environment="sandbox",supplier_code=code,as_of="2026-10-06",
        rebuilt_at=STAMP,inclusions=[{"supplier_code":code,"state":"active"}])
    result.update(updates)
    return result


def transition(kind="suspension", **updates):
    prov = dict(source_object="contract",source_id="contract-1",source_field="status",
        time_evidence="source_transition",supplier_level=True)
    if kind in ("exclusion","expiry"):
        prov.update(inclusion_id="inclusion-1",effective_active_before=1,effective_active_after=0)
    if kind == "expiry":
        prov["time_evidence"] = "expiry_boundary"
    return check(kind,kind=kind,snapshot={},actor=OFFICER if kind=="exclusion" else SYSTEM,
                 provenance=prov,**updates)


def inclusion(identity="inc-1", kind="activation", inclusion_id="i-1", **updates):
    item = dict(supplier_code="33345054",inclusion_id=inclusion_id,kind=kind,
        state_after={"activation":"active","suspension":"suspended","resumption":"active",
                     "termination":"inactive","expiry":"inactive"}[kind],
        effective_date="2026-10-05",source_event_at="2026-10-05T10:00:00+03:00",
        recorded_at=STAMP,source_system="fixture",source_event_id=identity,actor=SYSTEM,
        provenance={"source_object":"contract","source_id":inclusion_id,"source_field":"status",
                    "automatic_manual":"automatic","time_evidence":"source_transition"},
        environment="sandbox")
    if kind == "expiry":
        item["provenance"]["time_evidence"] = "expiry_boundary"
    item.update(updates)
    return item


def gap(kind="stale_factual_state", scope="active", remediation="factual_verification"):
    return dict(gap_type=kind,gap_reason="Evidence requires review",review_scope=scope,
        remediation=remediation,recommended_action="Перевірити за ЕСЗ/ЄДР; Google → normal sync")


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.execute("PRAGMA foreign_keys=ON")
        self.c.execute("CREATE TABLE legacy_profile(code TEXT,status TEXT)")
        self.c.execute("INSERT INTO legacy_profile VALUES ('33345054','legacy exact')")
        self.c.commit()
        for file in ("20261005_supplier_evidence_v3.sql","20261006_supplier_evidence_recording_v3.sql"):
            self.c.executescript((ROOT/"migrations"/file).read_text(encoding="utf-8"))

    def tearDown(self):
        self.c.close()

    def count(self, table):
        return self.c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def observe(self, gaps, source_id="old-row", code="33345054"):
        return r.observe_gap(self.c,environment="sandbox",supplier_code=code,
            source_system="legacy",source_object="profile",source_id=source_id,
            observed_at=STAMP,payload={"status":"Неактуально"},gaps=gaps)

    def gap_ids(self):
        return dict(self.c.execute("SELECT gap_type,gap_id FROM supplier_evidence_gaps_v3"))

    def test_schema_additive_empty_and_repeatable(self):
        self.assertEqual(self.c.execute("SELECT * FROM legacy_profile").fetchall(),[("33345054","legacy exact")])
        for table in ("supplier_evidence_events_v3","supplier_evidence_current_v3",
                      "supplier_inclusion_history_v3","supplier_evidence_observations_v3"):
            self.assertEqual(self.count(table),0)
        self.c.executescript((ROOT/"migrations/20261006_supplier_evidence_recording_v3.sql").read_text())
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)

    def test_exact_replay_ignores_receipt_time(self):
        self.assertTrue(r.append_event(self.c,**check()))
        self.assertFalse(r.append_event(self.c,**check(recorded_at="2026-10-06T13:00:00+03:00")))
        self.assertEqual(self.count("supplier_evidence_events_v3"),1)

    def test_conflicting_identity_never_overwrites(self):
        r.append_event(self.c,**check())
        with self.assertRaises(r.SourceIdentityConflict):
            r.append_event(self.c,**check(snapshot={"edr_status":"Припинено"}))
        self.assertEqual(self.count("supplier_evidence_events_v3"),1)

    def test_unchanged_facts_distinct_checks_same_day(self):
        r.append_event(self.c,**check())
        r.append_event(self.c,**check("check-2",source_event_at="2026-10-05T11:00:00+03:00"))
        p = r.update_projection(self.c,**context())
        self.assertEqual(len(p["verification_history"]),2)
        self.assertEqual(p["last_verification_event"]["provenance"]["external_source_event_id"],"check-2")

    def test_admission_three_same_day_exact_source_identities(self):
        stamps = [("e3edb5e958144b61b9d3320d23d2a120","17:04:21.589075"),
                  ("c1939b79afce43cfbef0eadf3a0566ff","15:59:34.798180"),
                  ("d27925ea7ed24af7bb4c1ec5deff4eb0","17:19:52.579134")]
        for source_id,time in stamps:
            stamp = "2026-09-18T"+time+"+03:00"
            e = check(source_id,code="2077003493",kind="admission",effective_date="2026-09-18",
                source_event_at=stamp,provenance={"submission_id":source_id,
                "qualification_id":"q-"+source_id,"submission_date_published":stamp})
            self.assertTrue(r.append_event(self.c,**e))
            self.assertFalse(r.append_event(self.c,**e))
        p = r.update_projection(self.c,**context("2077003493"))
        self.assertEqual(len(p["verification_history"]),3)
        self.assertEqual(p["current_event"]["provenance"]["submission_id"],stamps[-1][0])
        self.assertEqual(p["visible_date"],"2026-09-18")

    def test_admission_requires_full_submission_time_and_qualification(self):
        for prov in ({}, {"submission_id":"s","qualification_id":"q","submission_date_published":"2026-10-05"}):
            with self.assertRaises(ValueError):
                r.append_event(self.c,**check(kind="admission",provenance=prov))

    def test_rejection_not_verification_never_admitted_date_blank(self):
        e = check(kind="rejection",snapshot={},provenance={"submission_id":"s","qualification_id":"q",
            "submission_date_published":"2026-10-04T12:00:00+03:00","outcome":"reject",
            "ever_admitted":False,"supplier_level":True})
        r.append_event(self.c,**e)
        p = r.update_projection(self.c,**context(inclusions=[],last_application={"id":"s","date_published":"2026-10-04T12:00:00+03:00"}))
        self.assertEqual(p["prozorro_status"],"Ще не в реєстрі")
        self.assertEqual(p["edr_status_current"],"Неактуально")
        self.assertIsNone(p["visible_date"])
        self.assertEqual(p["verification_history"],[])

    def test_kinds_on_same_source_object_do_not_collide(self):
        for kind in ("suspension","resumption"):
            e = transition(kind)
            e["source_event_id"] = "same-object-revision"
            r.append_event(self.c,**e)
        self.assertEqual(self.count("supplier_evidence_events_v3"),2)

    def test_missing_source_time_records_gap_not_event(self):
        with self.assertRaises(ValueError):
            r.append_event(self.c,**transition(source_event_at=None))
        self.observe([gap("suspension_date_unproven","history_only","provenance_review")])
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)
        self.assertEqual(r.manual_review_dataset(self.c,environment="sandbox")["rows"],[])
        # Explicit historical gap does not block a new complete event.
        self.assertTrue(r.append_event(self.c,**check()))

    def test_lifecycle_does_not_change_verification_or_freshness(self):
        r.append_event(self.c,**check(effective_date="2026-09-17",source_event_at="2026-09-17T12:00:00+03:00"))
        r.append_event(self.c,**transition())
        p = r.update_projection(self.c,**context(inclusions=[{"state":"suspended"}]))
        self.assertEqual(p["visible_date"],"2026-10-05")
        self.assertEqual(p["visible_actor"],"ЕСЗ")
        self.assertEqual(p["last_verification_date"],"2026-09-17")
        self.assertEqual(p["freshness"]["age_days"],19)

    def test_manual_exclusion_requires_last_inclusion_proof(self):
        e = transition("exclusion")
        e["provenance"]["effective_active_after"] = 1
        with self.assertRaises(ValueError):
            r.append_event(self.c,**e)
        r.append_event(self.c,**transition("exclusion"))
        p = r.update_projection(self.c,**context(inclusions=[],ever_admitted=True))
        self.assertEqual(p["prozorro_status"],"Неактивний")
        self.assertEqual(p["visible_actor"],OFFICER["actor_display"])

    def test_date_only_expiry_from_proven_boundary(self):
        r.append_event(self.c,**transition("expiry",source_event_at=None))
        p = r.update_projection(self.c,**context(inclusions=[],ever_admitted=True))
        self.assertEqual(p["visible_actor"],"ЕСЗ")
        self.assertEqual(p["last_verification_date"],None)

    def test_no_unknown_actor_or_system_verification(self):
        for actor in ({},SYSTEM,{"actor_type":"officer","actor_display":""},
                      {"actor_type":"officer","actor_display":"ЕСЗ"}):
            with self.assertRaises(ValueError):
                r.append_event(self.c,**check(actor=actor))

    def test_prod_rejects_sandbox_attribution(self):
        for actor in ({"actor_type":"officer","actor_display":"Тестова УО SANDBOX"},
                      {"actor_type":"officer","actor_display":" Тестова УО sandbox "},
                      dict(OFFICER,officer_id="sandbox.officer"),dict(OFFICER,officer_source="sandbox_fallback")):
            with self.assertRaises(ValueError):
                r.append_event(self.c,**check(environment="prod",actor=actor))
        self.assertTrue(r.append_event(self.c,**check(environment="prod")))

    def test_timestamp_and_date_validation(self):
        for updates in ({"recorded_at":"2026-10-06"},{"source_event_at":"2026-10-05T12:00:00"},
                        {"source_event_at":"2026-10-04T12:00:00+03:00"},{"effective_date":"bad"}):
            with self.assertRaises(ValueError):
                r.append_event(self.c,**check(**updates))

    def test_atomic_append_projection_failure(self):
        self.c.execute("INSERT INTO legacy_profile VALUES ('other','keep')")
        with self.assertRaises(ValueError):
            r.append_and_project(self.c,event=check(),projection_context=context(inclusions=[{"state":"invalid"}]))
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)
        self.assertEqual(self.count("supplier_evidence_current_v3"),0)
        self.assertEqual(self.count("legacy_profile"),2)

    def test_success_never_commits_caller_transaction(self):
        r.append_and_project(self.c,event=check(),projection_context=context())
        self.assertTrue(self.c.in_transaction)
        self.c.rollback()
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)
        self.assertEqual(self.count("supplier_evidence_current_v3"),0)

    def test_atomic_with_autocommit_connection(self):
        self.c.isolation_level = None
        r.append_event(self.c,**check())
        self.assertTrue(self.c.in_transaction)
        self.c.rollback()
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)

    def test_partial_termination_only_inclusion_history(self):
        r.append_inclusion(self.c,**inclusion(inclusion_id="i-1"))
        r.append_inclusion(self.c,**inclusion("inc-2",inclusion_id="i-2"))
        terminated = inclusion("term-1",kind="termination",source_event_at="2026-10-05T11:00:00+03:00")
        r.append_inclusion(self.c,**terminated)
        self.assertFalse(r.append_inclusion(self.c,**terminated))
        states = r.inclusion_states(self.c,environment="sandbox",supplier_code="33345054",as_of="2026-10-06")
        self.assertTrue(states["complete"])
        p = r.update_projection(self.c,**context(inclusions=states["inclusions"]))
        self.assertEqual(p["prozorro_status"],"Активний")
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)

    def test_inclusion_conflict_and_unknown_attribution(self):
        r.append_inclusion(self.c,**inclusion())
        with self.assertRaises(r.SourceIdentityConflict):
            r.append_inclusion(self.c,**inclusion(source_event_at="2026-10-05T11:00:00+03:00"))
        e = inclusion(kind="termination")
        e["provenance"]["automatic_manual"] = "unknown"
        with self.assertRaises(ValueError):
            r.append_inclusion(self.c,**e)

    def test_inclusion_tie_is_ambiguity_not_id_wins(self):
        r.append_inclusion(self.c,**inclusion())
        r.append_inclusion(self.c,**inclusion("second",kind="termination"))
        result = r.inclusion_states(self.c,environment="sandbox",supplier_code="33345054",as_of="2026-10-06")
        self.assertFalse(result["complete"])
        self.assertEqual(result["gaps"][0]["gap_type"],"ambiguous_same_timestamp")

    def test_manual_inclusion_decision_officer(self):
        e = inclusion(kind="termination",actor=OFFICER)
        e["provenance"]["automatic_manual"] = "manual"
        self.assertTrue(r.append_inclusion(self.c,**e))

    def test_one_supplier_all_active_gaps_unknowns_blank(self):
        self.observe([gap(),gap("missing_attribution",remediation="provenance_review"),
                      gap("termination_date_unproven","history_only","provenance_review")])
        r.append_and_project(self.c,event=check(),projection_context=context())
        ds = r.manual_review_dataset(self.c,environment="sandbox",supplier_names={"33345054":"Supplier"})
        self.assertEqual(len(ds["rows"]),1)
        row = ds["rows"][0]
        self.assertEqual(len(row["gaps"]),2)
        self.assertEqual(row["known_event_dates"],["",""])
        self.assertTrue(all(x["actor"]=="" for x in row["known_actors_sources"]))
        self.assertEqual(row["supplier_name"],"Supplier")
        self.assertEqual(row["last_verification_date"],"2026-10-05")

    def test_verification_does_not_automatically_clear_queue(self):
        self.observe([gap()])
        r.append_event(self.c,**check())
        self.assertEqual(len(r.manual_review_dataset(self.c,environment="sandbox")["rows"]),1)

    def test_only_assessed_factual_gaps_closed(self):
        self.observe([gap(),gap("missing_attribution",remediation="provenance_review")])
        r.append_event(self.c,**check())
        event_id = r.prepare_event(**check())["event_id"]
        r.reassess_verification_gaps(self.c,environment="sandbox",supplier_code="33345054",event_id=event_id,
            assessed_at=STAMP,assessments={self.gap_ids()["stale_factual_state"]:{"closed":True,"reason":"Current factual evidence confirmed"}})
        row = r.manual_review_dataset(self.c,environment="sandbox")["rows"][0]
        self.assertEqual(row["gap_types"],["missing_attribution"])

    def test_successful_review_removes_supplier_only_without_other_gaps(self):
        self.observe([gap()])
        r.append_event(self.c,**check())
        args = dict(environment="sandbox",supplier_code="33345054",event_id=r.prepare_event(**check())["event_id"],
                    assessed_at=STAMP,assessments={self.gap_ids()["stale_factual_state"]:{"closed":True,"reason":"Confirmed"}})
        r.reassess_verification_gaps(self.c,**args)
        r.reassess_verification_gaps(self.c,**args)
        self.assertEqual(r.manual_review_dataset(self.c,environment="sandbox")["rows"],[])
        self.assertEqual(self.count("supplier_evidence_gaps_v3"),1)

    def test_verification_cannot_close_legacy_provenance(self):
        self.observe([gap("termination_date_unproven",remediation="provenance_review")])
        r.append_event(self.c,**check())
        with self.assertRaises(ValueError):
            r.reassess_verification_gaps(self.c,environment="sandbox",supplier_code="33345054",
                event_id=r.prepare_event(**check())["event_id"],assessed_at=STAMP,
                assessments={self.gap_ids()["termination_date_unproven"]:{"closed":True,"reason":"New EDR check"}})

    def test_reviewed_legacy_gap_history_only_without_fabricated_event(self):
        self.observe([gap("termination_date_unproven",remediation="provenance_review")])
        r.archive_legacy_gap(self.c,environment="sandbox",supplier_code="33345054",
            gap_id=self.gap_ids()["termination_date_unproven"],assessed_at=STAMP,
            assessment={"reason":"Historical timestamp unavailable; current state safe",
                        "reviewed_by":OFFICER["actor_display"],"source_reference":"review-1",
                        "current_manual_action_required":False})
        self.assertEqual(r.manual_review_dataset(self.c,environment="sandbox")["rows"],[])
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)
        self.assertEqual(self.count("supplier_evidence_gaps_v3"),1)

    def test_gap_replay_conflict_and_scope_validation(self):
        self.observe([gap()])
        self.observe([gap()])
        with self.assertRaises(r.SourceIdentityConflict):
            self.observe([gap("different")])
        with self.assertRaises(ValueError):
            self.observe([gap(scope="guessed")],source_id="new")

    def test_older_verification_cannot_close_newer_gap(self):
        g = gap()
        g["known_event_date"] = "2026-10-06"
        self.observe([g])
        r.append_event(self.c,**check())
        with self.assertRaises(ValueError):
            r.reassess_verification_gaps(self.c,environment="sandbox",supplier_code="33345054",
                event_id=r.prepare_event(**check())["event_id"],assessed_at=STAMP,
                assessments={self.gap_ids()["stale_factual_state"]:{"closed":True,"reason":"Confirmed"}})

    def test_environment_isolation_and_targeted_reads(self):
        r.append_event(self.c,**check())
        r.append_event(self.c,**check(code="other"))
        r.append_event(self.c,**check(environment="prod"))
        traced = []
        self.c.set_trace_callback(traced.append)
        p = r.update_projection(self.c,**context())
        self.assertEqual(len(p["verification_history"]),1)
        self.assertTrue(all("environment='sandbox'" in sql and "supplier_code='33345054'" in sql
            for sql in traced if "SELECT" in sql and "supplier_evidence_events_v3" in sql))

    def test_readonly_dataset_keyset_export_formula_safe(self):
        for code in ("001","002"):
            self.observe([gap()],code=code)
        self.c.commit()
        self.c.execute("PRAGMA query_only=ON")
        traced=[]
        self.c.set_trace_callback(traced.append)
        page = r.manual_review_dataset(self.c,environment="sandbox",limit=1,supplier_names={"001":"=BAD()"})
        self.assertEqual(page["rows"][0]["supplier_code"],"001")
        second = r.manual_review_dataset(self.c,environment="sandbox",after_code=page["next_after_code"],limit=1)
        self.assertEqual(second["rows"][0]["supplier_code"],"002")
        cells=list(csv.reader(io.StringIO(r.manual_review_csv(page))))
        self.assertEqual(cells[1][1],"'=BAD()")
        self.assertFalse(any(sql.lstrip().startswith(("INSERT","UPDATE","DELETE","BEGIN","SAVEPOINT")) for sql in traced))

    def test_history_gap_cannot_be_mislabeled_factual(self):
        with self.assertRaises(ValueError):
            self.observe([gap("termination_date_unproven")])
        self.assertEqual(self.count("supplier_evidence_observations_v3"),0)

    def test_same_timestamp_verifications_explicit_ambiguity(self):
        r.append_event(self.c,**check("z"))
        r.append_event(self.c,**check("a"))
        p = r.update_projection(self.c,**context())
        self.assertIsNone(p["current_event"])
        self.assertIn("verification:ambiguous_same_timestamp",p["gaps"])

    def test_out_of_order_verification_never_downgrades(self):
        r.append_event(self.c,**check("new",snapshot={"edr_status":"Припинено"}))
        r.append_event(self.c,**check("old",effective_date="2026-09-17",source_event_at="2026-09-17T12:00:00+03:00"))
        p = r.update_projection(self.c,**context())
        self.assertEqual(p["edr_status_current"],"Припинено")
        self.assertEqual(p["last_verification_date"],"2026-10-05")

    def test_context_cross_supplier_rolls_back(self):
        with self.assertRaises(ValueError):
            r.append_and_project(self.c,event=check(),projection_context=context(inclusions=[{"supplier_code":"other","state":"active"}]))
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)

    def test_all_gap_assessments_rollback_if_any_invalid(self):
        self.observe([gap(),gap("termination_date_unproven",remediation="provenance_review")])
        r.append_event(self.c,**check())
        with self.assertRaises(ValueError):
            r.reassess_verification_gaps(self.c,environment="sandbox",supplier_code="33345054",
                event_id=r.prepare_event(**check())["event_id"],assessed_at=STAMP,
                assessments={value:{"closed":True,"reason":"Checked"} for value in self.gap_ids().values()})
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"),0)

    def test_sqlite_row_factory_and_archiving_replay(self):
        self.c.row_factory = sqlite3.Row
        self.assertTrue(r.append_event(self.c,**check()))
        self.assertFalse(r.append_event(self.c,**check()))
        self.observe([gap("termination_date_unproven",remediation="provenance_review")])
        args = dict(environment="sandbox",supplier_code="33345054",
            gap_id=self.gap_ids()["termination_date_unproven"],assessed_at=STAMP,
            assessment={"reason":"No current action needed","reviewed_by":"Officer",
                        "source_reference":"review-1","current_manual_action_required":False})
        self.assertTrue(r.archive_legacy_gap(self.c,**args))
        self.assertFalse(r.archive_legacy_gap(self.c,**args))

    def test_no_runtime_or_migration_wiring(self):
        self.assertNotIn("supplier_evidence_recording_v3",(ROOT/"server.py").read_text(encoding="utf-8"))
        self.assertNotIn("20261006_supplier_evidence_recording_v3",(ROOT/"server.py").read_text(encoding="utf-8"))
        self.assertNotIn("supplier_evidence_recording_v3",(ROOT/"edr_sync_v2.py").read_text(encoding="utf-8"))

    def test_concurrent_replay_single_event_on_disposable_db(self):
        with tempfile.TemporaryDirectory(prefix="pqm-recording-test-") as folder:
            path = str(Path(folder)/"synthetic.sqlite3")
            setup = sqlite3.connect(path)
            for file in ("20261005_supplier_evidence_v3.sql","20261006_supplier_evidence_recording_v3.sql"):
                setup.executescript((ROOT/"migrations"/file).read_text(encoding="utf-8"))
            setup.close()
            def replay(_):
                con = sqlite3.connect(path,timeout=10)
                try:
                    inserted = r.append_event(con,**check())
                    con.commit()
                    return inserted
                finally:
                    con.close()
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(replay,range(8)))
            self.assertEqual(sum(results),1)
            con = sqlite3.connect(path)
            try:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_evidence_events_v3").fetchone()[0],1)
            finally:
                con.close()

    def test_inclusion_and_supplier_event_share_outer_transaction(self):
        with self.assertRaises(ValueError):
            with r.atomic(self.c):
                r.append_inclusion(self.c,**inclusion(kind="termination"))
                r.append_and_project(self.c,event=transition("exclusion"),
                    projection_context=context(inclusions=[{"state":"invalid"}]))
        self.assertEqual(self.count("supplier_inclusion_history_v3"),0)
        self.assertEqual(self.count("supplier_evidence_events_v3"),0)

    def test_reserved_actor_provenance_rejected(self):
        with self.assertRaises(ValueError):
            r.append_event(self.c,**check(provenance={"_recording_actor":SYSTEM}))

    def test_manual_review_environment_no_cross_contamination(self):
        self.observe([gap()])
        self.assertEqual(r.manual_review_dataset(self.c,environment="prod")["rows"],[])

    def test_cache_does_not_duplicate_full_history(self):
        r.append_and_project(self.c,event=check(),projection_context=context())
        payload=json.loads(self.c.execute("SELECT projection_json FROM supplier_evidence_current_v3").fetchone()[0])
        self.assertNotIn("verification_history",payload)
        self.assertIsNotNone(payload["last_verification_event"])

    def test_null_unknown_date_actor_export_as_blank(self):
        g = gap()
        g.update(known_event_date=None,known_actor=None)
        self.observe([g])
        row=r.manual_review_dataset(self.c,environment="sandbox")["rows"][0]
        self.assertEqual(row["known_event_dates"],[""])
        self.assertEqual(row["known_actors_sources"][0]["actor"],"")

    def test_existing_stage1_row_read_without_provenance_rewrite(self):
        r.append_event(self.c,**check())
        # Synthetic pre-recorder Stage 1 row: actor columns, no recorder metadata.
        self.c.execute("UPDATE supplier_evidence_events_v3 SET provenance_json='{}'")
        before=self.c.execute("SELECT * FROM supplier_evidence_events_v3").fetchall()
        p=r.update_projection(self.c,**context())
        self.assertEqual(p["last_verification_officer"],OFFICER["actor_display"])
        self.assertEqual(self.c.execute("SELECT * FROM supplier_evidence_events_v3").fetchall(),before)

    def test_canonical_sandbox_new_check_remains_normal_verification(self):
        actor={"actor_type":"officer","actor_display":"Тестова УО SANDBOX", "officer_id":"sandbox.officer"}
        r.append_and_project(self.c,event=check(actor=actor),projection_context=context())
        p=r.update_projection(self.c,**context())
        self.assertEqual(p["last_verification_officer"],"Тестова УО SANDBOX")
        self.assertEqual(p["last_verification_event"]["actor"]["officer_id"],"sandbox.officer")


if __name__ == "__main__":
    unittest.main()
