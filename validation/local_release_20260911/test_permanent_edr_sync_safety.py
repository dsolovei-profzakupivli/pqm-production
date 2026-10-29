"""Permanent Google -> PQM sync must not undo controlled factual/verification evidence."""
import json
import os
import unittest
from unittest.mock import patch

import edr_sync_v2 as sync
from google_verification_contract import google_verification_instant, incoming_verification_gate
from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


CODE = "12345678"
MIRROR_FIELDS = {
    "termination_decision_details": (6, "Old G", "New G"),
    "termination_record_date": (9, "2026-08-01", "19.09.2026"),
    "termination_record_number": (10, "Old K", "New K"),
    "edr_notes": (12, "Old M", "New M"),
}


def profile(con, day="2026-09-20", officer="Officer A", status="Зареєстровано"):
    checked_at = day + "T12:00:00" if len(day) == 10 else day
    con.execute("""INSERT INTO supplier_edr_profiles
      (supplier_code,edr_status,edr_checked_at,edr_officer,synced_at)
      VALUES (?,?,?,?,?)""", (CODE, status, checked_at, officer, "old"))


def observe(con, day, officer, status="Зареєстровано", **fields):
    values = row(status=status, checked=day, officer=officer, manager="")
    for index, value in fields.items():
        values[int(index)] = value
    source = snapshot(values)
    preview = sync.build_preview(con, source)
    result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                        actor="audit", synced_at="2026-09-25T12:00:00")
    return preview, result


def current(con):
    state = sync.current_verification_projections(con, [CODE])[CODE]
    return sync.normalized_date(state["verification_date"]), state["verification_officer"]


def legacy_event(con, day="2026-09-20", officer="Officer A", status=""):
    evidence = {"source": "legacy_google_registry", "verification_date": day,
      "verification_officer": officer, "source_tab": "ФОП", "source_row": 2}
    if status:
        evidence.update(factual_edr_status=status,
          factual_spreadsheet_id="SYNTHETIC_AUTHORIZED", factual_source_tab="ФОП",
          factual_source_row=2, factual_provenance_version=1,
          source_digest="a" * 64, factual_source_digest="b" * 64)
    sync._insert_event(con, item={"supplier_code": CODE, "source_sheet": "ФОП", "source_row": 2},
      event_type="legacy_google_registry", occurred_at=day, officer=officer,
      source="legacy_google_registry", changed_fields=[], snapshot=evidence, created_at="old")


class PermanentSyncSafetyTests(unittest.TestCase):
    def setUp(self):
        self.con = database()
        sync.register_verification_sql_functions(self.con)

    def tearDown(self):
        self.con.close()

    def test_kyiv_timestamp_precision_and_same_day_ordering(self):
        valid = google_verification_instant("23.10.2026 17:03:19")
        self.assertEqual(valid["kind"], "datetime")
        self.assertTrue(incoming_verification_gate(
            "23.10.2026 17:03:20", "23.10.2026 17:03:19", require_time=True)["accepted"])
        self.assertEqual(incoming_verification_gate(
            "23.10.2026 17:03:19", "2026-10-23T14:03:19Z", require_time=True)["reason"], "equal")
        self.assertFalse(incoming_verification_gate(
            "23.10.2026 17:03:18", "23.10.2026 17:03:19", require_time=True)["accepted"])
        self.assertEqual(google_verification_instant("23.10.2026")["kind"], "date_only")
        self.assertEqual(google_verification_instant("23.10.2026 17:03")["kind"], "invalid")
        for ambiguous in ("29.03.2026 03:30:00", "25.10.2026 03:30:00"):
            self.assertEqual(google_verification_instant(ambiguous)["kind"], "invalid")
        self.assertFalse(incoming_verification_gate(
            "20.09.2026 12:00:01", "2026-09-20", require_time=True)["accepted"])
        self.assertTrue(incoming_verification_gate(
            "21.09.2026 00:00:00", "2026-09-20", require_time=True)["accepted"])

    def test_google_no_information_is_not_imported_as_factual_or_current_status(self):
        profile(self.con)
        preview, result = observe(self.con, "20.09.2026", "Officer A", status="Немає інформації")
        self.assertEqual(result["verification_events"], 0)
        self.assertEqual(preview["summary"]["edr_status_changes"], 0)
        self.assertEqual(self.con.execute("SELECT edr_status FROM supplier_edr_profiles").fetchone()[0],
                         "Зареєстровано")
        self.assertEqual(sync.active_edr_status("2026-01-01", [{
            "event_type": "google_clarity", "occurred_at": "2026-09-20",
            "snapshot_json": json.dumps({"edr_status": "Немає інформації"})}]), "Зареєстровано")

    def test_older_preserves_profile_only_current_pair(self):
        profile(self.con)
        preview, result = observe(self.con, "05.06.2026", "Officer B")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))
        self.assertEqual(result["verification_events"], 0)
        self.assertEqual(preview["summary"]["older_verification_preserved"], 1)

    def test_older_preserves_ledger_current_pair_and_profile(self):
        profile(self.con)
        legacy_event(self.con)
        observe(self.con, "05.06.2026", "Officer B")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))
        self.assertEqual(tuple(self.con.execute("SELECT edr_checked_at,edr_officer FROM supplier_edr_profiles").fetchone()),
                         ("2026-09-20T12:00:00", "Officer A"))

    def test_newer_pair_accepted(self):
        profile(self.con)
        preview, result = observe(self.con, "25.09.2026", "Officer B")
        self.assertEqual(current(self.con), ("2026-09-25", "Officer B"))
        self.assertEqual(result["verification_events"], 1)
        self.assertEqual(preview["summary"]["newer_verification_accepted"], 1)

    def test_same_day_same_officer_equivalent(self):
        profile(self.con)
        legacy_event(self.con)
        preview, result = observe(self.con, "20.09.2026", "Officer A")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))
        self.assertEqual(result["verification_events"], 0)
        self.assertEqual(preview["summary"]["same_date_same_officer_equivalent"], 1)

    def test_same_instant_preserves_officer_then_newer_second_wins(self):
        profile(self.con)
        legacy_event(self.con)
        sync._insert_event(self.con, item={"supplier_code": CODE}, event_type="manual_edr",
          occurred_at="2026-09-20", officer="Officer A", source="PQM manual",
          changed_fields=[], snapshot={"edr_status": "Зареєстровано"}, created_at="old")
        preview, result = observe(self.con, "20.09.2026", "Officer B")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))
        self.assertEqual(result["verification_events"], 0)
        self.assertEqual(preview["summary"]["same_datetime_officer_preserved"], 1)
        preview, result = observe(self.con, "20.09.2026 12:00:01", "Officer B")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer B"))
        self.assertEqual(result["verification_events"], 1)

    def test_older_larger_id_does_not_win(self):
        profile(self.con)
        legacy_event(self.con)
        sync._insert_event(self.con, item={"supplier_code": CODE}, event_type="google_clarity",
          occurred_at="2026-06-05", officer="Officer B", source="Google Sheets",
          changed_fields=[], snapshot={"supplier_code": CODE, "edr_status": "Зареєстровано"}, created_at="later")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))

    def test_controlled_factual_wins_same_day_and_older_ordinary_status(self):
        with patch.dict(os.environ, {"PQM_GOOGLE_REGISTRY_SPREADSHEET_ID": "SYNTHETIC_AUTHORIZED"}):
            for day in ("20.09.2026", "05.06.2026"):
                con = database()
                try:
                    sync.register_verification_sql_functions(con)
                    profile(con, status="Припинено")
                    legacy_event(con, status="Припинено")
                    preview, _ = observe(con, day, "Officer B")
                    ledger = [dict(event) for event in con.execute("SELECT * FROM supplier_edr_verification_events")]
                    self.assertEqual(sync.active_edr_status("2026-01-01", ledger), "Припинено")
                    self.assertEqual(preview["summary"]["factual_status_protected"], 1)
                    if day == "20.09.2026":
                        self.assertEqual(current(con), ("2026-09-20", "Officer A"))
                finally:
                    con.close()

    def test_google_full_mirror_clears_newer_blanks_and_preserves_history(self):
        profile(self.con, status="Припинено")
        self.con.execute("""UPDATE supplier_edr_profiles SET termination_decision_details='Old G',
          termination_record_date='2026-08-01',termination_record_number='Old K',edr_notes='Old M'""")
        preview, applied = observe(self.con, "25.09.2026", "Officer B")
        fields = self.con.execute("""SELECT termination_decision_details,termination_record_date,
          termination_record_number,edr_notes FROM supplier_edr_profiles""").fetchone()
        self.assertEqual(tuple(fields), ("", "", "", ""))
        self.assertEqual(preview["summary"]["google_mirror_clears"], 4)
        self.assertEqual(applied["termination_clears"], 1)
        self.assertEqual(applied["google_mirror_clears"], 4)
        self.assertEqual(applied["google_mirror_clear_events"], 1)
        historical = self.con.execute("SELECT event_type,snapshot_json FROM supplier_edr_verification_events WHERE event_type='google_mirror_clear'").fetchone()
        self.assertIsNotNone(historical)
        self.assertEqual(json.loads(historical[1])["previous_values"], {
            "termination_decision_details": "Old G", "termination_record_date": "2026-08-01",
            "termination_record_number": "Old K", "edr_notes": "Old M"})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events WHERE event_type='termination_historical'").fetchone()[0], 1)
        same_source = snapshot(row(checked="25.09.2026", officer="Officer B", manager=""))
        repeat = sync.apply(self.con, same_source, same_source["source_fingerprint"],
            confirmed=True, actor="audit", synced_at="2026-09-25T12:01:00")
        self.assertEqual((repeat["google_mirror_clears"], repeat["termination_clears"]), (0, 0))
        preview, _ = observe(self.con, "26.09.2026", "Officer B", **{"6": "New G", "9": "27.09.2026", "10": "New K", "12": "New M"})
        fields = self.con.execute("""SELECT termination_decision_details,termination_record_date,
          termination_record_number,edr_notes FROM supplier_edr_profiles""").fetchone()
        self.assertEqual(tuple(fields), ("New G", "2026-09-27", "New K", "New M"))
        self.assertEqual(preview["summary"]["google_mirror_updates"], 4)

    def test_each_gjkm_field_supports_both_directions_and_preview_shows_clear(self):
        for field, (column, old_value, new_value) in MIRROR_FIELDS.items():
            with self.subTest(field=field, direction="empty_to_value"):
                con = database()
                try:
                    profile(con)
                    source_row = row(checked="21.09.2026 13:00:00", officer="Officer B", manager="")
                    source_row[column] = new_value
                    source = snapshot(source_row)
                    plan = sync.build_preview(con, source)
                    decision = next(x for x in plan["items"][0]["mirror_field_changes"] if x["field"] == field)
                    self.assertEqual(decision["action"], "update")
                    result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                        actor="audit", synced_at="2026-09-25T12:00:00")
                    stored = con.execute(f"SELECT {field} FROM supplier_edr_profiles WHERE supplier_code=?", (CODE,)).fetchone()[0]
                    self.assertEqual(stored, sync.normalized_date(new_value) if field == "termination_record_date" else new_value)
                    self.assertEqual(result["google_mirror_clears"], 0)
                finally:
                    con.close()
            with self.subTest(field=field, direction="value_to_empty"):
                con = database()
                try:
                    profile(con)
                    con.execute(f"UPDATE supplier_edr_profiles SET {field}=? WHERE supplier_code=?", (old_value, CODE))
                    source_row = row(checked="21.09.2026 13:00:00", officer="Officer B", manager="")
                    source = snapshot(source_row)
                    plan = sync.build_preview(con, source)
                    decision = next(x for x in plan["items"][0]["mirror_field_changes"] if x["field"] == field)
                    self.assertEqual((decision["current"], decision["google"], decision["planned"], decision["action"]),
                                     (old_value, "", "", "clear"))
                    result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                        actor="audit", synced_at="2026-09-25T12:00:00")
                    self.assertEqual(con.execute(f"SELECT {field} FROM supplier_edr_profiles WHERE supplier_code=?", (CODE,)).fetchone()[0], "")
                    self.assertEqual(result["google_mirror_clears"], 1)
                    history = con.execute("SELECT snapshot_json FROM supplier_edr_verification_events WHERE event_type='google_mirror_clear'").fetchone()
                    self.assertEqual(json.loads(history[0])["previous_values"], {field: old_value})
                finally:
                    con.close()

    def test_gjkm_clear_is_blocked_for_older_equal_day_only_or_invalid_timestamp(self):
        cases = [
            ("19.09.2026 12:00:00", "older"),
            ("20.09.2026 12:00:00", "equal"),
            ("20.09.2026", "date_only"),
            ("bad timestamp", "invalid"),
        ]
        for checked, label in cases:
            with self.subTest(timestamp=label):
                con = database()
                try:
                    profile(con)
                    con.execute("UPDATE supplier_edr_profiles SET termination_decision_details='Old G',edr_notes='Old M'")
                    source = snapshot(row(checked=checked, officer="Officer B", manager="",
                                          date_only=(label == "date_only")))
                    plan = sync.build_preview(con, source)
                    self.assertTrue(any(x["field"] in {"termination_decision_details", "edr_notes"}
                                        and x["action"] == "blocked"
                                        for x in plan["items"][0]["mirror_field_changes"]))
                    self.assertTrue(plan["conflicts"])
                    before = con.total_changes
                    with self.assertRaises(ValueError):
                        sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                            actor="audit", synced_at="2026-09-25T12:00:00")
                    self.assertEqual(con.total_changes, before)
                    self.assertEqual(tuple(con.execute("SELECT termination_decision_details,edr_notes FROM supplier_edr_profiles").fetchone()),
                                     ("Old G", "Old M"))
                finally:
                    con.close()

    def test_missing_m_column_is_not_interpreted_as_an_explicit_blank(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='Old M'")
        source_row = row(checked="21.09.2026 13:00:00", officer="Officer B", manager="")[:12]
        source = snapshot(source_row)
        preview = sync.build_preview(self.con, source)
        self.assertIn("missing_source_column:Примітки", preview["conflicts"][0]["reasons"])
        decision = next(x for x in preview["items"][0]["mirror_field_changes"] if x["field"] == "edr_notes")
        self.assertEqual(decision["action"], "blocked")
        before = self.con.total_changes
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                actor="audit", synced_at="2026-09-25T12:00:00")
        self.assertEqual(self.con.total_changes, before)
        self.assertEqual(self.con.execute("SELECT edr_notes FROM supplier_edr_profiles").fetchone()[0], "Old M")

    def test_gjkm_only_can_mirror_without_verification_pair(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET edr_notes='Confirmed note'")
        source = snapshot(row(checked="", officer="", manager=""))
        source["rows"][0]["Примітки"] = "New M"
        preview = sync.build_preview(self.con, source)
        self.assertIn("verification_date_required", preview["conflicts"][0]["reasons"])
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                       actor="audit", synced_at="2026-09-25T12:00:00")
        self.assertEqual(self.con.execute("SELECT edr_notes FROM supplier_edr_profiles").fetchone()[0], "Confirmed note")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))

    def test_same_day_later_verified_manager_timestamp_is_accepted(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET manager_name='Old Manager'")
        source = snapshot(row(checked="20.09.2026 12:00:01", officer="Officer A", manager="New Manager"))
        preview = sync.build_preview(self.con, source)
        self.assertEqual(preview["items"][0]["datetime_gate"]["reason"], "newer")
        sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                   actor="audit", synced_at="2026-09-25T12:00:00")
        self.assertEqual(self.con.execute("SELECT manager_name FROM supplier_edr_profiles").fetchone()[0], "New Manager")

    def test_day_only_google_date_is_not_a_verification_timestamp(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET edr_checked_at='2026-09-20T15:00:00+03:00',manager_name='Old Manager'")
        source = snapshot(row(checked="20.09.2026", officer="Officer B", manager="New Manager", date_only=True))
        preview = sync.build_preview(self.con, source)
        self.assertIn("verification_timestamp_required", preview["conflicts"][0]["reasons"])
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                       actor="audit", synced_at="2026-09-25T12:00:00")
        stored = self.con.execute("SELECT manager_name,edr_checked_at FROM supplier_edr_profiles").fetchone()
        self.assertEqual(tuple(stored), ("Old Manager", "2026-09-20T15:00:00+03:00"))

    def test_missing_current_verification_date_does_not_replace_existing_facts(self):
        self.con.execute("""INSERT INTO supplier_edr_profiles(supplier_code,manager_name,edr_status,full_name,synced_at)
          VALUES (?,?,?,?,?)""", (CODE, "Old Manager", "Зареєстровано", "Old legal name", "old"))
        source = snapshot(row(checked="21.09.2026", officer="Officer B", manager="New Manager"))
        preview = sync.build_preview(self.con, source)
        self.assertIn("current_verification_date_missing", preview["conflicts"][0]["reasons"])
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                       actor="audit", synced_at="2026-09-25T12:00:00")
        stored = self.con.execute("SELECT manager_name,full_name FROM supplier_edr_profiles").fetchone()
        self.assertEqual(tuple(stored), ("Old Manager", "Old legal name"))

    def test_malformed_date_blocks_without_writes(self):
        profile(self.con)
        source = snapshot(row(checked="not-a-date", officer="Officer B", manager=""))
        preview = sync.build_preview(self.con, source)
        self.assertIn("malformed_verification_date", preview["conflicts"][0]["reasons"])
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                       actor="audit", synced_at="2026-09-25T12:00:00")
        self.assertEqual(current(self.con), ("2026-09-20", "Officer A"))

    def test_malformed_google_record_date_cannot_look_like_intentional_clear(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET termination_record_date='2026-08-01'")
        source = snapshot(row(checked="20.09.2026", officer="Officer A", manager=""))
        source["rows"][0]["Дата запису"] = "not-a-date"
        preview = sync.build_preview(self.con, source)
        self.assertIn("malformed_termination_record_date", preview["conflicts"][0]["reasons"])
        with self.assertRaises(ValueError):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
                       actor="audit", synced_at="2026-09-25T12:00:00")
        self.assertEqual(self.con.execute("SELECT termination_record_date FROM supplier_edr_profiles").fetchone()[0], "2026-08-01")

    def test_older_name_and_manager_do_not_replace_newer_profile(self):
        profile(self.con)
        self.con.execute("UPDATE supplier_edr_profiles SET full_name='Current',short_name='Current short',manager_name='Current manager'")
        old_row = row(checked="05.06.2026", officer="Officer B", manager="Old manager")
        old_row[13], old_row[14] = "Old name", "Old short"
        source = snapshot(old_row)
        preview = sync.build_preview(self.con, source)
        values = self.con.execute("SELECT full_name,short_name,manager_name FROM supplier_edr_profiles").fetchone()
        self.assertEqual(tuple(values), ("Current", "Current short", "Current manager"))
        self.assertEqual(preview["items"][0]["manager_change_kind"], "same")


if __name__ == "__main__":
    unittest.main()
