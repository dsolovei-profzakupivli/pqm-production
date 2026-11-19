"""Additive integrity contract for manual supplier classification v4."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).parent
MANIFEST = ROOT / "supplier_manual_classification_v4_contract.json"
PINNED_MANIFEST_SHA256 = "1539ce02ddab5e3c5a0ad3ce8bb87f571cc2e3d8048b91e81b28883621197ff6"
SELF_FILE = "test_supplier_manual_classification_v4_integrity.py"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    if relative == SELF_FILE:
        raw = re.sub(rb'PINNED_MANIFEST_SHA256 = "[0-9a-f]{64}"',
                     b'PINNED_MANIFEST_SHA256 = "' + b"0" * 64 + b'"', raw)
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def sha(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


class SupplierManualClassificationV4IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = canonical(MANIFEST.name, MANIFEST.read_bytes())
        if hashlib.sha256(raw).hexdigest() != PINNED_MANIFEST_SHA256:
            raise AssertionError("Manual-classification v4 contract manifest changed")
        cls.manifest = json.loads(raw.decode("utf-8"))

    def test_exact_candidate_tree_and_baseline(self):
        self.assertEqual(self.manifest["parent"], "59177be3e98540c53484962cc7f349a157e7b0bf")
        files = self.manifest["files"]
        self.assertIn("supplier_manual_classification.py", files)
        self.assertIn("server.py", files)
        self.assertIn("scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs", files)
        self.assertIn("test_supplier_manual_classification.py", files)
        actual = {path: sha(path, (ROOT / path).read_bytes()) for path in files}
        self.assertEqual(actual, files)

    def test_automatic_v3_classifier_is_unchanged(self):
        raw = (ROOT / "supplier_classification.py").read_bytes()
        self.assertEqual(hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
                         self.manifest["automatic_v3_sha256"])
        source = raw.decode("utf-8")
        self.assertIn("subject-nature-20261031-v3", source)

    def test_manual_routing_is_independent_from_v3_and_has_no_third_sheet(self):
        module = (ROOT / "supplier_manual_classification.py").read_text(encoding="utf-8")
        writer = (ROOT / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        self.assertIn("supplier_manual_classifications", module)
        self.assertIn("supplier_manual_classification_events", module)
        self.assertIn("revision", module)
        self.assertIn("BEGIN IMMEDIATE", module)
        self.assertIn("classification_revision", writer)
        self.assertIn("'ФОП'", writer)
        self.assertIn("'ЮО'", writer)
        self.assertNotIn("'Нерезиденти'", writer)
        self.assertNotIn("'Нерезиденти'", module)

    def test_manual_api_is_authorized_and_effective_classification_reaches_registry(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        auth = (ROOT / "auth_access.py").read_text(encoding="utf-8")
        registry = (ROOT / "supplier_registry_integration.py").read_text(encoding="utf-8")
        self.assertIn("/api/supplier-classifications/", server)
        self.assertIn("suppliers.classification", auth)
        self.assertIn("apply_effective", server)
        self.assertIn("apply_effective", registry)
        self.assertIn("confirm_replace", server)

    def test_v3_integrity_runner_uses_exact_baseline_tree(self):
        runner = (ROOT / "validation/run_supplier_classification_v3_integrity.py").read_text(encoding="utf-8")
        self.assertIn('BASELINE = "59177be3e98540c53484962cc7f349a157e7b0bf"', runner)
        self.assertIn('FIXTURE_RELATIVE = Path("validation/fixtures/supplier_classification_v3_baseline_59177.zip")', runner)
        self.assertIn('FIXTURE_SHA256 = "49445ff35cb5f77c77095c96b8fb4f06de358b81c40b3ccd7dc0753b8c855bf8"', runner)
        self.assertIn('"test_supplier_classification_v3_integrity"', runner)
        self.assertIn('manifest["historical_manifests"]', runner)
        self.assertIn('path.write_bytes(lf)', runner)
        self.assertNotIn('["git"', runner)

    def test_v3_integrity_runner_executes_without_git(self):
        runner = ROOT / "validation/run_supplier_classification_v3_integrity.py"
        env = os.environ.copy()
        env["PATH"] = ""
        env.pop("PQM_RELEASE_SOURCE_ROOT", None)
        result = subprocess.run(
            [sys.executable, "-B", str(runner)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Ran 5 tests", output)
        self.assertIn("OK", output)

    def test_messages_history_runner_uses_exact_parent_and_isolated_dependencies(self):
        runner = (ROOT / "validation/run_messages_integrated_v1_history.py").read_text(encoding="utf-8")
        self.assertIn('PARENT_FIXTURE_SHA256 = "2fc0787617767048d92870559d4654dd989e356a898ef58c06015453ebaf71ad"', runner)
        self.assertIn('archive.read(relative)', runner)
        self.assertIn('".test-packages"', runner)
        self.assertIn('env["PYTHONPATH"] = str(test_packages)', runner)
        self.assertIn('".gate-tmp"', runner)
        self.assertIn('".venv-release"', runner)
        self.assertIn('HISTORICAL_COMPONENTS = {', runner)
        for component in (
            "auth_access.py", "auth_ui.js", "scheduler_runtime.py", "nazk_workflow.py",
            "google_writer_execution.py", "table_widths_ui.js", "violation_protocol_docx.py",
            "theme.css", "styles.css",
        ):
            self.assertIn(f'"{component}"', runner)
        nested_runner = (ROOT / "validation/run_integrated_messages_v1_integrity.py").read_text(encoding="utf-8")
        self.assertIn("inherited_pythonpath = env.get('PYTHONPATH', '')", nested_runner)
        self.assertIn("str(tree) + (os.pathsep + inherited_pythonpath", nested_runner)

    def test_every_declared_mutation_target_rejects_byte_mutations(self):
        files = self.manifest["files"]
        for relative in self.manifest["mutation_targets"]:
            with self.subTest(path=relative):
                data = (ROOT / relative).read_bytes()
                self.assertTrue(data)
                expected = files[relative]
                for mutated in (bytes([data[0] ^ 1]) + data[1:], data + b"X", data[:-1]):
                    self.assertNotEqual(sha(relative, mutated), expected)


if __name__ == "__main__":
    unittest.main()
