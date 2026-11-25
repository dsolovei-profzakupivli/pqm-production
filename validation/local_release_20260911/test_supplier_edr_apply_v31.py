"""V31 regression coverage for manager priority timestamps and Apply progress."""
import unittest
from unittest.mock import patch

import server
import edr_sync_v2
from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


class SupplierEdrApplyV31Tests(unittest.TestCase):
    def _manual_manager(self, con, *, code="12345678", name="РУЧНИЙ КЕРІВНИК",
                        updated_at="2026-11-23T17:05:00+00:00"):
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,created_at,updated_at)
          VALUES (?,?,?, '2026-11-01',NULL,1,'Підтверджено УО: тест',?,?)""",
          (code, name, server.normalize_manager_name(name), updated_at, updated_at))
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,edr_checked_at,synced_at)
          VALUES (?,?, '2026-11-22T12:00:00+02:00','old')""", (code, name))

    def _apply(self, con, source, *, sync_manager=None, enrich_manager=None):
        return edr_sync_v2.apply(
            con, source, source["source_fingerprint"], confirmed=True, actor="test",
            synced_at="2026-11-25T10:00:00+00:00",
            sync_manager=sync_manager or server.sync_current_supplier_manager,
            enrich_manager=enrich_manager or server.enrich_current_supplier_manager,
            establish_manager=server.establish_current_supplier_manager,
            reestablish_manager=server.reestablish_current_supplier_manager,
            sandbox_mode=True,
        )

    def test_apply_passes_exact_google_instant_and_keeps_history_as_calendar_dates(self):
        cases = (
            ("2026-11-23T17:00:00+00:00", True),  # earlier than 19:04:26 Kyiv
            ("2026-11-23T17:04:26+00:00", False),  # equal instant: manual value wins
            ("2026-11-23T17:05:00+00:00", False),  # later manual edit wins
        )
        for manual_updated_at, expect_google_manager in cases:
            with self.subTest(manual_updated_at=manual_updated_at):
                con = database()
                self.addCleanup(con.close)
                self._manual_manager(con, updated_at=manual_updated_at)
                source = snapshot(row(checked="23.11.2026 19:04:26", manager="НОВИЙ КЕРІВНИК"))
                result = self._apply(con, source)
                current = con.execute("SELECT * FROM supplier_managers WHERE is_current=1").fetchone()
                if expect_google_manager:
                    self.assertEqual(current["manager_name"], "НОВИЙ КЕРІВНИК")
                    previous = con.execute("SELECT * FROM supplier_managers WHERE is_current=0").fetchone()
                    self.assertEqual(previous["valid_to"], "2026-11-23")
                    self.assertEqual(current["valid_from"], "2026-11-23")
                    self.assertEqual(result["manager_identity_changes"], 1)
                else:
                    self.assertEqual(current["manager_name"], "РУЧНИЙ КЕРІВНИК")
                    self.assertEqual(result["manager_identity_changes"], 0)
                self.assertEqual(con.execute("SELECT edr_checked_at FROM supplier_edr_profiles").fetchone()[0],
                                 "2026-11-23T19:04:26+02:00")

    def test_apply_enrichment_uses_exact_instant_for_manual_priority(self):
        con = database()
        self.addCleanup(con.close)
        self._manual_manager(con, name="ТКАЧЕНКО Н.М.", updated_at="2026-11-23T17:05:00+00:00")
        source = snapshot(row(checked="23.11.2026 19:04:26", manager="ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА"))
        preview = edr_sync_v2.build_preview(con, source, sandbox_mode=True)
        self.assertEqual(preview["items"][0]["manager_change_kind"], "representation_enrichment")
        result = self._apply(con, source)
        current = con.execute("SELECT * FROM supplier_managers WHERE is_current=1").fetchone()
        self.assertEqual(current["manager_name"], "ТКАЧЕНКО Н.М.")
        self.assertEqual(result["manager_representation_enrichments"], 0)

    def test_priority_normalizer_handles_naive_utc_kyiv_and_both_dst_seasons(self):
        cases = (
            ("2026-01-15T10:00:00+02:00", "2026-01-15T08:00:00+00:00"),
            ("2026-07-15T10:00:00+03:00", "2026-07-15T07:00:00+00:00"),
            ("2026-07-15T10:00:00", "2026-07-15T07:00:00+00:00"),
        )
        for google, utc in cases:
            with self.subTest(google=google):
                self.assertEqual(server._supplier_manager_priority_instant(google, google_source=True),
                                 server._supplier_manager_priority_instant(utc))
        self.assertEqual(server._supplier_manager_priority_instant("2026-01-15"),
                         server._supplier_manager_priority_instant("2026-01-15T00:00:00+02:00"))

    def test_apply_progress_reports_real_completed_rows_and_does_not_change_summary(self):
        con = database()
        self.addCleanup(con.close)
        for code in ("12345678", "87654321"):
            con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,edr_checked_at,synced_at) VALUES (?,?,?,?)",
                        (code, "ПОПЕРЕДНІЙ", "2026-09-14T12:00:00+03:00", "old"))
        source = snapshot(row(), row(code="87654321", checked="16.09.2026"))
        updates = []
        result = edr_sync_v2.apply(con, source, source["source_fingerprint"], confirmed=True,
            actor="test", synced_at="2026-11-25T10:00:00+00:00", sandbox_mode=True,
            progress_callback=updates.append)
        self.assertEqual(updates[0], {"processed": 0, "total": 2, "stage": "applying"})
        self.assertEqual(updates[-1], {"processed": 2, "total": 2, "stage": "applying"})
        self.assertEqual(result["processed"], 2)
        self.assertEqual(len(updates), 3)

    def test_apply_exception_rolls_back_all_business_writes(self):
        con = database()
        self.addCleanup(con.close)
        for code, name in (("12345678", "ПОПЕРЕДНІЙ А"), ("87654321", "ПОПЕРЕДНІЙ Б")):
            con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,edr_checked_at,synced_at) VALUES (?,?,?,?)",
                        (code, name, "2026-09-14T12:00:00+03:00", "old"))
            con.execute("""INSERT INTO supplier_managers
              (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
              VALUES (?,?,?, '2026-08-01',NULL,1,'ЄДР','2026-08-01','2026-08-01')""",
              (code, name, server.normalize_manager_name(name)))
        con.commit()
        source = snapshot(row(manager="НОВИЙ А", checked="15.09.2026"),
                          row(code="87654321", manager="НОВИЙ Б", checked="16.09.2026"))
        calls = 0
        def fail_after_first(con, *args):
            nonlocal calls
            calls += 1
            result = server.sync_current_supplier_manager(con, *args)
            if calls == 2:
                raise RuntimeError("synthetic mid-Apply failure")
            return result
        with self.assertRaisesRegex(RuntimeError, "synthetic mid-Apply failure"):
            with con:
                self._apply(con, source, sync_manager=fail_after_first)
        profiles = con.execute("SELECT supplier_code,manager_name FROM supplier_edr_profiles ORDER BY supplier_code").fetchall()
        self.assertEqual([tuple(item) for item in profiles],
                         [("12345678", "ПОПЕРЕДНІЙ А"), ("87654321", "ПОПЕРЕДНІЙ Б")])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_google_receipts").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_worker_rolls_back_business_changes_and_records_failed_result(self):
        con = database()
        self.addCleanup(con.close)
        con.execute("ALTER TABLE submissions ADD COLUMN framework_id TEXT DEFAULT ''")
        for code, name in (("12345678", "ПОПЕРЕДНІЙ А"), ("87654321", "ПОПЕРЕДНІЙ Б")):
            con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,edr_checked_at,synced_at) VALUES (?,?,?,?)",
                        (code, name, "2026-09-14T12:00:00+03:00", "old"))
            con.execute("""INSERT INTO supplier_managers
              (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
              VALUES (?,?,?, '2026-08-01',NULL,1,'ЄДР','2026-08-01','2026-08-01')""",
              (code, name, server.normalize_manager_name(name)))
        con.commit()
        source = snapshot(row(manager="НОВИЙ А"), row(code="87654321", manager="НОВИЙ Б", checked="16.09.2026"))
        state_digest = edr_sync_v2.preview_state_digest(
            edr_sync_v2.build_preview(con, source, sandbox_mode=True))
        original = server.sync_current_supplier_manager
        calls = 0
        def fail_second_callback(*args):
            nonlocal calls
            calls += 1
            result = original(*args)
            if calls == 2:
                raise RuntimeError("synthetic worker failure")
            return result
        state = {}
        with patch.object(server, "db", return_value=con), \
             patch.object(server, "supplier_edr_source_snapshot", return_value=source), \
             patch.object(server, "sync_current_supplier_manager", side_effect=fail_second_callback), \
             patch.object(server, "refresh_current_submission_nazk_controls"), \
             patch.object(server, "reconcile_supplier_nazk_after_edr_manager_change"), \
             patch.object(server, "SUPPLIER_EDR_SYNC_STATE", state), \
             patch.object(server, "SANDBOX_MODE", True):
            server.supplier_edr_sync_worker(source["source_fingerprint"], "test", state_digest, 2)
        profiles = con.execute("SELECT supplier_code,manager_name FROM supplier_edr_profiles ORDER BY supplier_code").fetchall()
        self.assertEqual([tuple(item) for item in profiles],
                         [("12345678", "ПОПЕРЕДНІЙ А"), ("87654321", "ПОПЕРЕДНІЙ Б")])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_google_receipts").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)
        self.assertFalse(state["running"])
        self.assertEqual(state["last_result"], "failed")
        self.assertEqual(state["last_result_summary"]["errors"], 1)
        self.assertIn("synthetic worker failure", state["error"])


if __name__ == "__main__":
    unittest.main()
