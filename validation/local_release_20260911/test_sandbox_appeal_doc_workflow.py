"""Local-only workflow tests: no Google connector and no generated documents."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
import sandbox_google_docs_access as access


class SandboxAppealGoogleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.temp.name) / "sandbox.sqlite3"
        with sqlite3.connect(self.path) as con:
            con.executescript("""
                CREATE TABLE sandbox_violation_google_docs (
                  id TEXT PRIMARY KEY,report_id TEXT NOT NULL,document_id TEXT NOT NULL DEFAULT '',
                  document_name TEXT NOT NULL DEFAULT '',template_id TEXT NOT NULL,
                  destination_folder_id TEXT NOT NULL,source_digest TEXT NOT NULL,
                  status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            """)
        self.context = {"item": {"id": "report-1"},
            "gate": {"protocol_type": "warning"},
            "values": {"report_id": "report-1", "protocol_number": "9",
                       "customer_short_name": "Замовник", "supplier_short_name": "Постачальник",
                       "supplier_code": "00123456"}, "flags": {}}
        self.preflight = {"template_id": access.WARNING_TEMPLATE_ID,
            "destination_folder_id": access.SANDBOX_FOLDER_ID,
            "name": "report-1_9_П_Замовник_Постачальник (00123456)",
            "replacements": {"{{ report_id }}": "report-1"},
            "source_revision_id": "rev-1"}
        self.patches = [
            patch.object(server, "SANDBOX_MODE", True),
            patch.object(server, "DB_PATH", self.path),
            patch.object(server, "generate_violation_protocol", return_value=self.context),
            patch.object(server, "sandbox_appeal_docs_access_check", return_value={"ready_for_single_generation_test": True}),
            patch.object(server, "_google_access_token", return_value="test-only-token"),
            patch.object(server.sandbox_appeal_google_docs, "preflight_document", return_value=self.preflight),
        ]
        for candidate in self.patches:
            candidate.start()

    def tearDown(self):
        for candidate in reversed(self.patches):
            candidate.stop()
        self.temp.cleanup()

    def test_success_and_repeat_is_idempotent(self):
        calls = []
        def create(protocol_type, values, token, opener, on_copied, **kwargs):
            calls.append(protocol_type)
            on_copied("sandbox_generated_doc_1234567890", kwargs["preflight"])
            return {"document_id": "sandbox_generated_doc_1234567890",
                "document_url": "https://docs.google.com/document/d/sandbox_generated_doc_1234567890/edit",
                "name": self.preflight["name"]}
        with patch.object(server.sandbox_appeal_google_docs, "create_document", side_effect=create):
            first = server.generate_sandbox_violation_google_doc("report-1", {})
            second = server.generate_sandbox_violation_google_doc("report-1", {})
        self.assertEqual(calls, ["warning"])
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT status,document_id FROM sandbox_violation_google_docs").fetchall(),
                [("complete", "sandbox_generated_doc_1234567890")])

    def test_uncertain_copy_blocks_blind_retry(self):
        def fail_after_copy(protocol_type, values, token, opener, on_copied, **kwargs):
            on_copied("sandbox_generated_doc_1234567890", kwargs["preflight"])
            raise RuntimeError("ambiguous update")
        with patch.object(server.sandbox_appeal_google_docs, "create_document", side_effect=fail_after_copy):
            with self.assertRaises(RuntimeError):
                server.generate_sandbox_violation_google_doc("report-1", {})
            with self.assertRaisesRegex(RuntimeError, "reconcile"):
                server.generate_sandbox_violation_google_doc("report-1", {})
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT status FROM sandbox_violation_google_docs").fetchone()[0],
                             "uncertain")

    def test_access_failure_creates_no_attempt(self):
        with patch.object(server, "sandbox_appeal_docs_access_check", side_effect=PermissionError("scope")):
            with self.assertRaises(PermissionError):
                server.generate_sandbox_violation_google_doc("report-1", {})
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sandbox_violation_google_docs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
