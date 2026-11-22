import unittest

import edr_sync_v2 as sync
from test_edr_sync_v2 import database, row, snapshot


def set_cell(values, index, value):
    values[index] = value
    return values


def seed_profile(con, code, *, checked="2026-09-01T09:00:00+03:00", manager="Старий керівник",
                 full_name="Стара назва", short_name="Стара скорочена", status="Зареєстровано",
                 g="Старі реквізити", j="2026-08-01", k="Старий номер", m="Старі примітки"):
    con.execute("""INSERT INTO supplier_edr_profiles
      (supplier_code,manager_name,full_name,short_name,edr_status,edr_checked_at,
       termination_decision_details,termination_record_date,termination_record_number,
       edr_notes,edr_officer,source_sheet,source_row,synced_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (code, manager, full_name, short_name, status, checked, g, j, k, m,
       "Попередня УО", "ЮО", 2, "old-sync"))


class EdrPreviewSkipContractTests(unittest.TestCase):
    def test_mass_undated_rows_skip_without_business_or_receipt_writes(self):
        con = database()
        for code in ("11111111", "22222222", "33333333", "38261938"):
            seed_profile(con, code)
        rows = [
            row(code="11111111", checked="29.10.2026", manager="Застарілий керівник"),
            row(code="22222222", checked="", manager="Невідомий керівник"),
            row(code="33333333", checked="not-a-date", manager="Сумнівний керівник"),
            row(code="38261938", checked="29.10.2026 14:27:49",
                manager="Парфенюк Сергій Сергійович"),
        ]
        for values in rows[:3]:
            values[4] = "Припинено"
            values[6], values[9], values[10], values[12] = "Нові G", "30.10.2026", "Новий K", "Нові M"
        rows[3][6], rows[3][9], rows[3][10], rows[3][12] = "", "", "", ""
        source = snapshot(*rows)
        before = {r[0]: tuple(r[1:]) for r in con.execute("""SELECT supplier_code,manager_name,
          full_name,short_name,edr_status,edr_checked_at,termination_decision_details,
          termination_record_date,termination_record_number,edr_notes,edr_officer,source_sheet,
          source_row,synced_at FROM supplier_edr_profiles""")}
        plan = sync.build_preview(con, source)
        self.assertEqual((plan["summary"]["eligible"], plan["summary"]["skipped"],
                          plan["summary"]["conflict"]), (1, 3, 0))
        reasons = [item["datetime_gate"]["reason"] for item in plan["items"][:3]]
        self.assertEqual(reasons, ["incoming_date_only", "incoming_blank", "incoming_invalid"])
        reconciled = []
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
            actor="test", synced_at="2026-10-30T12:00:00+02:00",
            sync_manager=lambda *args: {"changed": True},
            reconcile_manager_nazk=lambda _con, code: reconciled.append(code))
        self.assertEqual(result["skipped_no_verification_timestamp"], 3)
        self.assertEqual(result["manager_identity_changes"], 1)
        self.assertEqual(reconciled, ["38261938"])
        after = {r[0]: tuple(r[1:]) for r in con.execute("""SELECT supplier_code,manager_name,
          full_name,short_name,edr_status,edr_checked_at,termination_decision_details,
          termination_record_date,termination_record_number,edr_notes,edr_officer,source_sheet,
          source_row,synced_at FROM supplier_edr_profiles""")}
        for code in ("11111111", "22222222", "33333333"):
            self.assertEqual(after[code], before[code])
        control = con.execute("""SELECT manager_name,full_name,edr_checked_at,
          termination_decision_details,termination_record_date,termination_record_number,edr_notes
          FROM supplier_edr_profiles WHERE supplier_code='38261938'""").fetchone()
        self.assertEqual(tuple(control), (
            "Парфенюк Сергій Сергійович", "ПОВНА НАЗВА",
            "2026-10-29T14:27:49+02:00", "", "", "", ""))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events WHERE supplier_code='38261938' AND event_type='google_clarity'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events WHERE supplier_code IN ('11111111','22222222','33333333')").fetchone()[0], 0)

    def test_real_conflict_blocks_otherwise_eligible_apply_atomically(self):
        con = database()
        seed_profile(con, "11111111")
        seed_profile(con, "22222222", checked="2026-10-29T14:27:49+02:00")
        good = row(code="11111111", checked="29.10.2026 14:27:50", manager="Новий керівник")
        stale = row(code="22222222", checked="29.10.2026 14:27:49", manager="Старий керівник")
        stale[4] = "Припинено"
        source = snapshot(good, stale)
        before = [tuple(r) for r in con.execute("SELECT supplier_code,manager_name,edr_status,edr_checked_at FROM supplier_edr_profiles ORDER BY supplier_code")]
        preview = sync.build_preview(con, source)
        self.assertEqual((preview["summary"]["eligible"], preview["summary"]["conflict"]), (1, 1))
        callbacks = []
        with self.assertRaises(ValueError):
            sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                actor="test", synced_at="2026-10-30T12:00:00+02:00",
                sync_manager=lambda *args: callbacks.append("manager") or {"changed": True})
        after = [tuple(r) for r in con.execute("SELECT supplier_code,manager_name,edr_status,edr_checked_at FROM supplier_edr_profiles ORDER BY supplier_code")]
        self.assertEqual(after, before)
        self.assertEqual(callbacks, [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_apply_rechecks_state_digest_before_any_write(self):
        con = database()
        seed_profile(con, "38261938")
        source = snapshot(row(code="38261938", checked="29.10.2026 14:27:49",
                              manager="Парфенюк Сергій Сергійович"))
        preview = sync.build_preview(con, source)
        digest = sync.preview_state_digest(preview)
        con.execute("UPDATE supplier_edr_profiles SET edr_notes='concurrent change' WHERE supplier_code='38261938'")
        before = tuple(con.execute("SELECT manager_name,edr_checked_at,edr_notes FROM supplier_edr_profiles WHERE supplier_code='38261938'").fetchone())
        with self.assertRaisesRegex(RuntimeError, "state changed"):
            sync.apply(con, source, source["source_fingerprint"], confirmed=True,
                actor="test", synced_at="2026-10-30T12:00:00+02:00",
                expected_state_digest=digest)
        self.assertEqual(tuple(con.execute("SELECT manager_name,edr_checked_at,edr_notes FROM supplier_edr_profiles WHERE supplier_code='38261938'").fetchone()), before)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_blank_cell_is_not_a_missing_column_and_header_contract_remains_exact(self):
        values = row(code="38261938", checked="29.10.2026 14:27:49")
        values[8] = ""
        source = snapshot(values)
        self.assertEqual(source["rows"][0]["Дата перевірки"], "")
        wrong_headers = list(sync.HEADERS)
        wrong_headers[0] = "непогоджена колонка"
        with self.assertRaisesRegex(ValueError, "canonical mapping"):
            sync.source_snapshot({"ФОП": [wrong_headers], "ЮО": [list(sync.HEADERS)]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
