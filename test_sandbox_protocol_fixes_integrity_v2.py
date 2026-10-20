"""Exact integrity checks for the separately approved protocol presentation fixes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import validation.local_release_20260911.sandbox_protocol_integrity_variant as integrity
from validation.local_release_20260911.sandbox_protocol_integrity_variant import (
    ROOT,
    load_contract,
    load_contracts,
    manifest_tree_matches,
)


BASELINE = "b2027e6d687bc4018a2720f10fae228ccff7b201"
PREVIOUS_VARIANT = "95f1330b590d3fa23ea098303e6dac5ce898352e"
PRODUCT_FILES = {
    "app.js",
    "protocol_supplier_names.py",
    "styles.css",
    "violation_protocol_docx.py",
}


def materialize_git_tree(revision, contract, destination):
    paths = set(contract.get("product_files", {}))
    paths.update(contract.get("guarded_files", {}))
    paths.update(
        path for path, values in contract.get("protected_files", {}).items()
        if values.get("sha256")
    )
    for relative in paths:
        content = subprocess.check_output(
            ["git", "show", f"{revision}:{relative}"], cwd=ROOT
        )
        target = Path(destination) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def materialize_working_tree(contract, destination):
    paths = set(contract.get("product_files", {}))
    paths.update(contract.get("guarded_files", {}))
    paths.update(
        path for path, values in contract.get("protected_files", {}).items()
        if values.get("sha256")
    )
    for relative in paths:
        target = Path(destination) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


class ProtocolFixesIntegrityV2Tests(unittest.TestCase):
    def setUp(self):
        self.contracts = load_contracts()
        self.previous = self.contracts[0]
        self.current = self.contracts[1]

    def test_previous_integrity_contract_and_hashes_remain_unchanged(self):
        stored = json.loads((ROOT / "test_sandbox_protocol_integrity_variant.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, self.previous)
        self.assertEqual(self.previous["variant_id"], "sandbox-universal-decline-p49-3-v1")
        self.assertEqual(set(self.previous["product_files"]), {
            "app.js", "server.py", "template_catalog.py", "violation_protocol_docx.py",
            "metadata/template_legacy_tokens.v1.json",
            "templates/violation_protocols/decline_individual_review.docx",
        })

    def test_baseline_and_previous_allowed_variant_still_match_v1(self):
        for revision in (BASELINE, PREVIOUS_VARIANT):
            with self.subTest(revision=revision), tempfile.TemporaryDirectory(dir=ROOT) as temp:
                materialize_git_tree(revision, self.previous, temp)
                self.assertTrue(manifest_tree_matches(self.previous, temp))

    def test_new_variant_is_exactly_bound_to_baseline_and_four_files(self):
        self.assertEqual(self.current["baseline_sha"], BASELINE)
        self.assertEqual(set(self.current["product_files"]), PRODUCT_FILES)
        for relative, expected in self.current["product_files"].items():
            with self.subTest(file=relative):
                self.assertEqual(len(expected["sha256"]), 64)
                self.assertTrue(manifest_tree_matches(self.current, ROOT))
        self.assertTrue(manifest_tree_matches(self.current, ROOT))
        self.assertEqual(
            self.current["protected_files"]["server.py"]["sha256"],
            self.previous["product_files"]["server.py"]["sha256"],
        )

    def test_new_variant_rejects_baseline_and_every_single_byte_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as baseline_tree:
            materialize_git_tree(BASELINE, self.current, baseline_tree)
            self.assertFalse(manifest_tree_matches(self.current, baseline_tree))

        with tempfile.TemporaryDirectory(dir=ROOT) as candidate_tree:
            materialize_working_tree(self.current, candidate_tree)
            self.assertTrue(manifest_tree_matches(self.current, candidate_tree))
            for relative in sorted(PRODUCT_FILES):
                with self.subTest(file=relative):
                    target = Path(candidate_tree) / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(manifest_tree_matches(self.current, candidate_tree))
                    target.write_bytes(original)
                    self.assertTrue(manifest_tree_matches(self.current, candidate_tree))

    def test_new_variant_rejects_changes_to_unchanged_protected_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as candidate_tree:
            materialize_working_tree(self.current, candidate_tree)
            target = Path(candidate_tree) / "server.py"
            original = target.read_bytes()
            changed = bytearray(original)
            changed[0] ^= 1
            target.write_bytes(changed)
            self.assertFalse(manifest_tree_matches(self.current, candidate_tree))

    def test_manifest_cannot_be_changed_to_accept_arbitrary_hashes(self):
        modified = json.loads((ROOT / "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json").read_text(encoding="utf-8"))
        modified["product_files"]["app.js"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "modified-manifest.json"
            path.write_text(json.dumps(modified), encoding="utf-8")
            with patch.object(integrity, "ADDITIONAL_CONTRACTS", (path,)):
                with self.assertRaisesRegex(AssertionError, "закріплений integrity-маніфест"):
                    integrity.load_contracts()


if __name__ == "__main__":
    unittest.main()
