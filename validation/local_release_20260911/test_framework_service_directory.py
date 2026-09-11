import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class FrameworkServiceDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "pqm.sqlite3"
        server.init_db()
        with server.db() as con:
            con.execute("""INSERT INTO frameworks(id,pretty_id,dk_code,title,status,raw_json,synced_at)
              VALUES ('framework-1','UA-F-1','11110000-0','Чинний відбір','active','{}',?)""",
              (server.now_iso(),))

    def tearDown(self):
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    @staticmethod
    def rows(category="ЇЖА", officer="Савва", url="https://market/one"):
        return [
            {"ID": "UA-F-1", "ДК": "11110000-0", "КАТЕГ": category,
             "Хто розглядає": "Особа розгляду", "Хто публікує": officer, "Посилання на майданчик": url,
             "status": "активне", "Назва фреймворку": "Чинний відбір"},
            {"ID": "UA-F-2", "ДК": "22220000-0", "КАТЕГ": "ІНШЕ",
             "Хто розглядає": "Інша особа", "Хто публікує": "Федченко", "Посилання на майданчик": "https://market/two",
             "status": "закрите", "Назва фреймворку": "Історичний відбір"},
            {"ID": "UA-F-3", "ДК": "33330000-0", "КАТЕГ": "ІНШЕ",
             "Хто розглядає": "", "Хто публікує": "", "Посилання на майданчик": "",
             "status": "не відбулося", "Назва фреймворку": "Скасований відбір"},
        ]

    def test_imports_all_statuses_including_unmatched_frameworks(self):
        with patch.object(server, "load_announcement_rows", return_value=self.rows()):
            result = server.sync_framework_officers()
        self.assertEqual(result["unique"], 3)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["unmatched"], 2)
        with server.db() as con:
            rows = con.execute("SELECT pretty_id FROM framework_service_directory ORDER BY pretty_id").fetchall()
        self.assertEqual([row[0] for row in rows], ["UA-F-1", "UA-F-2", "UA-F-3"])

    def test_responsible_officer_comes_from_publisher_not_reviewer(self):
        with patch.object(server, "load_announcement_rows", return_value=self.rows()):
            server.sync_framework_officers()
        with server.db() as con:
            officer = con.execute(
                "SELECT responsible_officer FROM framework_service_directory WHERE pretty_id='UA-F-1'"
            ).fetchone()[0]
        self.assertEqual(officer, "Дмитро САВВА")

    def test_google_refresh_does_not_overwrite_pqm_managed_fields(self):
        with patch.object(server, "load_announcement_rows", return_value=self.rows()):
            server.sync_framework_officers()
        with server.db() as con:
            con.execute("""UPDATE framework_service_directory SET category='РУЧНА',marketplace_url='https://pqm',
              responsible_officer='Олена ЄРЬОМІНА',source='PQM' WHERE pretty_id='UA-F-1'""")
            con.execute("""UPDATE framework_officers SET category='РУЧНА',marketplace_url='https://pqm',
              officer='Олена ЄРЬОМІНА',source='PQM' WHERE framework_id='framework-1'""")
        with patch.object(server, "load_announcement_rows", return_value=self.rows("НОВА", "Федченко", "https://google")):
            server.sync_framework_officers()
        with server.db() as con:
            directory = con.execute("SELECT category,marketplace_url,responsible_officer,source FROM framework_service_directory WHERE pretty_id='UA-F-1'").fetchone()
            projection = con.execute("SELECT category,marketplace_url,officer,source FROM framework_officers WHERE framework_id='framework-1'").fetchone()
        self.assertEqual(tuple(directory), ("РУЧНА", "https://pqm", "Олена ЄРЬОМІНА", "PQM"))
        self.assertEqual(tuple(projection), ("РУЧНА", "https://pqm", "Олена ЄРЬОМІНА", "PQM"))

    def test_initial_google_officer_is_filled_when_pqm_value_is_absent(self):
        with patch.object(server, "load_announcement_rows", return_value=self.rows(officer="Федченко")):
            server.sync_framework_officers()
        with server.db() as con:
            directory = con.execute("SELECT responsible_officer,source FROM framework_service_directory WHERE pretty_id='UA-F-1'").fetchone()
            projection = con.execute("SELECT officer,source FROM framework_officers WHERE framework_id='framework-1'").fetchone()
        self.assertEqual(tuple(directory), ("Тетяна ФЕДЧЕНКО", "Google Sheets: Оголошення"))
        self.assertEqual(tuple(projection), ("Тетяна ФЕДЧЕНКО", "Google Sheets: Оголошення"))

    def test_status_precedence_uses_complete_before_qualification_end_date(self):
        future = {"qualificationPeriod": {"endDate": "2999-01-01T00:00:00+02:00"}}
        past = {"qualificationPeriod": {"endDate": "2000-01-01T00:00:00+02:00"}}
        self.assertEqual(server.effective_framework_status("complete", future), "closed")
        self.assertEqual(server.effective_framework_status("active", future), "active")
        self.assertEqual(server.effective_framework_status("active", past), "closed")
        self.assertEqual(server.effective_framework_status("active", {}), "active")
        self.assertEqual(server.effective_framework_status("unexpected", future), "unexpected")

    def test_manual_create_is_pqm_owned_and_audited(self):
        result = server.create_framework_service_entry({
            "pretty_id": "UA-F-NEW", "dk_code": "44440000-0",
            "category": "ІНШЕ", "marketplace_url": "https://market/new",
        }, "Адміністратор")
        self.assertTrue(result["created"])
        with server.db() as con:
            row = con.execute("SELECT source,category FROM framework_service_directory WHERE pretty_id='UA-F-NEW'").fetchone()
            audit = con.execute("SELECT COUNT(*) FROM audit_log WHERE submission_id='UA-F-NEW' AND field_name='framework_directory.created'").fetchone()[0]
        self.assertEqual(tuple(row), ("PQM", "ІНШЕ"))
        self.assertEqual(audit, 1)
        directory = server.framework_service_directory()
        created = next(item for item in directory["items"] if item["pretty_id"] == "UA-F-NEW")
        self.assertEqual(created["status"], "Не визначено")

    def test_import_new_reports_conflicts_and_never_overwrites_existing(self):
        server.create_framework_service_entry({
            "pretty_id": "UA-F-1", "dk_code": "11110000-0", "category": "РУЧНА"
        }, "Адміністратор")
        with patch.object(server, "load_announcement_rows", return_value=self.rows("GOOGLE")):
            result = server.import_new_framework_service_entries("Адміністратор")
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["existing_conflicts"], 1)
        with server.db() as con:
            category = con.execute("SELECT category FROM framework_service_directory WHERE pretty_id='UA-F-1'").fetchone()[0]
        self.assertEqual(category, "РУЧНА")

    def test_base_frameworks_remain_available_without_bids_database(self):
        with patch.object(server, "BIDS_MODE", "disabled"):
            result = server.framework_analytics({"page": ["1"], "size": ["25"]})
        self.assertFalse(result["bids_available"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["framework"]["pretty_id"], "UA-F-1")
        self.assertIn("лише в LOCAL", result["message"])

    def test_manual_directory_entry_is_part_of_tracked_source_set(self):
        server.create_framework_service_entry({
            "pretty_id": "UA-F-NEW", "dk_code": "39540000-9", "category": "НОВИЙ"
        }, "Адміністратор")
        api_items = {
            "framework-1": {"id": "framework-1", "prettyID": "UA-F-1", "status": "active",
                            "procuringEntity": {"identifier": {"id": server.ORGANIZER_EDRPOU}}},
            "framework-new": {"id": "framework-new", "prettyID": "UA-F-NEW", "status": "active",
                              "procuringEntity": {"identifier": {"id": server.ORGANIZER_EDRPOU}}},
        }
        def get(url):
            return {"data": api_items[url.rsplit('/', 1)[-1]]}
        with patch.object(server, "load_announcement_rows", return_value=self.rows()[:1]), \
             patch.object(server, "paginated_pages", return_value=[[{"id": key} for key in api_items]]), \
             patch.object(server, "api_get", side_effect=get):
            tracked = server.discover_tracked_frameworks()
        self.assertEqual([item["prettyID"] for item in tracked], ["UA-F-1", "UA-F-NEW"])

    def test_missing_factual_api_record_keeps_manual_directory_entry_pending(self):
        server.create_framework_service_entry({
            "pretty_id": "UA-F-PENDING", "dk_code": "39540000-9"
        }, "Адміністратор")
        factual = {"id": "framework-1", "prettyID": "UA-F-1", "status": "active",
                   "procuringEntity": {"identifier": {"id": server.ORGANIZER_EDRPOU}}}
        with patch.object(server, "load_announcement_rows", return_value=self.rows()[:1]), \
             patch.object(server, "paginated_pages", return_value=[[{"id": "framework-1"}]]), \
             patch.object(server, "api_get", return_value={"data": factual}), \
             self.assertLogs(server.SERVER_LOG, level="WARNING") as logs:
            tracked = server.discover_tracked_frameworks()
        self.assertEqual([item["prettyID"] for item in tracked], ["UA-F-1"])
        self.assertTrue(any("UA-F-PENDING" in message for message in logs.output))
        directory = server.framework_service_directory()
        pending = next(item for item in directory["items"] if item["pretty_id"] == "UA-F-PENDING")
        self.assertEqual(pending["status"], "Не визначено")

    def test_pending_manual_entry_is_visible_as_undefined_without_prozorro_data(self):
        server.create_framework_service_entry({
            "pretty_id": "UA-F-PENDING", "dk_code": "39540000-9", "source_title": "Новий відбір"
        }, "Адміністратор")
        with patch.object(server, "BIDS_MODE", "disabled"):
            result = server.framework_analytics({"page": ["1"], "size": ["25"],
                                                 "search": ["UA-F-PENDING"]})
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["framework"]["pretty_id"], "UA-F-PENDING")
        self.assertEqual(item["source_status"], "")
        self.assertTrue(item["agreement_pending"])

    def test_factual_framework_links_manual_directory_row_idempotently(self):
        server.create_framework_service_entry({
            "pretty_id": "UA-F-NEW", "dk_code": "39540000-9"
        }, "Адміністратор")
        factual = {"id": "framework-new", "prettyID": "UA-F-NEW", "title": "Новий відбір",
                   "classification": {"id": "39540000-9"}, "status": "active",
                   "procuringEntity": {"identifier": {"id": server.ORGANIZER_EDRPOU}}}
        self.assertTrue(server.save_framework(factual))
        self.assertTrue(server.save_framework(factual))
        with server.db() as con:
            relation = con.execute("SELECT framework_id FROM framework_service_directory WHERE pretty_id='UA-F-NEW'").fetchone()[0]
            count = con.execute("SELECT COUNT(*) FROM frameworks WHERE pretty_id='UA-F-NEW'").fetchone()[0]
        self.assertEqual(relation, "framework-new")
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
