"""Exact integrity checks for the separately approved protocol presentation fixes."""
import hashlib
import json
import tempfile
import unittest
import zipfile
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
HISTORICAL_FIXTURE = ROOT / "validation/fixtures/protocol_integrity_history.zip"
HISTORICAL_FIXTURE_SHA256 = "57203e4896bd7ec44eb3ffa68e67092bdfaee913af5549d8e1485adbdcf24381"
HISTORICAL_REVISIONS = (BASELINE, PREVIOUS_VARIANT)


def materialize_historical_tree(revision, contract, destination):
    if revision not in HISTORICAL_REVISIONS:
        raise AssertionError(f"Невідома історична ревізія integrity fixture: {revision}")

    def contract_paths(value):
        paths = set(value.get("product_files", {}))
        paths.update(value.get("guarded_files", {}))
        paths.update(
            path for path, values in value.get("protected_files", {}).items()
            if values.get("sha256")
        )
        return paths

    previous, current = load_contracts()[:2]
    baseline_paths = contract_paths(previous) | contract_paths(current)
    previous_variant_paths = contract_paths(previous)
    expected_paths = baseline_paths if revision == BASELINE else previous_variant_paths
    paths = contract_paths(contract)
    if not paths.issubset(expected_paths):
        raise AssertionError("Integrity fixture не містить усіх запитаних файлів ревізії")

    archive_bytes = HISTORICAL_FIXTURE.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != HISTORICAL_FIXTURE_SHA256:
        raise AssertionError("Змінено зафіксований архів історичних integrity fixture")

    expected_entries = {
        f"{historical_revision}/{relative}"
        for historical_revision in HISTORICAL_REVISIONS
        for relative in (baseline_paths if historical_revision == BASELINE else previous_variant_paths)
    }
    with zipfile.ZipFile(HISTORICAL_FIXTURE) as archive:
        entries = archive.namelist()
        if len(entries) != len(set(entries)) or set(entries) != expected_entries:
            raise AssertionError("Склад історичних integrity fixture не відповідає маніфесту")

        for relative in paths:
            content = archive.read(f"{revision}/{relative}")
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
        self.cat = self.contracts[2]

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
                materialize_historical_tree(revision, self.previous, temp)
                self.assertTrue(manifest_tree_matches(self.previous, temp))

    def test_previous_protocol_variant_remains_pinned_beside_cat_variant(self):
        self.assertEqual(self.current["baseline_sha"], BASELINE)
        self.assertEqual(set(self.current["product_files"]), PRODUCT_FILES)
        self.assertEqual(
            self.current["guarded_files"]["halloween_motion.js"]["sha256"],
            "86358bbfdf498b04fe0f5d8c3f2f56cc5905e3c4f5ea4ffc141b9f8ff706153f",
        )
        for relative, expected in self.current["product_files"].items():
            with self.subTest(file=relative):
                self.assertEqual(len(expected["sha256"]), 64)
                actual = (ROOT / relative).read_bytes()
                self.assertEqual(
                    integrity.sha256(integrity.canonical_content(relative, actual)),
                    expected["sha256"],
                )
        for section in ("guarded_files", "protected_files"):
            for relative, expected in self.current.get(section, {}).items():
                if relative == "halloween_motion.js":
                    continue
                with self.subTest(section=section, file=relative):
                    actual = (ROOT / relative).read_bytes()
                    self.assertEqual(
                        integrity.sha256(integrity.canonical_content(relative, actual)),
                        expected["sha256"],
                    )
        self.assertTrue(manifest_tree_matches(self.cat, ROOT))
        self.assertEqual(self.cat["baseline_sha"], "20fe5a4c721ab60ae95ba44816b79d00a6e3df8d")
        self.assertEqual(set(self.cat["product_files"]), {
            "sandbox_runtime.py", "halloween_motion.js", "halloween_cat_season.js",
            "halloween_cat_season.css", "assets/pqm-cat-no-hat.png",
        })
        self.assertEqual(
            self.current["protected_files"]["server.py"]["sha256"],
            self.previous["product_files"]["server.py"]["sha256"],
        )

    def test_previous_protocol_v2_tree_still_matches_its_original_contract(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as previous_tree:
            materialize_working_tree(self.current, previous_tree)
            with zipfile.ZipFile(HISTORICAL_FIXTURE) as archive:
                original_motion = archive.read(f"{BASELINE}/halloween_motion.js")
            expected_motion_sha = self.current["guarded_files"]["halloween_motion.js"]["sha256"]
            self.assertEqual(
                hashlib.sha256(integrity.canonical_content("halloween_motion.js", original_motion)).hexdigest(),
                expected_motion_sha,
            )
            (Path(previous_tree) / "halloween_motion.js").write_bytes(original_motion)
            self.assertTrue(manifest_tree_matches(self.current, previous_tree))

    def test_cat_variant_rejects_baseline_and_every_single_byte_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as baseline_tree:
            materialize_historical_tree(BASELINE, self.current, baseline_tree)
            self.assertFalse(manifest_tree_matches(self.cat, baseline_tree))

        with tempfile.TemporaryDirectory(dir=ROOT) as candidate_tree:
            materialize_working_tree(self.cat, candidate_tree)
            self.assertTrue(manifest_tree_matches(self.cat, candidate_tree))
            for relative in sorted(self.cat["product_files"]):
                with self.subTest(file=relative):
                    target = Path(candidate_tree) / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(manifest_tree_matches(self.cat, candidate_tree))
                    target.write_bytes(original)
                    self.assertTrue(manifest_tree_matches(self.cat, candidate_tree))

    def test_cat_variant_rejects_changes_to_unchanged_protected_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as candidate_tree:
            materialize_working_tree(self.cat, candidate_tree)
            target = Path(candidate_tree) / "server.py"
            original = target.read_bytes()
            changed = bytearray(original)
            changed[0] ^= 1
            target.write_bytes(changed)
            self.assertFalse(manifest_tree_matches(self.cat, candidate_tree))

    def test_manifest_cannot_be_changed_to_accept_arbitrary_hashes(self):
        modified = json.loads((ROOT / "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json").read_text(encoding="utf-8"))
        modified["product_files"]["app.js"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "modified-manifest.json"
            path.write_text(json.dumps(modified), encoding="utf-8")
            with patch.object(integrity, "ADDITIONAL_CONTRACTS", (path,)):
                with self.assertRaisesRegex(AssertionError, "закріплений integrity-маніфест"):
                    integrity.load_contracts()

    def test_cat_manifest_cannot_be_changed_to_accept_arbitrary_hashes(self):
        modified = json.loads((ROOT / "test_sandbox_permanent_cat_integrity_variant.json").read_text(encoding="utf-8"))
        modified["product_files"]["halloween_motion.js"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "modified-cat-manifest.json"
            path.write_text(json.dumps(modified), encoding="utf-8")
            with patch.object(integrity, "CAT_CONTRACT", path):
                with self.assertRaisesRegex(AssertionError, "закріплений integrity-маніфест постійного котика"):
                    integrity.load_contracts()


if __name__ == "__main__":
    unittest.main()
