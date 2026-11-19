"""Contract-v3 synthetic fixtures. Pure resolver + disposable in-memory DDL only."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import unittest

import supplier_evidence_v3 as v3

OFFICER = {"actor_type": "officer", "actor_display": "Світлана НАМЯСЕНКО"}
SYSTEM = {"actor_type": "system", "actor_display": "ЕСЗ"}


def event(kind="edr_check", day="2026-09-17", identity="check-1", code="33345054",
          actor=None, status="Зареєстровано", **kwargs):
    return v3.make_event(supplier_code=code, kind=kind, effective_date=day,
        actor=actor or (SYSTEM if kind in {"suspension", "resumption", "expiry"} else OFFICER),
        source_system="fixture", source_event_id=identity,
        snapshot={"edr_status": status, "manager_name": "manager"}, **kwargs)


def project(events=(), states=("active",), **kwargs):
    return v3.resolve(supplier_code="33345054", events=list(events),
        inclusions=[{"state": s} for s in states], as_of="2026-10-05", **kwargs)


class EvidenceV3Tests(unittest.TestCase):
    def test_admission_uses_submission_date_not_protocol_or_qualification(self):
        controls = [("2077003493", "2026-09-18", "Тетяна ФЕДЧЕНКО"),
                    ("2886810864", "2026-09-16", "Дмитро САВВА"),
                    ("2981518432", "2026-09-22", "Дмитро САВВА")]
        for code, day, officer in controls:
            with self.subTest(code=code):
                e = v3.admission_event(submission={"id": code, "supplier_code": code,
                    "decision": "admit", "date_published": day + "T10:00:00+03:00",
                    "protocol_date": "2026-09-30", "qualification_decision_date": "2026-09-30"},
                    actor=v3.attribution(provenance_kind="admission", officer=officer))
                self.assertEqual(e["effective_date"], day)
                self.assertEqual(e["actor"]["actor_display"], officer)
                self.assertEqual(e["snapshot"]["edr_status"], "Зареєстровано")

    def test_repeated_admission_creates_new_verification(self):
        a, b = event("admission", identity="application-1"), event("admission", "2026-10-01", "application-2")
        p = project([a, b])
        self.assertEqual(len(p["verification_history"]), 2)
        self.assertEqual(p["last_verification_date"], "2026-10-01")

    def test_unchanged_facts_new_check_and_replay(self):
        a, b = event(), event(day="2026-10-05", identity="check-2")
        p = project([a, b, deepcopy(b)])
        self.assertEqual(a["snapshot"], b["snapshot"])
        self.assertNotEqual(a["event_id"], b["event_id"])
        self.assertEqual(len(p["verification_history"]), 2)
        self.assertEqual(p["last_verification_event"]["event_id"], b["event_id"])

    def test_same_day_checks_use_exact_timestamp(self):
        a = event(source_event_at="2026-09-17T10:00:00+03:00")
        b = event(identity="check-2", source_event_at="2026-09-17T11:00:00+03:00")
        self.assertEqual(project([b, a])["current_event"]["event_id"], b["event_id"])
        self.assertEqual(len(project([a, b])["verification_history"]), 2)

    def test_same_day_without_proven_order_is_explicit_gap(self):
        p = project([event(), event(identity="different")])
        self.assertIsNone(p["current_event"])
        self.assertIn("verification:ambiguous_same_day_events", p["gaps"])

    def test_identity_conflict_is_not_latest_id_wins(self):
        a = event()
        b = deepcopy(a)
        b["snapshot"]["manager_name"] = "changed"
        self.assertIn("conflicting_source_event_identity", project([a,b])["gaps"])

    def test_reobservation_timestamp_does_not_create_event(self):
        a = event()
        b = deepcopy(a)
        b["recorded_at"] = "2026-10-05T10:00:00+03:00"
        p = project([a,b])
        self.assertEqual(p["gaps"], [])
        self.assertEqual(len(p["verification_history"]), 1)

    def test_same_timestamp_ambiguity_not_resolved_by_hash(self):
        a = event(source_event_at="2026-09-17T10:00:00+03:00")
        b = event(identity="another",source_event_at="2026-09-17T10:00:00+03:00")
        self.assertIn("verification:ambiguous_same_timestamp",project([a,b])["gaps"])

    def test_future_events_do_not_become_current(self):
        future = event(day="2026-10-06", identity="future")
        self.assertEqual(len(project([event(),future])["verification_history"]),1)

    def test_newer_verification_after_resumption_becomes_visible(self):
        b = event("resumption","2026-10-01","resume",provenance={"supplier_level":True})
        c = event(day="2026-10-05", identity="new-check")
        p = project([event(),b,c])
        self.assertEqual(p["visible_actor"],OFFICER["actor_display"])
        self.assertEqual(p["current_event"]["event_id"],c["event_id"])

    def test_33345054_exclusion_preserves_8627_history(self):
        a = event(identity="legacy-8627")
        b = event("exclusion", "2026-10-05", "protocol-755",
            actor=v3.attribution(provenance_kind="exclusion", environment="sandbox",
                canonical_sandbox_officer=v3.SANDBOX_OFFICER),
            provenance={"supplier_level": True, "protocol_number": "755"})
        p = project([a,b], states=("inactive",), ever_admitted=True)
        self.assertEqual(p["edr_status_current"], "Неактуально")
        self.assertEqual(p["visible_date"], "2026-10-05")
        self.assertEqual(p["visible_actor"], v3.SANDBOX_OFFICER)
        self.assertEqual(p["last_verification_date"], "2026-09-17")
        self.assertEqual(p["last_verification_officer"], "Світлана НАМЯСЕНКО")
        self.assertEqual(len(p["verification_history"]), 1)

    def test_suspension_and_resumption_visible_event_not_freshness_base(self):
        a = event(day="2026-07-01")
        for kind, state in [("suspension", "suspended"), ("resumption", "active")]:
            with self.subTest(kind=kind):
                b = event(kind, "2026-10-05", kind, provenance={"supplier_level": True})
                p = project([a,b], states=(state,))
                self.assertTrue(p["monitoring_eligible"])
                self.assertEqual(p["edr_status_current"], "Зареєстровано")
                self.assertEqual(p["visible_actor"], "ЕСЗ")
                self.assertEqual(p["visible_date"], "2026-10-05")
                self.assertEqual(p["last_verification_date"], "2026-07-01")
                self.assertEqual(p["freshness"]["bucket"], "gt90")

    def test_one_remaining_active_inclusion_prevents_inactive(self):
        b = event("exclusion", "2026-10-05", "one-contract",
                  provenance={"supplier_level": False})
        p = project([event(),b], states=("active","inactive"))
        self.assertEqual(p["prozorro_status"], "Активний")
        self.assertEqual(p["edr_status_current"], "Зареєстровано")
        self.assertEqual(p["visible_date"], "2026-09-17")

    def test_active_inclusion_wins_over_suspended(self):
        self.assertEqual(project([event()], states=("active","suspended"))["prozorro_status"], "Активний")

    def test_expiry_actor_is_system(self):
        b = event("expiry", "2026-10-05", "expiry", provenance={"supplier_level":True})
        p = project([event(),b], states=("inactive",), ever_admitted=True)
        self.assertEqual(p["visible_actor"], "ЕСЗ")
        self.assertEqual(p["edr_status_current"], "Неактуально")

    def test_never_admitted_one_or_ten_rejections_date_blank(self):
        for count in (1,10):
            rejected = [event("rejection", "2026-09-%02d" % (i+1), str(i),
                              provenance={"supplier_level":True}) for i in range(count)]
            p = project(rejected, states=())
            self.assertEqual(p["prozorro_status"], "Ще не в реєстрі")
            self.assertIsNone(p["visible_date"])
            self.assertEqual(p["visible_actor"], OFFICER["actor_display"])
            self.assertIsNone(p["last_verification_date"])
            self.assertEqual(p["verification_history"], [])
            self.assertIsNotNone(p["current_event_date"])
            self.assertEqual(p["current_event_type"], "lifecycle")

    def test_rejected_later_application_does_not_replace_verification(self):
        a = event("admission")
        b = event("rejection", "2026-10-05", "rejected", provenance={"supplier_level":True})
        p = project([a,b], last_application={"date":"2026-10-05","decision":"reject"})
        self.assertEqual(p["current_event"]["event_id"], a["event_id"])
        self.assertEqual(p["last_application"]["date"], "2026-10-05")

    def test_ever_admitted_never_returns_to_never_admitted(self):
        p = project([], states=(), ever_admitted=True)
        self.assertEqual(p["prozorro_status"], "Неактивний")
        self.assertIn("missing_lifecycle_evidence", p["gaps"])

    def test_twelve_active_missing_evidence_no_fabricated_pair(self):
        codes = "2077003493 2886810864 2981518432 3385014935 3602006515 3618208369 3624813159 30795712 39984849 41141768 45547692 46120124".split()
        for code in codes:
            p = v3.resolve(supplier_code=code,events=[],inclusions=[{"state":"active"}],as_of="2026-10-05")
            self.assertEqual(p["prozorro_status"], "Активний")
            self.assertNotEqual(p["edr_status_current"], "Неактуально")
            self.assertIsNone(p["last_verification_date"])
            self.assertIn("missing_verification_evidence",p["gaps"])

    def test_nine_newer_checks_preserved_atomically(self):
        for i in range(9):
            newer = event(day="2026-10-05", identity=str(i), status="Припинено")
            p = project([newer,event()])
            self.assertEqual(p["edr_status_current"], "Припинено")
            self.assertEqual(p["factual_snapshot"], newer["snapshot"])
            self.assertEqual(p["visible_date"], "2026-10-05")

    def test_freshness_boundaries(self):
        for day,bucket in [("2026-10-05","lt30"),("2026-09-05","gt30"),
                           ("2026-08-06","gt60"),("2026-07-07","gt90")]:
            self.assertEqual(v3.freshness(monitored=True,verification_date=day,as_of="2026-10-05")["bucket"],bucket)
        self.assertEqual(project()["freshness"]["bucket"],"not_checked")

    def test_attribution_specific_before_fallback_and_prod_unchanged(self):
        self.assertEqual(v3.attribution(provenance_kind="admission",officer="Тетяна ФЕДЧЕНКО",
            environment="sandbox",canonical_sandbox_officer=v3.SANDBOX_OFFICER)["actor_display"],"Тетяна ФЕДЧЕНКО")
        self.assertEqual(v3.attribution(provenance_kind="admission",environment="prod",
            canonical_sandbox_officer=v3.SANDBOX_OFFICER),{"gap":"missing_officer"})

    def test_normalization_requires_provenance_not_blanket_4420(self):
        for kind in ("unknown","edr_check",""):
            self.assertIn("gap",v3.normalization_proposal(observation_id="old",provenance_kind=kind,
                historical_date="2026-07-22",canonical_sandbox_officer=v3.SANDBOX_OFFICER))
        for kind,actor in [("admission",v3.SANDBOX_OFFICER),("exclusion",v3.SANDBOX_OFFICER),("expiry","ЕСЗ")]:
            p=v3.normalization_proposal(observation_id="old",provenance_kind=kind,
                historical_date="2026-07-22",canonical_sandbox_officer=v3.SANDBOX_OFFICER)
            self.assertFalse(p["creates_verification_event"])
            self.assertEqual(p["effective_date"],"2026-07-22")
            self.assertEqual(p["actor"]["actor_display"],actor)

    def test_no_mutation_of_inputs(self):
        events=[event()]; before=deepcopy(events)
        p=project(events); p["factual_snapshot"]["manager_name"]="changed"
        self.assertEqual(events,before)

    def test_invalid_evidence_is_rejected(self):
        for kwargs in ({"actor":{"gap":"missing_officer"}}, {"effective_date":"bad"},
                       {"source_event_at":"2026-09-17T10:00:00"},
                       {"snapshot":{"edr_status":"Неактуально"}}):
            defaults=dict(supplier_code="x",kind="edr_check",effective_date="2026-09-17",
                actor=OFFICER,source_system="fixture",source_event_id="id",snapshot={"edr_status":"Зареєстровано"})
            defaults.update(kwargs)
            with self.assertRaises(ValueError):v3.make_event(**defaults)

    def test_ddl_is_additive_idempotent_and_no_backfill(self):
        con=sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE supplier_edr_profiles(code TEXT,status TEXT); INSERT INTO supplier_edr_profiles VALUES('old','Неактуально'); CREATE TABLE supplier_edr_verification_events(id INTEGER); INSERT INTO supplier_edr_verification_events VALUES(8627);")
        ddl=(Path(v3.__file__).parent / "migrations/20261005_supplier_evidence_v3.sql").read_text(encoding="utf-8")
        con.executescript(ddl);con.executescript(ddl)
        self.assertEqual(con.execute("SELECT * FROM supplier_edr_profiles").fetchall(),[("old","Неактуально")])
        self.assertEqual(con.execute("SELECT * FROM supplier_edr_verification_events").fetchall(),[(8627,)])
        for table in ("supplier_evidence_events_v3","supplier_evidence_projections_v3","supplier_evidence_normalizations_v3"):
            self.assertEqual(con.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0)
        con.close()


if __name__ == "__main__":
    unittest.main()
