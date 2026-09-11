import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class ConsolidatedAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "pqm.sqlite3"
        self.patch = patch.object(server, "DB_PATH", self.db_path)
        self.patch.start()
        server.init_db()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_additive_tables_and_system_profiles_exist(self):
        with server.db() as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("application_view_profiles", tables)
            self.assertIn("application_protocol_remark_selections", tables)
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM application_view_profiles WHERE is_system=1"
            ).fetchone()[0], 3)

    def test_remark_selections_round_trip_without_parsing_final_text(self):
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,raw_json,synced_at) VALUES ('f','UA-F','{}','now')")
            con.execute("""INSERT INTO submissions
              (id,framework_id,documents_json,raw_json,synced_at) VALUES ('s','f','[]','{}','now')""")
            remark_id = con.execute("SELECT id FROM remarks_catalog ORDER BY id LIMIT 1").fetchone()[0]
        self.assertEqual(server.save_application_remark_selections("s", [remark_id], "officer"), [remark_id])
        self.assertEqual(server.application_remark_selections("s"), [remark_id])
        self.assertEqual(server.save_application_remark_selections("s", [], "officer"), [])
        self.assertEqual(server.application_remark_selections("s"), [])

    def test_profiles_are_scoped_to_owner(self):
        with server.db() as con:
            con.execute("""INSERT INTO application_view_profiles
              (id,owner_key,name,is_system,columns_json,created_at,updated_at,created_by,updated_by)
              VALUES ('mine','alice','Особистий',0,'[]','now','now','alice','alice')""")
        alice = server.list_application_view_profiles("alice")["items"]
        bob = server.list_application_view_profiles("bob")["items"]
        self.assertIn("mine", {item["id"] for item in alice})
        self.assertNotIn("mine", {item["id"] for item in bob})
        self.assertTrue(all(item["is_system"] for item in bob))

    def test_profile_columns_exclude_filters_and_sort(self):
        result = server._validated_profile_columns([
            {"key": "participant", "visible": True, "order": 2, "width": 240,
             "search": "alpha", "sort": "desc"}
        ])
        self.assertEqual(result, [{"key": "participant", "visible": True, "order": 2,
                                  "width": 240, "pin": ""}])

    def test_local_oauth_status_distinguishes_access_failure(self):
        with patch.object(server, "ENABLE_GOOGLE", True), \
             patch.object(server, "_google_oauth_client", return_value=None), \
             patch.object(server, "_google_oauth_token", return_value=None), \
             patch.object(server, "GOOGLE_OAUTH_CLIENT_ACCESS_ERROR", "access_denied"), \
             patch.object(server, "GOOGLE_OAUTH_TOKEN_ACCESS_ERROR", ""):
            status = server.google_oauth_status()
        self.assertEqual(status["client_state"], "access_denied")
        self.assertEqual(status["token_state"], "absent")
        self.assertIn("доступ", status["message"].casefold())

    def test_local_oauth_status_distinguishes_expired_token(self):
        expired = {"access_token": "test-only", "obtained_at": 1, "expires_in": 1}
        with patch.object(server, "ENABLE_GOOGLE", True), \
             patch.object(server, "_google_oauth_client", return_value={"client_id": "test-only"}), \
             patch.object(server, "_google_oauth_token", return_value=expired), \
             patch.object(server, "GOOGLE_OAUTH_CLIENT_ACCESS_ERROR", ""), \
             patch.object(server, "GOOGLE_OAUTH_TOKEN_ACCESS_ERROR", ""):
            status = server.google_oauth_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["authorized"])
        self.assertEqual(status["token_state"], "expired")
        self.assertIn("прострочений", status["message"].casefold())


if __name__ == "__main__":
    unittest.main()
