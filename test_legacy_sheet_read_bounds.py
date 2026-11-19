"""Bounded read-only Google Sheets access for the fixed legacy audit."""
import ast
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import google_writer_execution as execution
import test_partial_reconciliation_legacy_20261108 as legacy_fixture

FINGERPRINT = legacy_fixture.FINGERPRINT


def load_preflight_functions():
    source_path = Path(__file__).with_name("server.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names = {"_google_writer_legacy_read_sheet_values",
             "_google_writer_legacy_live_sheet_preflight"}
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != names:
        raise AssertionError("Could not locate the pinned legacy sheet preflight functions")
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {
        "DB_PATH": "unused-read-only-test-path",
        "google_writer_execution": execution,
        "json": json,
        "re": re,
        "urllib": SimpleNamespace(parse=urllib.parse, request=urllib.request,
                                   error=urllib.error),
        "sandbox_runtime": SimpleNamespace(SANDBOX_EDR_SPREADSHEET_ID="sandbox-sheet"),
    }
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class LegacySheetReadBoundsTests(unittest.TestCase):
    def setUp(self):
        self.preflight = load_preflight_functions()
        fixture = legacy_fixture.LegacyAppendOnlyReconciliation20261108Tests()
        fixture.details = fixture._make_details()
        self.expected_rows = fixture.details["appends"][:25]
        self.full_rows = fixture._matrices()
        self.code_rows = {
            tab: [[row[1]] for row in rows]
            for tab, rows in self.full_rows.items()
        }
        self.request_ranges = []

    def _fake_read(self, tab, token, a1_range):
        self.assertEqual(token, "test-cached-token")
        self.request_ranges.append((tab, a1_range))
        if a1_range == "B:B":
            return self.code_rows[tab]
        match = re.fullmatch(r"A([1-9][0-9]*):O([1-9][0-9]*)", a1_range)
        if match:
            first, last = (int(value) for value in match.groups())
            return self.full_rows[tab][first - 1:last]
        self.fail("Unexpected legacy audit range")

    def test_reads_global_codes_then_only_the_target_full_rows(self):
        plan = {"expected_rows": self.expected_rows}
        with patch.object(execution, "load_legacy_reconciliation_live_audit_plan",
                          return_value=plan), \
             patch.dict(self.preflight, {
                 "_google_writer_legacy_cached_sheets_token": lambda: "test-cached-token",
                 "_google_writer_legacy_read_sheet_values": self._fake_read,
             }):
            result = self.preflight["_google_writer_legacy_live_sheet_preflight"](FINGERPRINT)

        self.assertEqual(result, execution.partial_reconciliation_profile(FINGERPRINT)["evidence"]["audit"])
        self.assertEqual(self.request_ranges, [
            ("ФОП", "B:B"), ("ЮО", "B:B"), ("ФОП", "A1:O17"), ("ЮО", "A1:O8"),
        ])
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(result["writes_performed"], 0)

    def test_duplicate_in_global_key_column_fails_closed(self):
        self.code_rows["ФОП"].append(list(self.code_rows["ФОП"][0]))

        def fake_read(tab, token, a1_range):
            if a1_range == "B:B":
                return self.code_rows[tab]
            return self._fake_read(tab, token, a1_range)

        plan = {"expected_rows": self.expected_rows}
        with patch.object(execution, "load_legacy_reconciliation_live_audit_plan",
                          return_value=plan), patch.dict(self.preflight, {
                              "_google_writer_legacy_cached_sheets_token": lambda: "test-cached-token",
                              "_google_writer_legacy_read_sheet_values": fake_read,
                          }):
            with self.assertRaisesRegex(RuntimeError, "evidence changed"):
                self.preflight["_google_writer_legacy_live_sheet_preflight"](FINGERPRINT)

    def test_response_limit_remains_fail_closed_for_each_range(self):
        class OversizedResponse:
            def read(self, limit):
                self.assert_limit = limit
                return b"x" * limit

        @contextmanager
        def fake_google_open(request, timeout):
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(timeout, 45)
            yield OversizedResponse()

        self.preflight["sandbox_runtime"].google_open = fake_google_open
        with patch.dict(self.preflight, {"sandbox_runtime": self.preflight["sandbox_runtime"]}):
            with self.assertRaisesRegex(ValueError, "fixed response bound"):
                self.preflight["_google_writer_legacy_read_sheet_values"]("ФОП", "test-token", "B:B")


if __name__ == "__main__":
    unittest.main()
