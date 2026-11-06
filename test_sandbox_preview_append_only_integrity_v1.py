"""Additive source integrity contract for detailed Sandbox Preview and APPEND_ONLY."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

MANIFEST = Path("validation/sandbox_preview_append_only_v1.json")
MANIFEST_SHA256 = "ed2d0404fd4128f3ed248cb23d87d3e6f933a7d2467d6fe1ca6c454e4a7ae168"
BASELINE = "0347404ddddd67eae52a90810ccf6e00bff2683e"


def canonical(raw):
    return raw.replace(b"\r\n", b"\n")


def canonical_self(raw):
    return re.sub(rb'MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(raw))


class SandboxPreviewAppendOnlyIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.manifest_raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_raw.decode("utf-8"))

    def test_manifest_scope_hashes_and_clean_baseline(self):
        self.assertEqual(hashlib.sha256(self.manifest_raw).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-preview-details-append-only")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], BASELINE)
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip(), BASELINE)
        self.assertEqual(hashlib.sha256(canonical_self(Path(__file__).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["expected_changed_files"]) - {MANIFEST.as_posix(), Path(__file__).name})
        tracked = set(subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=self.root, text=True).splitlines())
        untracked = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=self.root, text=True).splitlines())
        self.assertEqual(tracked | untracked, set(self.manifest["expected_changed_files"]))
        for relative, expected in self.manifest["files"].items():
            raw = canonical((self.root / relative).read_bytes())
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)

    def test_production_sources_and_historical_pins_are_unchanged(self):
        for group in ("production_sources", "historical_manifests"):
            for relative, expected in self.manifest[group].items():
                current = canonical((self.root / relative).read_bytes())
                baseline = canonical(subprocess.check_output(["git", "show", f"{BASELINE}:{relative}"], cwd=self.root))
                with self.subTest(group=group, path=relative):
                    self.assertEqual(current, baseline)
                    self.assertEqual(hashlib.sha256(current).hexdigest(), expected)

    def test_source_mutations_and_production_scope_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            raw = canonical((self.root / relative).read_bytes())
            for mutation in (bytes([raw[0] ^ 1]) + raw[1:], raw + b"\x00", raw[:-1]):
                with self.subTest(path=relative, length=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), expected)
        execution = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        server = canonical((self.root / "server.py").read_bytes()).decode("utf-8")
        self.assertIn("APPEND_ONLY requires the Sandbox checkpoint protocol", execution)
        self.assertIn("validate_preview_plan_scope(snapshot,ticket)", server)
        self.assertIn("ticket.get('scope')", execution)
        self.assertIn("PQM-PREVIEW-TICKET:", execution)


if __name__ == "__main__":
    unittest.main()
