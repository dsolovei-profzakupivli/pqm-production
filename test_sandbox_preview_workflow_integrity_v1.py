"""Additive integrity contract for the Preview modal browser CI step."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/sandbox_preview_workflow_v1.json")
MANIFEST_SHA256 = "0da1027b853a44dfcb599926c07c0c27d5f014b078e00114eec0392d3f21126d"
BASELINE = "0347404ddddd67eae52a90810ccf6e00bff2683e"
TEST_FILE = "test_sandbox_preview_workflow_integrity_v1.py"


def canonical(raw):
    return raw.replace(b"\r\n", b"\n")


def canonical_self(raw):
    return re.sub(rb'MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(raw))


class SandboxPreviewWorkflowIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.manifest_bytes = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_and_exact_workflow_delta(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-preview-workflow")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], BASELINE)
        self.assertEqual(self.manifest["baseline_workflow_fixture"],
                         "validation/fixtures/release_checks_baseline_0347404.yml")
        self.assertEqual(self.manifest["added_command"],
                         "node validation/google_writer_preview_modal_browser.cjs")
        self.assertEqual(hashlib.sha256(canonical_self(Path(__file__).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])
        self.assertEqual(set(self.manifest["files"]), {
            ".github/workflows/release-checks.yml",
            "validation/fixtures/release_checks_baseline_0347404.yml",
            "validation/run_messages_integrated_v1_history_addendum.py",
            "validation/run_local_release.py",
        })
        for relative, expected in self.manifest["files"].items():
            actual = canonical((self.root / relative).read_bytes())
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(actual).hexdigest(), expected)

    def test_only_the_approved_browser_command_was_added(self):
        base = canonical((self.root / self.manifest["baseline_workflow_fixture"]).read_bytes())
        current = canonical((self.root / ".github/workflows/release-checks.yml").read_bytes())
        anchor = b"          node validation/chat_messages_browser.cjs\n"
        addition = b"          " + self.manifest["added_command"].encode("ascii") + b"\n"
        self.assertEqual(base.count(anchor), 1)
        self.assertEqual(current, base.replace(anchor, anchor + addition, 1))
        self.assertEqual(current.count(addition), 1)
        self.assertLess(current.index(addition), current.index(b"      - name: Build release image"))

    def test_content_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            raw = canonical((self.root / relative).read_bytes())
            for changed in (bytes([raw[0] ^ 1]) + raw[1:], raw + b"\x00", raw[:-1]):
                with self.subTest(path=relative, size=len(changed)):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
