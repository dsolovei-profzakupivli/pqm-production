"""Sandbox Preview skips rows without a trustworthy observation timestamp."""
import unittest

import edr_sync_v2 as sync
import sandbox_edr_review
from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


class EdrPreviewSkippedRowsTests(unittest.TestCase):
    def setUp(self):
        self.con = database()

    def tearDown(self):
        self.con.close()

    def seed_profile(self, code, manager="OLD MANAGER", checked="2026-09-20T12:00:00+03:00"):
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,edr_status,full_name,short_name,edr_checked_at,edr_officer,
           termination_decision_details,edr_notes,synced_at)
          VALUES(?,?,?,'OLD FULL','OLD SHORT',?,'OLD OFFICER','OLD G','OLD M','seed')""",
          (code, manager, "Зареєстровано", checked))

    def test_mass_date_only_and_blank_rows_are_skipped_without_blocking_valid_row(self):
        mass = 1200
        source_rows = []
        for index in range(mass):
            code = f"{90_000_000 + index:08d}"
            self.seed_profile(code)
            if index % 2:
                source_rows.append(row(code=code, checked="", officer="NEW OFFICER", manager="NEW MANAGER"))
            else:
                source_rows.append(row(code=code, checked="20.09.2026", date_only=True,
                                       officer="NEW OFFICER", manager="NEW MANAGER"))
        valid_code = "38261938"
        self.seed_profile(valid_code, manager="ДОВБЕНКО ВОЛОДИМИР ВІТАЛІЙОВИЧ")
        source_rows.append(row(code=valid_code, checked="23.10.2026 17:03:19",
                               officer="УО контроль", manager="ПАРФЕНЮК СЕРГІЙ СЕРГІЙОВИЧ"))
        source = snapshot(*source_rows)

        before_preview = self.con.total_changes
        preview = sync.build_preview(self.con, source, sandbox_mode=True)
        self.assertEqual(self.con.total_changes, before_preview)
        self.assertEqual(preview["conflicts"], [])
        self.assertEqual(preview["summary"]["skipped"], mass)
        self.assertEqual(preview["summary"]["skipped_unverified_timestamp"], mass)
        self.assertEqual(preview["summary"]["eligible"], 1)
        self.assertEqual(preview["summary"]["conflict"], 0)
        self.assertEqual(sum(item["row_state"] == "skipped" for item in preview["items"]), mass)
        self.assertTrue(all(not item["changed_fields"] for item in preview["items"][:-1]))
        review_rows = sandbox_edr_review.details(preview)
        self.assertEqual(sum(item["category"] == "skipped" for item in review_rows), mass)
        self.assertEqual(sandbox_edr_review.summary_additions(preview, review_rows)["changed_suppliers"], 1)

        old_digest = sync.preview_state_digest(preview)
        result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
            actor="synthetic", synced_at="2026-10-29T12:00:00+03:00",
            sync_manager=lambda *args: {"changed": True},
            reconcile_manager_nazk=lambda con, code: None,
            expected_state_digest=old_digest, sandbox_mode=True)
        self.assertEqual(result["skipped_no_verification_timestamp"], mass)
        self.assertEqual(result["updated_profiles"], 1)
        for index in (0, 1, mass - 1):
            code = f"{90_000_000 + index:08d}"
            stored = self.con.execute("""SELECT manager_name,edr_status,edr_checked_at,
              edr_officer,termination_decision_details,edr_notes,last_google_received_at
              FROM supplier_edr_profiles WHERE supplier_code=?""", (code,)).fetchone()
            self.assertEqual(tuple(stored), (
                "OLD MANAGER", "Зареєстровано", "2026-09-20T12:00:00+03:00",
                "OLD OFFICER", "OLD G", "OLD M", ""))
            self.assertEqual(self.con.execute(
                "SELECT COUNT(*) FROM supplier_google_receipts WHERE supplier_code=?", (code,)
            ).fetchone()[0], 0)
        control = self.con.execute(
            "SELECT manager_name,edr_checked_at FROM supplier_edr_profiles WHERE supplier_code=?",
            (valid_code,)).fetchone()
        self.assertEqual(tuple(control), ("ПАРФЕНЮК СЕРГІЙ СЕРГІЙОВИЧ", "2026-10-23T17:03:19+03:00"))

    def test_short_trailing_cells_are_blank_but_missing_canonical_header_is_rejected(self):
        self.seed_profile("12345678")
        short = row(code="12345678", checked="21.09.2026 13:00:00", officer="NEW OFFICER", manager="OLD MANAGER")[:12]
        source = snapshot(short)
        preview = sync.build_preview(self.con, source, sandbox_mode=True)
        self.assertEqual(preview["conflicts"], [])
        item = preview["items"][0]
        self.assertEqual(item["row_state"], "eligible")
        decision = next(change for change in item["mirror_field_changes"] if change["field"] == "edr_notes")
        self.assertEqual((decision["action"], decision["reason"], decision["planned"]),
                         ("clear", "newer_google_verification", ""))

        bad_headers = list(sync.HEADERS)
        bad_headers.pop(12)
        with self.assertRaisesRegex(ValueError, "canonical mapping"):
            sync.source_snapshot({"ФОП": [bad_headers, short], "ЮО": [list(sync.HEADERS)]})

    def test_real_conflict_skips_only_its_row_and_keeps_valid_rows_atomic(self):
        self.seed_profile("12345678")
        self.seed_profile("12345679")
        valid = row(code="12345678", checked="23.10.2026 17:03:19",
                    officer="NEW OFFICER", manager="NEW MANAGER")
        malformed = row(code="12345679", checked="not-a-date",
                        officer="NEW OFFICER", manager="NEW MANAGER")
        source = snapshot(valid, malformed)
        preview = sync.build_preview(self.con, source, sandbox_mode=True)
        self.assertEqual(preview["summary"]["eligible"], 1)
        self.assertEqual(preview["summary"]["conflict"], 1)
        self.assertEqual(preview["items"][1]["row_state"], "conflict")
        blocked_details = [entry for entry in sandbox_edr_review.details(preview)
                           if entry["supplier_code"] == "12345679"]
        self.assertTrue(blocked_details)
        self.assertTrue(all(entry["action"] == "blocked" for entry in blocked_details))
        result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
            actor="synthetic", synced_at="2026-10-29T12:00:00+03:00",
            expected_state_digest=sync.preview_state_digest(preview), sandbox_mode=True)
        self.assertEqual(result["updated_profiles"], 1)
        self.assertEqual(result["skipped_conflicts"], 1)
        self.assertEqual(self.con.execute(
            "SELECT manager_name FROM supplier_edr_profiles WHERE supplier_code='12345678'"
        ).fetchone()[0], "NEW MANAGER")
        stale = self.con.execute("""SELECT manager_name,edr_checked_at,last_google_received_at
          FROM supplier_edr_profiles WHERE supplier_code='12345679'""").fetchone()
        self.assertEqual(tuple(stale), ("OLD MANAGER", "2026-09-20T12:00:00+03:00", ""))
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM supplier_google_receipts WHERE supplier_code='12345679'"
        ).fetchone()[0], 0)

    def test_state_change_after_preview_blocks_the_whole_apply_before_any_write(self):
        self.seed_profile("12345678")
        self.seed_profile("12345679")
        source = snapshot(
            row(code="12345678", checked="23.10.2026 17:03:19", officer="NEW", manager="NEW A"),
            row(code="12345679", checked="23.10.2026 17:03:19", officer="NEW", manager="NEW B"),
        )
        reviewed = sync.build_preview(self.con, source, sandbox_mode=True)
        reviewed_digest = sync.preview_state_digest(reviewed)
        # Simulate a concurrent operator change after review, then measure only
        # writes attempted by Apply. The stale digest must fail before receipts.
        self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='concurrent edit' WHERE supplier_code='12345679'")
        changes_before_apply = self.con.total_changes
        with self.assertRaisesRegex(RuntimeError, "PQM state changed after reviewed preview"):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                actor="synthetic", synced_at="2026-10-29T12:00:00+03:00",
                expected_state_digest=reviewed_digest, sandbox_mode=True)
        self.assertEqual(self.con.total_changes, changes_before_apply)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM supplier_google_receipts"
        ).fetchone()[0], 0)

    def test_38261938_reconcile_callback_only_follows_applied_manager_change(self):
        code = "38261938"
        self.seed_profile(code, manager="ДОВБЕНКО ВОЛОДИМИР ВІТАЛІЙОВИЧ")
        callbacks = []
        undated = snapshot(row(code=code, checked="", officer="NEW OFFICER",
                               manager="ПАРФЕНЮК СЕРГІЙ СЕРГІЙОВИЧ"))
        preview = sync.build_preview(self.con, undated, sandbox_mode=True)
        self.assertEqual(preview["items"][0]["row_state"], "skipped")
        sync.apply(self.con, undated, undated["source_fingerprint"], confirmed=True,
            actor="synthetic", synced_at="2026-10-29T12:00:00+03:00",
            sync_manager=lambda *args: callbacks.append("manager") or {"changed": True},
            reconcile_manager_nazk=lambda *args: callbacks.append("nazk"), sandbox_mode=True)
        self.assertEqual(callbacks, [])
        self.assertEqual(self.con.execute(
            "SELECT manager_name FROM supplier_edr_profiles WHERE supplier_code=?", (code,)
        ).fetchone()[0], "ДОВБЕНКО ВОЛОДИМИР ВІТАЛІЙОВИЧ")

        exact = snapshot(row(code=code, checked="23.10.2026 17:03:19", officer="NEW OFFICER",
                             manager="ПАРФЕНЮК СЕРГІЙ СЕРГІЙОВИЧ"))
        plan = sync.build_preview(self.con, exact, sandbox_mode=True)
        self.assertEqual(plan["items"][0]["manager_change_kind"], "real_identity_change")
        self.assertEqual(plan["items"][0]["row_state"], "eligible")
        sync.apply(self.con, exact, exact["source_fingerprint"], confirmed=True,
            actor="synthetic", synced_at="2026-10-29T12:00:00+03:00",
            sync_manager=lambda *args: callbacks.append("manager") or {"changed": True},
            reconcile_manager_nazk=lambda *args: callbacks.append("nazk"), sandbox_mode=True)
        self.assertEqual(callbacks, ["manager", "nazk"])


if __name__ == "__main__":
    unittest.main()
