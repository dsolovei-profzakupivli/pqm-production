import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_tool(name):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


meddata = load_tool("meddata_historical_migration")
officer_audit = load_tool("review_officer_login_audit")


class MedDataReleaseToolkitTests(unittest.TestCase):
    def test_manifest_is_exact_and_bound_to_canonical_source(self):
        payload = json.loads((ROOT / "metadata" / "meddata_historical_applications.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["applications"]), 53_803)
        self.assertEqual(payload["source"]["sha256"], meddata.EXPECTED_SOURCE_SHA256)
        self.assertEqual(payload["source"]["row_count"], 53_803)

    def test_all_ten_fields_and_canonical_enums_are_registered(self):
        self.assertEqual(len(meddata.FIELD_SPECS), 10)
        self.assertEqual(meddata.canonical_value("Погоджено", "compliance", {})[1], "approved")
        self.assertEqual(meddata.canonical_value("Не погоджено", "compliance", {})[1], "rejected")
        self.assertEqual(meddata.canonical_value("Так", "decision", {})[1], "admit")
        self.assertEqual(meddata.canonical_value("Ні", "decision", {})[1], "reject")
        self.assertEqual(meddata.canonical_value("Не визначено", "decision", {})[1], "")
        self.assertEqual(meddata.canonical_value("є", "text", {})[1], "є")

    def test_classification_is_idempotent(self):
        self.assertEqual(meddata.classify("same", True, "same"), "SAME")
        self.assertEqual(meddata.classify("", True, "value"), "INSERT_HISTORY")
        self.assertEqual(meddata.classify("test", True, "history"), "OVERWRITE_TEST_DATA")
        self.assertEqual(meddata.classify("value", False, ""), "NO_SOURCE_VALUE")

    def test_review_officer_audit_separates_manifest_and_pqm_era(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp); db = root / "test.sqlite3"; manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"version": 1, "applications": {"historical": {}}}), encoding="utf-8")
            con = sqlite3.connect(db)
            try:
                con.executescript("""
                CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY, full_name TEXT NOT NULL);
                CREATE TABLE auth_users(username TEXT PRIMARY KEY, officer_id INTEGER, active INTEGER NOT NULL);
                CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY, review_officer TEXT);
                CREATE TABLE audit_log(submission_id TEXT, changed_at TEXT, changed_by TEXT, field_name TEXT, old_value TEXT, new_value TEXT);
                """)
                con.execute("INSERT INTO authorized_officers VALUES (1,'ДМИТРО САВВА')")
                con.execute("INSERT INTO auth_users VALUES ('d.savva',1,1)")
                con.executemany("INSERT INTO application_fields VALUES (?,?)", (("historical", "d.savva"), ("current", "d.savva")))
                con.commit()
            finally:
                con.close()
            summary, plans = officer_audit.audit(db, manifest)
            self.assertTrue(summary["safe_to_apply_pqm_era"])
            self.assertEqual(summary["historical_manifest_login_applications"], 1)
            self.assertEqual(summary["pqm_era_login_applications"], 1)
            self.assertEqual({row["scope"] for row in plans}, {"historical_manifest", "pqm_era"})
            with tempfile.TemporaryDirectory() as backups:
                result = officer_audit.apply(db, plans, Path(backups))
            self.assertEqual(result["changed_pqm_era"], 1)
            self.assertEqual(result["historical_changed"], 0)
            con = sqlite3.connect(db)
            try:
                values = dict(con.execute("SELECT submission_id,review_officer FROM application_fields"))
                audit_rows = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            finally:
                con.close()
            self.assertEqual(values["historical"], "d.savva")
            self.assertEqual(values["current"], "Дмитро САВВА")
            self.assertEqual(audit_rows, 1)


if __name__ == "__main__":
    unittest.main()
