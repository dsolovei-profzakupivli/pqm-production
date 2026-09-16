import io
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

import server


class FinalLocalStabilizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def seed_application(self, submission_id, status, framework_officer, protocol_officer=""):
        with server.db() as con:
            framework = f"f-{submission_id}"
            qualification = f"q-{submission_id}"
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES (?,?,?,'{}',?)",
                        (framework, framework, "active", server.now_iso()))
            con.execute("INSERT INTO framework_officers(framework_id,officer,synced_at) VALUES (?,?,?)",
                        (framework, framework_officer, server.now_iso()))
            con.execute("""INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,
                         date_published,documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,?,'[]','{}',?)""",
                        (submission_id, framework, qualification, submission_id, "Supplier",
                         "2026-08-25T10:00:00+03:00", server.now_iso()))
            con.execute("""INSERT INTO qualifications(id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
                         VALUES (?,?,?,?,'[]','{}',?)""",
                        (qualification, framework, submission_id, status, server.now_iso()))
            con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES (?,?)",
                        (submission_id, protocol_officer))

    def effective_officers(self):
        with server.db() as con:
            return {row["id"]: row["officer"] for row in con.execute(f"""SELECT s.id,
              {server.effective_officer_sql()} officer FROM submissions s
              LEFT JOIN qualifications q ON q.id=s.qualification_id
              LEFT JOIN application_fields af ON af.submission_id=s.id
              LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id""")}

    def test_effective_officer_pending_tracks_framework_completed_is_frozen(self):
        self.seed_application("pending", "pending", "Officer A")
        self.seed_application("completed", "active", "Officer A", "Officer B")
        first = self.effective_officers()
        self.assertEqual(first["pending"], "Officer A")
        self.assertEqual(first["completed"], "Officer B")
        with server.db() as con:
            con.execute("UPDATE framework_officers SET officer='Officer C'")
        second = self.effective_officers()
        self.assertEqual(second["pending"], "Officer C")
        self.assertEqual(second["completed"], "Officer B")

    def test_completed_without_protocol_officer_is_unassigned(self):
        self.seed_application("completed", "unsuccessful", "Officer A")
        self.assertEqual(self.effective_officers()["completed"], "")

    def test_legal_reference_natural_sort(self):
        items = [{"id": index, "point": point, "category": ""} for index, point in enumerate(
            ["п. 10", "абз. 2 п. 5.1", "п. 2", "п. 5.2", "п. 5.1", "абз. 1 п. 5.1"], 1)]
        self.assertEqual([item["point"] for item in sorted(items, key=server.legal_reference_sort_key)],
                         ["п. 2", "п. 5.1", "абз. 1 п. 5.1", "абз. 2 п. 5.1", "п. 5.2", "п. 10"])

    def test_edr_export_has_exact_headers_and_derived_values(self):
        with server.db() as con:
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,source_sheet,source_row,synced_at,
               termination_decision_details,edr_officer,edr_notes)
              VALUES ('1234567890','ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ ТЕСТ','ФОП ТЕСТ','КЕРІВНИК','Зареєстровано',
              '01.08.2026','ФОП',2,?,'Дата запису: 02.03.2020 Номер запису: 123','УО ТЕСТ','Примітка')""",
              (server.now_iso(),))
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES ('f-export','f-export','active','{}',?)",
                        (server.now_iso(),))
            con.execute("""INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,
              date_published,documents_json,raw_json,synced_at) VALUES
              ('s-export','f-export','q-export','1234567890','ФОП ТЕСТ','2026-08-01','[]','{}',?)""",
                        (server.now_iso(),))
            con.execute("""INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,
              documents_json,raw_json,synced_at) VALUES
              ('q-export','f-export','s-export','active','2026-08-02','[]','{}',?)""",
                        (server.now_iso(),))
            con.execute("""INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,
              milestones_json,raw_json,synced_at) VALUES
              ('rc-export','f-export','q-export','1234567890','active','[]','{}',?)""", (server.now_iso(),))
        rows = server.build_supplier_edr_export_rows("ФОП", today=date(2026, 8, 20))
        self.assertEqual(list(rows[0]), server.EDR_EXPORT_HEADERS)
        self.assertEqual(rows[0]["Код ЄДРПОУ"], "1234567890")
        self.assertEqual(rows[0]["Стара Назва"], "ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ ТЕСТ")
        self.assertEqual(rows[0]["Фактична дата перевірки ЄДР"], "2026-08-01 00:00:00")
        self.assertTrue(server.supplier_edr_export_csv("ФОП").startswith(b"\xef\xbb\xbf"))

    def test_edr_export_population_requires_historical_admission_not_current_active(self):
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES ('f-pop','f-pop','complete','{}',?)",
                        (server.now_iso(),))
            for suffix, code, status in (("old", "1111111111", "active"), ("new", "2222222222", "pending")):
                con.execute("""INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,
                  date_published,documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,'2026-01-01','[]','{}',?)""",
                            (f"s-{suffix}", "f-pop", f"q-{suffix}", code,
                             f"ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ {suffix}", server.now_iso()))
                con.execute("""INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,
                  documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,'[]','{}',?)""",
                            (f"q-{suffix}", "f-pop", f"s-{suffix}", status, "2026-01-02", server.now_iso()))
            con.execute("""INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,
              milestones_json,raw_json,synced_at) VALUES
              ('rc-old','f-pop','q-old','1111111111','terminated','[]','{}',?)""", (server.now_iso(),))
        default_rows = server.build_supplier_edr_export_rows("ФОП", today=date(2026, 8, 20))
        self.assertNotIn("1111111111", {row["Код ЄДРПОУ"] for row in default_rows})
        selected = server.build_supplier_edr_export_rows("ФОП", today=date(2026, 8, 20), filters={
            "supplier_codes": {"1111111111"}, "selected_mode": True,
        })
        self.assertEqual([row["Код ЄДРПОУ"] for row in selected], ["1111111111"])

    def test_edr_export_uses_registry_qualification_when_submission_pointer_is_stale(self):
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES ('f-multi','f-multi','active','{}',?)",
                        (server.now_iso(),))
            con.execute("""INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,
              date_published,documents_json,raw_json,synced_at) VALUES
              ('s-multi','f-multi','q-pending','3069605914','ФОП МЕЛЬНИЧЕНКО ІВАН РОМАНОВИЧ',
               '2023-11-23','[]','{}',?)""", (server.now_iso(),))
            for qualification_id, status in (("q-pending", "pending"), ("q-active", "active")):
                con.execute("""INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,
                  documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,'[]','{}',?)""",
                            (qualification_id, "f-multi", "s-multi", status, "2023-12-10", server.now_iso()))
            con.execute("""INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,
              milestones_json,raw_json,synced_at) VALUES
              ('rc-multi','f-multi','q-active','3069605914','active','[]','{}',?)""", (server.now_iso(),))
        rows = server.build_supplier_edr_export_rows("ФОП", today=date(2026, 8, 20))
        row = next(item for item in rows if item["Код ЄДРПОУ"] == "3069605914")
        self.assertEqual(row["Стара Назва"], "ФОП МЕЛЬНИЧЕНКО ІВАН РОМАНОВИЧ")

    def test_supplier_note_tables_are_additive_and_auditable(self):
        with server.db() as con:
            con.execute("INSERT INTO supplier_notes VALUES ('12345678','Note',?,?)", (server.now_iso(), "Officer"))
            con.execute("INSERT INTO supplier_note_events(supplier_code,old_note,new_note,changed_at,changed_by) VALUES ('12345678','','Note',?,?)",
                        (server.now_iso(), "Officer"))
            self.assertEqual(con.execute("SELECT note FROM supplier_notes").fetchone()[0], "Note")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_note_events").fetchone()[0], 1)

    def test_archive_document_retries_429_then_succeeds(self):
        calls, waits = [], []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()
        def opener(*_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("https://example.test/file", 429, "rate", {"Retry-After": "3"}, None)
            return Response(b"document")
        data, attempts = server._download_archive_document(
            {"url": "https://example.test/file"}, opener=opener, sleeper=waits.append)
        self.assertEqual(data, b"document")
        self.assertEqual(attempts, 2)
        self.assertEqual(waits, [3.0])

    def test_archive_document_reports_429_after_all_retries(self):
        calls, waits = [], []
        def opener(*_args, **_kwargs):
            calls.append(1)
            raise urllib.error.HTTPError("https://example.test/file", 429, "rate", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            server._download_archive_document(
                {"url": "https://example.test/file"}, opener=opener, sleeper=waits.append)
        self.assertEqual(len(calls), 5)
        self.assertEqual(waits, [2.0, 4.0, 8.0, 16.0])


if __name__ == "__main__":
    unittest.main()
