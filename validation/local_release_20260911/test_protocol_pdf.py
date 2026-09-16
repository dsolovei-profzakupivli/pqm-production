import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document

import protocol_pdf
import server


class ProtocolPdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.docx = self.root / "protocol.docx"
        self.docx.write_bytes(b"test docx")

    def tearDown(self):
        self.temp.cleanup()

    def test_pdf_is_exported_atomically_and_cached(self):
        output = self.root / "pdf" / "result.pdf"
        calls = []

        def export(source, target, executable):
            calls.append((source, executable))
            target.write_bytes(b"%PDF-1.7\ncontrol")

        with patch.object(protocol_pdf, "_running_on_windows", return_value=False), \
                patch.object(protocol_pdf, "_soffice_executable", return_value="soffice"), \
                patch.object(protocol_pdf, "_export_with_libreoffice", side_effect=export):
            self.assertEqual(protocol_pdf.ensure_pdf(self.docx, output), output.resolve())
            self.assertEqual(protocol_pdf.ensure_pdf(self.docx, output), output.resolve())
        self.assertEqual(len(calls), 1)
        self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
        self.assertEqual(list(output.parent.glob(".*.tmp.pdf")), [])

    def test_invalid_renderer_output_is_not_published(self):
        output = self.root / "result.pdf"

        def export(_source, target, _executable):
            target.write_bytes(b"not a pdf")

        with patch.object(protocol_pdf, "_running_on_windows", return_value=False), \
                patch.object(protocol_pdf, "_soffice_executable", return_value="soffice"), \
                patch.object(protocol_pdf, "_export_with_libreoffice", side_effect=export):
            with self.assertRaisesRegex(RuntimeError, "некоректний файл"):
                protocol_pdf.ensure_pdf(self.docx, output)
        self.assertFalse(output.exists())

    def test_windows_prefers_word_and_marks_faithful_cache(self):
        output = self.root / "result.pdf"
        calls = []

        def export(source, target):
            calls.append(source)
            target.write_bytes(b"%PDF-1.7\nword")

        with patch.object(protocol_pdf, "_running_on_windows", return_value=True), \
                patch.object(protocol_pdf, "_word_available", return_value=True), \
                patch.object(protocol_pdf, "_export_with_word", side_effect=export), \
                patch.object(protocol_pdf, "_soffice_executable", return_value=None):
            protocol_pdf.ensure_pdf(self.docx, output)
            protocol_pdf.ensure_pdf(self.docx, output)
        self.assertEqual(len(calls), 1)
        self.assertEqual(output.with_suffix(".pdf.converter").read_text(), "word_com")

    def test_unmarked_approximate_cache_is_never_reused(self):
        output = self.root / "result.pdf"
        output.write_bytes(b"%PDF-1.7\nold chromium")
        output.touch()
        calls = []

        def export(_source, target):
            calls.append(True)
            target.write_bytes(b"%PDF-1.7\nword")

        with patch.object(protocol_pdf, "_running_on_windows", return_value=True), \
                patch.object(protocol_pdf, "_word_available", return_value=True), \
                patch.object(protocol_pdf, "_export_with_word", side_effect=export), \
                patch.object(protocol_pdf, "_soffice_executable", return_value=None):
            protocol_pdf.ensure_pdf(self.docx, output)
        self.assertEqual(calls, [True])
        self.assertEqual(output.read_bytes(), b"%PDF-1.7\nword")

    def test_no_fidelity_converter_returns_clear_error(self):
        output = self.root / "result.pdf"
        with patch.object(protocol_pdf, "_running_on_windows", return_value=False), \
                patch.object(protocol_pdf, "_soffice_executable", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "не знайдено Microsoft Word або LibreOffice"):
                protocol_pdf.ensure_pdf(self.docx, output)
        self.assertFalse(output.exists())

    def test_report_protocol_pdf_uses_business_filename_suffixes(self):
        old_db, old_protocols = server.DB_PATH, server.PROTOCOLS_DIR
        try:
            server.DB_PATH = self.root / "server.sqlite3"
            server.PROTOCOLS_DIR = self.root / "protocols"
            server.init_db()
            server.save_violation_report({
                "id": "report-internal", "violationReportID": "UA-D-2026-09-07-000001",
                "status": "pending", "datePublished": "2026-09-07", "dateModified": "2026-09-07",
                "tender_id": "tender", "author": {"identifier": {"id": "11111111"}},
                "defendants": [{"identifier": {"id": "22222222"}}],
                "authority": {"identifier": {"id": "40996564"}},
                "details": {"reason": "contractBreach", "documents": []},
            })
            server.PROTOCOLS_DIR.mkdir(parents=True)
            source = server.PROTOCOLS_DIR / "current.docx"
            source.write_bytes(b"docx")
            with server.db() as connection:
                connection.execute("""INSERT INTO violation_report_reviews
                    (report_id,internal_decision,protocol_number,generated_protocol_filename,updated_at,updated_by)
                    VALUES (?,?,?,?,?,?)""", (
                    "report-internal", "warning", "670/26", source.name, server.now_iso(), "УО"))
            with patch.object(server.protocol_pdf, "ensure_pdf", side_effect=lambda _source, target: Path(target)):
                path, filename = server.violation_protocol_pdf("report-internal")
            self.assertEqual(filename, "UA-D-2026-09-07-000001_670_26_П.pdf")
            self.assertEqual(path.name, filename)
            with server.db() as connection:
                connection.execute("UPDATE violation_report_reviews SET internal_decision='decline_p49_1_2'")
            with patch.object(server.protocol_pdf, "ensure_pdf", side_effect=lambda _source, target: Path(target)):
                _path, filename = server.violation_protocol_pdf("UA-D-2026-09-07-000001")
            self.assertEqual(filename, "UA-D-2026-09-07-000001_670_26_В.pdf")
        finally:
            server.DB_PATH, server.PROTOCOLS_DIR = old_db, old_protocols

    def test_http_pdf_route_is_not_captured_by_detail_route(self):
        pdf = self.root / "ready.pdf"
        pdf.write_bytes(b"%PDF-1.7\nroute")
        handler = object.__new__(server.Handler)
        handler.path = "/api/violation-reports/report-internal/protocol/pdf"
        handler.command = "GET"
        handler.headers = {}
        handler.auth_user = "fixture"
        handler.auth_role = "admin"
        handler.auth_officer_id = None
        handler.wfile = io.BytesIO()
        status, headers = [], {}
        handler.send_response = status.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        with patch.object(handler, "_authorize", return_value=True), \
                patch.object(server, "db", side_effect=lambda: contextlib.nullcontext(None)), \
                patch.object(server.auth_access, "effective", return_value={
                    "active": True, "permissions": {"appeals.read": True}}), \
                patch.object(server, "violation_protocol_pdf", return_value=(pdf, "UA-D-TEST_670_П.pdf")):
            handler.do_GET()
        self.assertEqual(status, [200])
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("UA-D-TEST_670_%D0%9F.pdf", headers["Content-Disposition"])
        self.assertTrue(handler.wfile.getvalue().startswith(b"%PDF-"))

    def test_http_pdf_failure_is_json_and_never_advertised_as_download(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/violation-reports/report-internal/protocol/pdf"
        handler.command = "GET"
        handler.headers = {}
        handler.auth_user = "fixture"
        handler.auth_role = "admin"
        handler.auth_officer_id = None
        handler.wfile = io.BytesIO()
        status, headers = [], {}
        handler.send_response = status.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        with patch.object(handler, "_authorize", return_value=True), \
                patch.object(server, "db", side_effect=lambda: contextlib.nullcontext(None)), \
                patch.object(server.auth_access, "effective", return_value={
                    "active": True, "permissions": {"appeals.read": True}}), \
                patch.object(server, "violation_protocol_pdf", side_effect=RuntimeError("converter failed")), \
                patch.object(server.SERVER_LOG, "exception"):
            handler.do_GET()
        self.assertEqual(status, [503])
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertNotIn("Content-Disposition", headers)
        self.assertIn(b'"code": "protocol_pdf_generation_failed"', handler.wfile.getvalue())

    def test_amcu_http_pdf_uses_exact_generated_source_and_business_filename(self):
        source = self.root / "АМКУ_2884318089_701_v2.docx"
        pdf = self.root / "АМКУ_2884318089_701_v2.pdf"
        source.write_bytes(b"docx");pdf.write_bytes(b"%PDF-1.7\namcu")
        handler = object.__new__(server.Handler)
        handler.path = "/api/operational-tasks/" + "a"*32 + "/documents/" + "b"*32 + "/pdf"
        handler.command = "GET";handler.headers = {};handler.auth_user = "fixture"
        handler.auth_role = "admin";handler.auth_officer_id = None;handler.wfile = io.BytesIO()
        status, headers = [], {}
        handler.send_response = status.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        with patch.object(handler, "_authorize", return_value=True), \
                patch.object(server.auth_access, "effective", return_value={
                    "active": True, "permissions": {"tasks.read": True}}), \
                patch.object(server, "db", side_effect=lambda: contextlib.nullcontext(None)), \
                patch.object(server.task_documents, "amcu_pdf_source", return_value=(
                    source, "Протокол № 701 від 15.09.2026 (пп. 7 п. 40).pdf")) as resolve, \
                patch.object(server.protocol_pdf, "ensure_pdf", return_value=pdf) as convert:
            handler.do_GET()
        self.assertEqual(status, [200]);self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("%D0%9F%D1%80%D0%BE%D1%82%D0%BE%D0%BA%D0%BE%D0%BB", headers["Content-Disposition"])
        self.assertTrue(handler.wfile.getvalue().startswith(b"%PDF-"))
        resolve.assert_called_once();convert.assert_called_once_with(source, source.with_suffix(".pdf"))

    def test_amcu_http_pdf_failure_is_json_without_content_disposition(self):
        source = self.root / "source.docx";source.write_bytes(b"docx")
        handler = object.__new__(server.Handler)
        handler.path = "/api/operational-tasks/" + "a"*32 + "/documents/" + "b"*32 + "/pdf"
        handler.command = "GET";handler.headers = {};handler.auth_user = "fixture"
        handler.auth_role = "admin";handler.auth_officer_id = None;handler.wfile = io.BytesIO()
        status, headers = [], {}
        handler.send_response = status.append
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None
        with patch.object(handler, "_authorize", return_value=True), \
                patch.object(server.auth_access, "effective", return_value={
                    "active": True, "permissions": {"tasks.read": True}}), \
                patch.object(server, "db", side_effect=lambda: contextlib.nullcontext(None)), \
                patch.object(server.task_documents, "amcu_pdf_source", return_value=(source, "protocol.pdf")), \
                patch.object(server.protocol_pdf, "ensure_pdf", side_effect=RuntimeError("converter unavailable")), \
                patch.object(server.SERVER_LOG, "exception"):
            handler.do_GET()
        self.assertEqual(status, [503]);self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertNotIn("Content-Disposition", headers)
        self.assertIn(b'"code": "protocol_pdf_generation_failed"', handler.wfile.getvalue())


if __name__ == "__main__":
    unittest.main()
