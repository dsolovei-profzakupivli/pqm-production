"""Controlled SANDBOX verification import: synthetic, no live DB or Google writes."""
import sqlite3
import unittest
from unittest.mock import patch
import os
import json
import time

import legacy_google_verification_preview as module


def record(code="001", tab="ФОП", row=2, day="2026-09-23", officer="Officer One"):
    return {"supplier_code": code, "source_tab": tab, "source_row": row,
            "verification_date": day, "verification_officer": officer, "source": module.SOURCE}


def source(items):
    items = sorted(items, key=lambda x: (x["source_tab"], x["source_row"], x["supplier_code"]))
    return {"spreadsheet_id": module.SANDBOX_SPREADSHEET_ID,
            "source_digest": module.source_digest(items), "records": items}


class ControlledApplyTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("""CREATE TABLE supplier_edr_verification_events (
          id INTEGER PRIMARY KEY, supplier_code TEXT, event_type TEXT, occurred_at TEXT,
          officer TEXT, source TEXT, source_submission_id TEXT DEFAULT '',
          source_sheet TEXT, source_row INTEGER, changed_fields TEXT, snapshot_hash TEXT,
          snapshot_json TEXT, created_at TEXT,
          UNIQUE(supplier_code,event_type,occurred_at,source,snapshot_hash))""")
        self.con.execute("CREATE TABLE supplier_edr_profiles (supplier_code TEXT,edr_status TEXT,manager TEXT)")
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES ('001','Зареєстровано','manager')")
        self.con.execute("CREATE TABLE qualifications (supplier_code TEXT,status TEXT)")
        self.con.execute("INSERT INTO qualifications VALUES ('001','active')")
        self.con.commit()
        self.registry = {"001": "individual_entrepreneur", "002": "legal_entity"}
        self.days = {"001": "2026-09-22", "002": ""}
        self.p1 = patch.object(module.supplier_registry_integration, "_build_full_registry",
            side_effect=lambda con: {"items": [{"supplier_code": code, "entity_type": kind}
                                              for code, kind in self.registry.items()]})
        self.p2 = patch.object(module.edr_sync_v2, "current_verification_projections",
            side_effect=lambda con, codes: {code: {"verification_date": self.days[code]}
                                            for code in codes if code in self.days})
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p2.stop(); self.p1.stop(); self.con.close()

    def bound(self, items):
        body = source(items)
        result = module.preview(self.con, body)
        body["selection_digest"] = result["selection_digest"]
        body["preview_ticket"] = result["preview_ticket"]
        body["confirmation"] = module.APPLY_CONFIRMATION
        return body

    def count(self):
        return self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0]

    def test_newer_initial_atomic_insert_and_replay(self):
        body = self.bound([record(), record("002", "ЮО", 2, officer="Officer Two")])
        self.assertEqual(module.apply(self.con, body)["verified"], 2)
        self.assertEqual(self.count(), 2)
        event = self.con.execute("SELECT event_type,source,occurred_at,officer,source_sheet,"
                                 "source_row,snapshot_json FROM supplier_edr_verification_events "
                                 "WHERE supplier_code='001'").fetchone()
        self.assertEqual(tuple(event)[:6], (module.SOURCE, module.SOURCE, "2026-09-23",
                                            "Officer One", "ФОП", 2))
        evidence = json.loads(event["snapshot_json"])
        self.assertEqual(evidence["spreadsheet_id"], module.SANDBOX_SPREADSHEET_ID)
        self.assertEqual(evidence["source_digest"], body["source_digest"])
        self.assertEqual(module.apply(self.con, body)["transaction_status"], "ALREADY_APPLIED")
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.con.execute("SELECT edr_status,manager FROM supplier_edr_profiles").fetchone()[:],
                         ("Зареєстровано", "manager"))
        self.assertEqual(self.con.execute("SELECT status FROM qualifications").fetchone()[0], "active")

    def test_max_500_batch_commits_once_and_replay_is_idempotent(self):
        items = [record(str(1000 + index), row=index + 2) for index in range(500)]
        self.registry.update({item["supplier_code"]: "individual_entrepreneur" for item in items})
        self.days.update({item["supplier_code"]: "2026-09-22" for item in items})
        body = self.bound(items)
        before = module.preview(self.con, source(items))
        self.assertEqual((before["received"], before["selected"], before["incoming_newer"]),
                         (500, 500, 500))
        self.assertTrue(before["batch_apply_ready"])
        self.assertEqual(before["ticket_ttl_seconds"], 900)
        result = module.apply(self.con, body)
        self.assertEqual((result["inserted"], result["verified"], result["db_writes"]),
                         (500, 500, 500))
        self.assertEqual(result["google_writes"], 0)
        self.assertEqual(self.count(), 500)
        self.assertEqual(module.apply(self.con, body)["transaction_status"], "ALREADY_APPLIED")
        self.assertEqual(self.count(), 500)
        after = module.preview(self.con, source(items))
        self.assertEqual(after["equivalent_event"], 500)
        self.assertEqual(after["selected"], 0)
        self.assertFalse(after["batch_apply_ready"])

    def test_max_500_batch_rolls_back_every_insert_on_readback_failure(self):
        items = [record(str(2000 + index), row=index + 2) for index in range(500)]
        self.registry.update({item["supplier_code"]: "individual_entrepreneur" for item in items})
        self.days.update({item["supplier_code"]: "2026-09-22" for item in items})
        body = self.bound(items)
        def corrupt_last(con):
            con.execute("UPDATE supplier_edr_verification_events SET officer='corrupt' "
                        "WHERE supplier_code=?", (items[-1]["supplier_code"],))
        with self.assertRaisesRegex(ValueError, "AFTER_VERIFICATION_FAILED"):
            module.apply(self.con, body, after_insert_hook=corrupt_last)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.con.execute("SELECT edr_status,manager FROM supplier_edr_profiles").fetchone()[:],
                         ("Зареєстровано", "manager"))

    def test_preview_binding_is_deterministic_and_read_only(self):
        body = source([record()])
        before = self.con.total_changes
        first = module.preview(self.con, body)
        second = module.preview(self.con, body)
        self.assertEqual(first["selection_digest"], second["selection_digest"])
        self.assertEqual(first["current_pqm_state_digest"], second["current_pqm_state_digest"])
        self.assertEqual(before, self.con.total_changes)
        self.assertEqual(self.count(), 0)
        expired = module._preview_ticket(first["selection_digest"], int(time.time()) - 1)
        self.assertFalse(module._ticket_valid(expired, first["selection_digest"]))

    def test_existing_factual_legacy_pair_is_equivalent_and_unchanged(self):
        factual = {"source": module.SOURCE, "verification_date": "2026-09-23",
                   "verification_officer": "Officer One",
                   "factual_edr_status": "Припинено", "factual_provenance_version": 1}
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,source_sheet,source_row,
           snapshot_hash,snapshot_json) VALUES (?,?,?,?,?,?,?,?,?)""",
          ("001", module.SOURCE, "2026-09-23", "Officer One", module.SOURCE,
           "ФОП", 2, "factual-evidence", json.dumps(factual, ensure_ascii=False)))
        self.con.commit()
        before = self.con.execute("SELECT snapshot_json FROM supplier_edr_verification_events").fetchone()[0]
        result = module.preview(self.con, source([record()]))
        self.assertEqual(result["equivalent_event"], 1)
        self.assertEqual(result["incoming_newer"] + result["initial"], 0)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.con.execute("SELECT snapshot_json FROM supplier_edr_verification_events").fetchone()[0], before)

    def test_mixed_batch_with_factual_equivalent_rolls_back_without_downgrade(self):
        factual = {"source": module.SOURCE, "verification_date": "2026-09-23",
                   "verification_officer": "Officer One", "factual_edr_status": "Припинено",
                   "factual_provenance_version": 1}
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,source_sheet,source_row,
           snapshot_hash,snapshot_json) VALUES (?,?,?,?,?,?,?,?,?)""",
          ("001", module.SOURCE, "2026-09-23", "Officer One", module.SOURCE,
           "ФОП", 2, "factual-evidence", json.dumps(factual, ensure_ascii=False)))
        self.con.commit()
        body = self.bound([record(), record("002", "ЮО", 2, officer="Officer Two")])
        self.assertFalse(module.preview(self.con, source(body["records"]))["batch_apply_ready"])
        with self.assertRaisesRegex(ValueError, "SELECTION_NOT_FULLY_ELIGIBLE"):
            module.apply(self.con, body)
        self.assertEqual(self.count(), 1)
        self.assertEqual(json.loads(self.con.execute(
            "SELECT snapshot_json FROM supplier_edr_verification_events").fetchone()[0]), factual)

    def test_existing_il_only_legacy_pair_is_equivalent(self):
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,source_sheet,source_row,
           snapshot_hash,snapshot_json) VALUES (?,?,?,?,?,?,?,?,?)""",
          ("001", module.SOURCE, "2026-09-23", "Officer One", module.SOURCE,
           "ФОП", 2, "il-evidence", "{}"))
        self.con.commit()
        result = module.preview(self.con, source([record()]))
        self.assertEqual(result["equivalent_event"], 1)
        self.assertEqual(result["incoming_newer"] + result["initial"], 0)
        self.assertEqual(self.count(), 1)

    def test_stale_preview_and_changed_state_zero_writes(self):
        body = self.bound([record()])
        body["selection_digest"] = "bad"
        with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET_INVALID"):
            module.apply(self.con, body)
        body = self.bound([record()])
        self.days["001"] = "2026-09-24"
        with self.assertRaisesRegex(ValueError, "STALE_PREVIEW"):
            module.apply(self.con, body)
        self.assertEqual(self.count(), 0)

    def test_tamper_wrong_sheet_source_confirmation_and_limit(self):
        body = self.bound([record()])
        for key, value, error in (("spreadsheet_id", "wrong", "SANDBOX_SPREADSHEET"),
                                  ("confirmation", "no", "EXPLICIT_CONFIRMATION")):
            changed = dict(body, **{key: value})
            with self.assertRaisesRegex(ValueError, error): module.apply(self.con, changed)
        changed = dict(body); changed["records"] = [dict(record(), verification_officer="Other")]
        with self.assertRaisesRegex(ValueError, "SOURCE_DIGEST_MISMATCH"):
            module.apply(self.con, changed)
        changed = source([record(str(i), row=i+2) for i in range(501)])
        changed.update(selection_digest="x", preview_ticket="x", confirmation=module.APPLY_CONFIRMATION)
        writes_before_limit = self.con.total_changes
        with self.assertRaisesRegex(ValueError, "CONTROLLED_PREVIEW_LIMIT"):
            module.apply(self.con, changed)
        self.assertEqual(self.con.total_changes, writes_before_limit)
        self.assertFalse(self.con.in_transaction)
        changed = self.bound([record()]); changed["records"][0]["source"] = "google_registry"
        changed["source_digest"] = module.source_digest(changed["records"])
        with self.assertRaisesRegex(ValueError, "APPLY_SOURCE_INVALID"):
            module.apply(self.con, changed)
        changed = self.bound([record()]); changed["preview_ticket"] = "forged"
        with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET_INVALID"):
            module.apply(self.con, changed)
        self.assertEqual(self.count(), 0)

    def test_same_older_missing_officer_and_ambiguous_rejected(self):
        for day, officer in (("2026-09-22", "Officer"), ("2026-09-21", "Officer"),
                             ("2026-09-23", "—")):
            with self.assertRaisesRegex(ValueError, "SELECTION_NOT_FULLY_ELIGIBLE"):
                module.apply(self.con, self.bound([record(day=day, officer=officer)]))
        self.registry.pop("001")
        with self.assertRaisesRegex(ValueError, "SELECTION_NOT_FULLY_ELIGIBLE"):
            module.apply(self.con, self.bound([record()]))
        self.assertEqual(self.count(), 0)

    def test_rollback_on_after_failure(self):
        body = self.bound([record(), record("002", "ЮО", 2, officer="Officer Two")])
        def corrupt(con):
            con.execute("UPDATE supplier_edr_verification_events SET officer='corrupt' WHERE supplier_code='002'")
        with self.assertRaisesRegex(ValueError, "AFTER_VERIFICATION_FAILED"):
            module.apply(self.con, body, after_insert_hook=corrupt)
        self.assertEqual(self.count(), 0)

    def test_trigger_side_effect_rolls_back_all(self):
        self.con.execute("""CREATE TRIGGER forbidden_profile_update AFTER INSERT ON
          supplier_edr_verification_events BEGIN UPDATE supplier_edr_profiles
          SET edr_status='changed' WHERE supplier_code=NEW.supplier_code; END""")
        self.con.commit()
        body = self.bound([record()])
        with self.assertRaisesRegex(ValueError, "PROTECTED_STATE_CHANGED|UNEXPECTED_DB_MUTATION"):
            module.apply(self.con, body)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.con.execute("SELECT edr_status FROM supplier_edr_profiles").fetchone()[0],
                         "Зареєстровано")

    def test_apply_route_requires_sandbox_bearer(self):
        import server
        responses = []
        handler = type("Fake", (), {})()
        handler.path = module.APPLY_PATH; handler.command = "POST"
        handler.headers = {"Authorization": "Bearer bad"}
        handler.send_json = lambda data, status=200: responses.append(status)
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(os.environ, {
                "PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN": "secret"}):
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 401)
            handler.headers["Authorization"] = "Bearer secret"
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 200)

    def test_prod_route_unavailable(self):
        import server
        responses = []
        handler = type("Fake", (), {})()
        handler.path = module.APPLY_PATH; handler.command = "POST"
        handler.send_json = lambda data, status=200: responses.append(status)
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: responses.append(200))
        self.assertEqual(responses, [404])


if __name__ == "__main__":
    unittest.main()
