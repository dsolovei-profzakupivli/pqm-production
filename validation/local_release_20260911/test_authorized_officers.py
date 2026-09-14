import tempfile
import unittest
from pathlib import Path

import server


class AuthorizedOfficerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "pqm.sqlite3"
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_canonical_directory_has_four_active_and_three_historical_people(self):
        rows = server.authorized_officers()
        self.assertEqual(len(rows), 7)
        self.assertEqual(sum(bool(row["active"]) for row in rows), 4)
        self.assertFalse(any(row["full_name"] == "НЕ ВИЗНАЧЕНО" for row in rows))
        self.assertFalse(any(row["full_name"] == "ОЛЕНА АБРОСІМОВА" for row in rows))

    def test_never_used_officer_can_be_deleted_but_used_officer_cannot(self):
        with server.db() as con:
            unused = con.execute("""INSERT INTO authorized_officers
                (full_name,role,active,created_at,updated_at) VALUES (?,?,?,?,?)""",
                ("Тест НЕВИКОРИСТАНИЙ", "УО", 0, server.now_iso(), server.now_iso())).lastrowid
            used = con.execute("""INSERT INTO authorized_officers
                (full_name,role,active,created_at,updated_at) VALUES (?,?,?,?,?)""",
                ("Тест ВИКОРИСТАНИЙ", "УО", 1, server.now_iso(), server.now_iso())).lastrowid
            con.execute("""INSERT INTO violation_reports(id,report_id,raw_json,synced_at)
                VALUES ('r','UA-D-R','{}',?)""", (server.now_iso(),))
            con.execute("""INSERT INTO violation_report_reviews
                (report_id,assigned_officer_id,assigned_officer,updated_at,updated_by)
                VALUES (?,?,?,?,?)""", ('r', used, "Тест ВИКОРИСТАНИЙ", server.now_iso(), "Тест"))
        self.assertEqual(server.officer_usage_count(unused, "Тест НЕВИКОРИСТАНИЙ"), 0)
        self.assertGreater(server.officer_usage_count(used, "Тест ВИКОРИСТАНИЙ"), 0)

    def test_officer_directory_explains_why_used_officer_cannot_be_deleted(self):
        app_js = (Path(__file__).parent / "app.js").read_text(encoding="utf-8")
        self.assertIn("x.can_delete", app_js)
        self.assertIn("УО вже використана у предметних даних — доступна лише деактивація", app_js)

    def test_login_resolves_to_canonical_officer_business_identity(self):
        with server.db() as con:
            officer = con.execute(
                "SELECT id,full_name FROM authorized_officers WHERE active=1 ORDER BY id LIMIT 1"
            ).fetchone()
            con.execute("""INSERT INTO auth_users
                (username,password_hash,role,officer_id,active,created_at,updated_at,created_by)
                VALUES (?,?,?,?,?,?,?,?)""", (
                    "d.savva", "test", "officer", officer["id"], 1,
                    server.now_iso(), server.now_iso(), "test",
                ))
            resolved = server.canonical_officer_identity(con, "d.savva")
        self.assertEqual(resolved, server.formatted_officer_name(officer["full_name"]))
        self.assertNotEqual(resolved, "d.savva")

    def test_unknown_login_is_not_persistable_as_officer_identity(self):
        with server.db() as con:
            self.assertEqual(server.canonical_officer_identity(con, "unknown.login"), "")

    def test_newer_manual_manager_is_not_overwritten_by_older_edr_snapshot(self):
        with server.db() as con:
            server.sync_current_supplier_manager(
                con, "12345678", "НОВИЙ КЕРІВНИК",
                "Підтверджено УО у заявці test", "2026-08-26T12:00:00+00:00",
            )
            result = server.sync_current_supplier_manager(
                con, "12345678", "СТАРИЙ КЕРІВНИК",
                "Google Sheets: ЄДР", "2026-08-20T12:00:00+00:00",
            )
            current = con.execute(
                "SELECT manager_name,source FROM supplier_managers WHERE supplier_code='12345678' AND is_current=1"
            ).fetchone()
        self.assertEqual(result["reason"], "newer_manual_value_preserved")
        self.assertEqual(current["manager_name"], "НОВИЙ КЕРІВНИК")
