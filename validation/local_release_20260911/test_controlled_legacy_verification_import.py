"""No network or production data; controlled historical verification import."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch


_test_dir = Path(__file__).resolve().parent
SCRIPT = next((root / "scripts" / "controlled_legacy_verification_import.py"
               for root in (_test_dir, *_test_dir.parents)
               if (root / "scripts" / "controlled_legacy_verification_import.py").is_file()), None)
if SCRIPT is None:
    raise FileNotFoundError("controlled_legacy_verification_import.py not found beside release tests")
spec = importlib.util.spec_from_file_location("controlled_legacy_verification_import", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(cases):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE supplier_edr_profiles (supplier_code TEXT, edr_status TEXT, manager_name TEXT)")
    con.execute("""CREATE TABLE supplier_edr_verification_events (
      id INTEGER PRIMARY KEY, supplier_code TEXT, event_type TEXT, occurred_at TEXT,
      officer TEXT, source TEXT, source_sheet TEXT, source_row INTEGER,
      changed_fields TEXT, snapshot_hash TEXT, snapshot_json TEXT, created_at TEXT,
      UNIQUE(supplier_code,event_type,occurred_at,source,snapshot_hash))""")
    tabs = {}
    items = []
    projection = {}
    for tab in module.TABS:
        rows = [list(module.HEADERS)]
        for case in cases:
            if case["tab"] != tab:
                continue
            row = [""] * 17
            row[1], row[8], row[11] = case["code"], case["date"], case["officer"]
            if case.get("formula"):
                row[15] = "=TODAY()"
            rows.append(row)
            items.append({"supplier_code": case["code"], "entity_type":
                "individual_entrepreneur" if tab == "ФОП" else "legal_entity"})
            projection[case["code"]] = {"verification_date": case.get("pqm_date", ""),
                                        "verification_officer_raw": case.get("pqm_officer", "")}
            con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?,?)",
                        (case["code"], "Неактуально", "manager"))
        tabs[tab] = rows
    con.commit()
    return con, tabs, items, projection


class ControlledImportTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            {"code": "001", "tab": "ФОП", "date": "2026-09-22", "officer": "Officer A",
             "pqm_date": "2026-08-01"},
            {"code": "002", "tab": "ЮО", "date": "22.09.2026", "officer": "Officer B",
             "pqm_date": ""},
            {"code": "003", "tab": "ФОП", "date": "2026-09-22", "officer": "Officer C",
             "pqm_date": "2026-09-22"},
            {"code": "004", "tab": "ЮО", "date": "2026-08-01", "officer": "Officer D",
             "pqm_date": "2026-09-22"},
        ]
        self.con, self.tabs, self.items, self.projection = fixture(self.cases)
        self.registry_patch = patch.object(module.supplier_registry_integration,
                                           "_build_full_registry", return_value={"items": self.items})
        def projected(con, codes):
            result = {}
            for code in codes:
                if code not in self.projection:
                    continue
                item = dict(self.projection[code])
                row = con.execute("SELECT occurred_at,officer,source FROM "
                                  "supplier_edr_verification_events WHERE supplier_code=? "
                                  "AND source=? ORDER BY occurred_at DESC LIMIT 1",
                                  (code, module.SOURCE)).fetchone()
                if row and row["occurred_at"] > item["verification_date"]:
                    item.update(verification_date=row["occurred_at"],
                                verification_officer_raw=row["officer"],
                                selected_event={"source": row["source"]})
                result[code] = item
            return result
        self.projection_patch = patch.object(module.edr_sync_v2, "current_verification_projections",
                                             side_effect=projected)
        self.registry_patch.start()
        self.projection_patch.start()
        self.db_patch = patch.object(module, "SANDBOX_DB", "")  # sqlite :memory: main path
        self.db_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        self.projection_patch.stop()
        self.db_patch.stop()
        self.con.close()

    def test_newer_initial_and_exclusions(self):
        result, selected = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual((result["candidate_newer"], result["candidate_initial"]), (1, 1))
        self.assertEqual((result["same_date_excluded"], result["google_older_excluded"]), (1, 1))
        self.assertEqual({x["code"] for x in selected}, {"001", "002"})
        self.assertEqual(result["db_writes"], 0)

    def test_wrong_sheet_and_formula_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "SANDBOX_SPREADSHEET_MISMATCH"):
            module.build_preview(self.con, "wrong", self.tabs)
        self.tabs["ФОП"][1][15] = "=TODAY()"
        result, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(result["candidate_newer"], 0)
        self.assertEqual(result["invalid_or_ambiguous"]["formula_date_or_officer"], 1)

    def test_equivalent_event_and_duplicate_identity(self):
        self.con.execute("INSERT INTO supplier_edr_verification_events "
                         "(supplier_code,event_type,occurred_at,officer,source,snapshot_hash) "
                         "VALUES ('001','manual_edr','2026-09-22','officer a','x','y')")
        result, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(result["already_imported_or_equivalent"], 1)
        self.tabs["ФОП"].append(self.tabs["ФОП"][1][:])
        result, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertGreater(result["invalid_or_ambiguous"]["ambiguous_identity"], 0)

    def test_preview_determinism_and_staleness(self):
        first, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        second, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(first["preview_digest"], second["preview_digest"])
        self.tabs["ФОП"][1][8] = "2026-09-23"
        changed, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertNotEqual(first["preview_digest"], changed["preview_digest"])

    def test_apply_pair_profile_unchanged_and_idempotent_preview(self):
        first, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        source = lambda: (module.SANDBOX_SHEET_ID, self.tabs)
        result = module.apply_controlled(self.con, source, first["preview_digest"], module.CONFIRMATION)
        self.assertEqual(result, {"inserted": 2, "verified": 2})
        rows = self.con.execute("SELECT occurred_at,officer,source FROM supplier_edr_verification_events "
                                "ORDER BY supplier_code").fetchall()
        self.assertEqual([tuple(x) for x in rows], [
            ("2026-09-22", "Officer A", module.SOURCE),
            ("2026-09-22", "Officer B", module.SOURCE)])
        self.assertEqual(self.con.execute("SELECT DISTINCT edr_status,manager_name "
                                          "FROM supplier_edr_profiles").fetchone()[:],
                         ("Неактуально", "manager"))
        after, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(after["planned_inserts"], 0)
        with self.assertRaisesRegex(ValueError, "STALE_PREVIEW"):
            module.apply_controlled(self.con, source, first["preview_digest"], module.CONFIRMATION)

    def test_stale_google_and_pqm_before_write(self):
        first, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.tabs["ФОП"][1][11] = "Changed officer"
        with self.assertRaisesRegex(ValueError, "STALE_PREVIEW"):
            module.apply_controlled(self.con, lambda: (module.SANDBOX_SHEET_ID, self.tabs),
                                    first["preview_digest"], module.CONFIRMATION)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)
        self.tabs["ФОП"][1][11] = "Officer A"
        self.projection["001"]["verification_date"] = "2026-09-23"
        with self.assertRaisesRegex(ValueError, "STALE_PREVIEW"):
            module.apply_controlled(self.con, lambda: (module.SANDBOX_SHEET_ID, self.tabs),
                                    first["preview_digest"], module.CONFIRMATION)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_transaction_rollback_after_failure(self):
        first, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        calls = 0
        def source():
            nonlocal calls
            calls += 1
            if calls == 2:
                changed = {k: [r[:] for r in v] for k, v in self.tabs.items()}
                changed["ФОП"][1][11] = "Changed officer"
                return module.SANDBOX_SHEET_ID, changed
            return module.SANDBOX_SHEET_ID, self.tabs
        with self.assertRaisesRegex(ValueError, "GOOGLE_SOURCE_CHANGED"):
            module.apply_controlled(self.con, source, first["preview_digest"], module.CONFIRMATION)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_profile_trigger_change_causes_transaction_rollback(self):
        self.con.execute("""CREATE TRIGGER bad_side_effect AFTER INSERT ON supplier_edr_verification_events
          BEGIN UPDATE supplier_edr_profiles SET edr_status='changed'
          WHERE supplier_code=NEW.supplier_code; END""")
        self.con.commit()
        first, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        with self.assertRaisesRegex(ValueError, "PROFILE_CHANGED"):
            module.apply_controlled(self.con, lambda: (module.SANDBOX_SHEET_ID, self.tabs),
                                    first["preview_digest"], module.CONFIRMATION)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_profiles "
                                          "WHERE edr_status='changed'").fetchone()[0], 0)

    def test_literal_identity_never_merges_digits(self):
        self.tabs["ФОП"][1][1] = "UA-001"
        result, _ = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(result["candidate_newer"], 0)
        self.assertEqual(result["invalid_or_ambiguous"]["ambiguous_identity"], 1)

    def test_max_ten_and_confirmation(self):
        extra = [{"code": f"X{i:02}", "tab": "ФОП", "date": "2026-09-22",
                  "officer": "Officer", "pqm_date": ""} for i in range(20)]
        self.con.close()
        self.con, self.tabs, self.items, self.projection = fixture(extra)
        module.supplier_registry_integration._build_full_registry.return_value = {"items": self.items}
        result, selected = module.build_preview(self.con, module.SANDBOX_SHEET_ID, self.tabs)
        self.assertEqual(result["planned_inserts"], 20)
        self.assertEqual(len(selected), 10)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_CONFIRMATION_REQUIRED"):
            module.apply_controlled(self.con, lambda: (module.SANDBOX_SHEET_ID, self.tabs),
                                    result["preview_digest"], "no")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
