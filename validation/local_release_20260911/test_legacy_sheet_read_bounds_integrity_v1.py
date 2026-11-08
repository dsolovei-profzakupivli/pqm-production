"""Additive source pin for bounded legacy Sheets reads; prior manifests stay immutable."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20260911/legacy_sheet_read_bounds_v1.json")
MANIFEST_SHA256 = "861c2c7e8438da033464722045c10452947c381a337f095b7dc83e9755b0e793"
TEST_FILE = "validation/local_release_20260911/test_legacy_sheet_read_bounds_integrity_v1.py"


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


def root_path():
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "server.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate bounded legacy Sheets read overlay root")


class LegacySheetReadBoundsIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_overlay_pins_only_the_bounded_read_change_and_preserves_history(self):
        self.assertEqual(self.manifest["contract"], "pqm-google-writer-legacy-sheet-read-bounds")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "98eb5d5808bad3493fe877e344ba77dc75317f96")
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["scope"]))
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            normalized = canonical_self(raw) if relative == TEST_FILE else canonical(raw)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(),
                                 expected)

    def test_read_contract_keeps_full_key_scan_and_limits_full_rows_to_targets(self):
        source = canonical((self.root / "server.py").read_bytes()).decode("utf-8")
        bounded_reader = source[source.index("def _google_writer_legacy_read_sheet_values"):
                                source.index("def _google_writer_legacy_live_sheet_preflight")]
        preflight = source[source.index("def _google_writer_legacy_live_sheet_preflight"):
                           source.index("def sandbox_google_row_navigation_enabled")]
        for required in (
            'a1_range != "B:B"', 'r"A[1-9][0-9]*:O[1-9][0-9]*"',
            'method="GET"', 'response.read(4_000_001)',
            'len(raw) > 4_000_000', 'valueRenderOption',
        ):
            with self.subTest(reader_contract=required):
                self.assertIn(required, bounded_reader)
        self.assertIn('"B:B"', preflight)
        self.assertIn('code_locations.setdefault(code, []).append((tab, row_number))', preflight)
        self.assertIn('for item in plan["expected_rows"]', preflight)
        self.assertIn('f"A{first}:O{last}"', preflight)
        self.assertIn('audit_legacy_reconciliation_first_chunk', preflight)
        self.assertIn('partial_reconciliation_profile', (self.root / "google_writer_execution.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
