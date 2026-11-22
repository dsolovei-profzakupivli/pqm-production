import json
import gc
import tempfile
import unittest
from pathlib import Path

import nazk_registry_evidence
import reference_directories
import server


class NazkFullContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        self.old_db_factory = server.db
        server.DB_PATH = Path(self.temp.name) / "pqm.sqlite3"
        self.con = self.old_db_factory()
        server.db = lambda: self.con
        server.init_db()
        server.init_reference_tables(server.DB_PATH)

    def tearDown(self):
        server.db = self.old_db_factory
        self.con.close()
        server.DB_PATH = self.old_db
        gc.collect()
        self.temp.cleanup()

    def _insert_record(self, source_id, *, punishment="", raw_json=None):
        raw_json = raw_json if raw_json is not None else json.dumps({
            "decreeNumber": "Н-0012",
            "decreeDate": "2026-10-09",
            "privatePayload": "must-not-be-projected",
        }, ensure_ascii=False)
        with server.db() as con:
            con.execute("""INSERT INTO nazk_registry
              (source_id,full_name,offense_name,court_case_number,sentence_date,
               punishment_start,decision_url,punishment,raw_json)
              VALUES (?,?,?,?,?,?,?,?,?)""",
              (source_id, "КРУГЛЯК ОЛЕКСІЙ МИХАЙЛОВИЧ", "Опис порушення",
               "551/226/26", "2026-10-07", "2026-10-08",
               "https://example.test/decision", punishment, raw_json))

    def test_directory_api_projects_all_nine_fields_without_raw_json(self):
        self._insert_record("nazk-nonempty", punishment="Призначено штраф")
        self._insert_record("nazk-empty", punishment="", raw_json="not-json")

        result = reference_directories.list_registry(server.DB_PATH, "nazk", {"search": ["Кругляк"]})
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 2)
        expected = {
            "source_id", "full_name", "offense_name", "punishment", "court_case_number",
            "sentence_date", "punishment_start", "decision_url", "decree_number", "decree_date",
        }
        for item in result["items"]:
            self.assertTrue(expected <= item.keys())
            self.assertNotIn("raw_json", item)
            self.assertNotIn("privatePayload", item)
            self.assertEqual(item["sentence_date"], "07.10.2026")
            self.assertEqual(item["punishment_start"], "08.10.2026")
        nonempty = next(item for item in result["items"] if item["source_id"] == "nazk-nonempty")
        empty = next(item for item in result["items"] if item["source_id"] == "nazk-empty")
        self.assertEqual((nonempty["punishment"], nonempty["decree_number"], nonempty["decree_date"]),
                         ("Призначено штраф", "Н-0012", "2026-10-09"))
        self.assertEqual((empty["punishment"], empty["decree_number"], empty["decree_date"]),
                         ("", "", ""))

    def test_supplier_profile_projects_source_id_and_decree_fields(self):
        code = "10000001"
        manager = "КРУГЛЯК ОЛЕКСІЙ МИХАЙЛОВИЧ"
        with server.db() as con:
            con.execute("""INSERT INTO supplier_registry_summary
              (supplier_code,supplier_name,active_count,refreshed_at) VALUES (?,?,?,?)""",
              (code, "Тестовий постачальник", 0, server.now_iso()))
            con.execute("""INSERT INTO supplier_managers
              (supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
              VALUES (?,?,?,1,'test',?,?)""",
              (code, manager, "кругляк олексій михайлович", server.now_iso(), server.now_iso()))
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,manager_name,synced_at) VALUES (?,?,?)""",
              (code, manager, server.now_iso()))
        self._insert_record("nazk-profile", punishment="Стягнення збережене")

        profile = server.supplier_profile(code)
        self.assertEqual(len(profile["nazk"]), 1)
        row = profile["nazk"][0]
        self.assertEqual(row["source_id"], "nazk-profile")
        self.assertEqual(row["punishment"], "Стягнення збережене")
        self.assertEqual((row["decree_number"], row["decree_date"]), ("Н-0012", "2026-10-09"))
        self.assertNotIn("raw_json", row)
        self.assertNotIn("privatePayload", row)

    def test_operational_evidence_projection_keeps_source_id_and_optional_fields(self):
        self._insert_record("nazk-evidence", punishment="Призначено штраф", raw_json=json.dumps({
            "decreeNumber": "Н-18", "decreeDate": "2026-10-09", "privatePayload": "hidden",
        }, ensure_ascii=False))
        self._insert_record("nazk-evidence-empty", punishment="", raw_json="{}")
        records = []
        for source_id in ("nazk-evidence", "nazk-evidence-empty"):
            with server.db() as con:
                cursor = con.execute("""INSERT INTO supplier_nazk_checks
                  (supplier_code,manager_name,workflow_status,started_at,created_at,created_by,updated_at,updated_by)
                  VALUES ('10000001','КРУГЛЯК ОЛЕКСІЙ МИХАЙЛОВИЧ','completed',?,?,?,?,?)""",
                  (server.now_iso(), server.now_iso(), "test", server.now_iso(), "test"))
                check_id = cursor.lastrowid
                con.execute("""INSERT INTO supplier_nazk_check_matches
                  (check_id,nazk_source_id,match_status,created_at) VALUES (?,?,'candidate',?)""",
                  (check_id, source_id, server.now_iso()))
            records.extend(nazk_registry_evidence.registry_records(self.con, check_id))
        self.assertEqual([row["source_id"] for row in records], ["nazk-evidence", "nazk-evidence-empty"])
        self.assertEqual((records[0]["punishment"], records[0]["decree_number"], records[0]["decree_date"]),
                         ("Призначено штраф", "Н-18", "2026-10-09"))
        self.assertEqual((records[1]["punishment"], records[1]["decree_number"], records[1]["decree_date"]),
                         ("", "", ""))
        self.assertTrue(all("raw_json" not in row and "privatePayload" not in row for row in records))


if __name__ == "__main__":
    unittest.main()
