"""Additive integrity contract for the single-run partial reconciliation flow."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20260911/partial_apply_reconciliation_v2.json")
MANIFEST_SHA256 = "d99da6feec2eb7533968ce2dd3ad5f11b3726cc7e810d4a7900388f1b3feae40"
TEST_FILE = "test_partial_apply_reconciliation_integrity_v2.py"


def canonical_text(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(rb'MANIFEST_SHA256 = "[^"]*"',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical_text(data))


def repository_root():
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "server.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate partial reconciliation integrity root")


class PartialApplyReconciliationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical_text((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_identity_scope_and_preserved_history(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-partial-apply-reconciliation")
        self.assertEqual(self.manifest["version"], 2)
        self.assertEqual(self.manifest["baseline"], "3a63ac035e1b788b0ffb6729171d81758d2af80e")
        self.assertEqual(set(self.manifest["files"]), {
            "google_writer_execution.py", "server.py",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs",
            "scripts/pqm-google-writer/mirror-alignment/execution-api.test.cjs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs",
            "test_google_writer_partial_reconciliation.py", "test_partial_apply_reconciliation_integrity_v2.py",
            "validation/run_local_release.py", "validation/run_preview_digest_contract_v1_integrity.py",
            "validation/fixtures/preview_digest_contract_v1_baseline_3a63ac.zip",
        })
        for relative, expected in self.manifest["preserved_sources"].items():
            with self.subTest(source=relative):
                self.assertEqual(hashlib.sha256(canonical_text((self.root / relative).read_bytes())).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical_text((self.root / relative).read_bytes())).hexdigest(), expected)
        self.assertEqual(hashlib.sha256(canonical_self((self.root / TEST_FILE).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])

    def test_reconciliation_sources_match_exact_additive_hashes(self):
        for relative, expected in self.manifest["files"].items():
            with self.subTest(path=relative):
                data = (self.root / relative).read_bytes()
                if relative == TEST_FILE:
                    data = canonical_self(data)
                elif not relative.endswith(".zip"):
                    data = canonical_text(data)
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)

    def test_partial_reconciliation_is_one_sandbox_run_and_never_apply(self):
        python = (self.root / "google_writer_execution.py").read_text(encoding="utf-8")
        server = (self.root / "server.py").read_text(encoding="utf-8")
        script = (self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_text(encoding="utf-8")
        self.assertIn("PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT = '9be34ff2df1e661346176eeb'", python)
        self.assertIn("def prepare_partial_reconciliation", python)
        self.assertIn("def finalize_partial_reconciliation", python)
        self.assertIn("'status':'RECONCILED_PARTIAL'", python)
        self.assertIn("status='partial'", python)
        self.assertIn("/api/admin/google-writer/reconcile-partial", server)
        self.assertIn("permissions.get('admin.manage')", server)
        self.assertIn("permissions.get('google.writer.execute')", server)
        self.assertIn("'reconcile_partial'", script)
        self.assertIn("PQM_EXECUTION_UNCERTAIN", script)
        self.assertIn("originalRunRecordRaw", script)
        self.assertNotIn("pqmSandboxDailySync(", script[script.index("function pqmSandboxReconcilePartial_"):])
        self.assertNotIn("Sheets.Spreadsheets.Values.update", script[script.index("function pqmSandboxReconcilePartial_"):])

    def test_previous_a_formula_date_only_and_no_information_sources_are_unchanged(self):
        expected = self.manifest["preserved_sources"]
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxPreviewDependencies.gs", expected)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAppendApply.gs", expected)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/PqmVerificationDatetime.gs", expected)

    def test_every_declared_file_rejects_mutation(self):
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            normalized = canonical_self(raw) if relative == TEST_FILE else raw if relative.endswith(".zip") else canonical_text(raw)
            for mutation in (normalized + b"\x00", normalized[:-1]):
                with self.subTest(path=relative, size=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
