"""Additive integrity/mutation checks for precise Google EDR mirror semantics."""
import hashlib
import json
import unittest
from pathlib import Path


BASELINE = "a40aa70c55204d8cc3566b70ac43cdf01e3dce03"
MANIFEST = Path("validation/local_release_20260911/sandbox_edr_google_nazk_contract_v2.json")
MANIFEST_SHA256_LF = "84b11fa0f453906aaa0138f1238f06c3843ac7105b4647f2504343e9b0e8ce10"


def canonical(data: bytes, path: str) -> bytes:
    return data if Path(path).suffix.lower() == ".zip" else data.replace(b"\r\n", b"\n")


def repository_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "edr_sync_v2.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate repository root for additive EDR/NAZK v2 integrity")


class SandboxEdrGoogleNazkContractV2Integrity(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical((self.root / MANIFEST).read_bytes(), str(MANIFEST))
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_manifest_and_exact_candidate_scope(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.assertEqual(self.manifest["baseline"], BASELINE)
        self.assertEqual(self.manifest["contract"], "sandbox-edr-google-nazk-reconcile")
        self.assertEqual(self.manifest["version"], 2)
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest["files"]), {
            "edr_sync_review.py", "edr_sync_v2.py", "google_verification_contract.py",
            "sandbox_edr_review.py", "server.py",
            "scripts/pqm-google-writer/sandbox-append-daily-cycle.test.cjs",
            "scripts/pqm-google-writer/sandbox-full-apply.test.cjs",
            "test_google_alignment_backend.py",
            "validation/local_release_20260911/test_edr_sync_v2.py",
            "validation/local_release_20260911/test_permanent_edr_sync_safety.py",
            "validation/local_release_20260911/test_prod_edr_review_promotion.py",
            "validation/local_release_20260911/test_sandbox_canonical_officer.py",
            "validation/local_release_20260911/test_sandbox_edr_google_nazk_reconcile_integrity.py",
            "validation/local_release_20260911/test_sandbox_edr_review.py",
            "validation/local_release_20260911/test_single_supplier_edr_workflow.py",
            "validation/local_release_20260911/test_supplier_edr_dates.py",
            "validation/local_release_20260911/test_supplier_edr_filter.py",
            "validation/local_release_20260911/sandbox_edr_google_nazk_reconcile_v1.json",
            "validation/run_local_release.py",
            "validation/run_sandbox_edr_google_nazk_reconcile_v1_integrity.py",
            "validation/fixtures/edr_google_nazk_reconcile_v1_candidate_a40aa70.zip",
        })

    def test_all_pinned_files_match_exact_bytes_after_line_ending_only_normalization(self):
        for relative, entry in self.manifest["files"].items():
            with self.subTest(path=relative):
                content = canonical((self.root / relative).read_bytes(), relative)
                key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry[key])

    def test_single_byte_append_delete_and_value_mutations_are_rejected(self):
        for relative, entry in self.manifest["files"].items():
            original = canonical((self.root / relative).read_bytes(), relative)
            digest_key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
            pinned = entry[digest_key]
            mutations = (bytes([original[0] ^ 1]) + original[1:], original + b"\x00", original[:-1])
            for changed in mutations:
                with self.subTest(path=relative, changed_length=len(changed)):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), pinned)

    def test_contract_explicitly_protects_full_mirror_and_kyiv_timestamp_rules(self):
        contract = self.manifest["behavior"]
        self.assertEqual(contract["google_to_pqm_mapping"], {
            "G": "termination_decision_details", "J": "termination_record_date",
            "K": "termination_record_number", "M": "edr_notes",
        })
        self.assertEqual(contract["google_to_pqm_full_mirror"], ["G", "J", "K", "M"])
        self.assertEqual(contract["pqm_to_google_protected"], ["G", "J", "K", "M"])
        self.assertEqual(contract["google_timestamp_format"], "dd.MM.yyyy HH:mm:ss Europe/Kyiv")
        self.assertTrue(contract["newer_blank_is_explicit_clear"])
        self.assertTrue(contract["missing_source_column_is_not_blank"])
        self.assertTrue(contract["date_only_is_not_a_verification_instant"])
        self.assertTrue(contract["clear_history_includes_m"])
        self.assertTrue(contract["pqm_to_google_F_allowed"])
        self.assertTrue(contract["google_to_pqm_F_ignored"])
        self.assertTrue(contract["apply_rechecks_source_fingerprint_and_pqm_state_digest"])
        self.assertTrue(contract["manager_change_reconciliation_uses_cached_nazk_no_external_fetch"])
        self.assertTrue(contract["blank_or_unverified_manager_does_not_close_nazk_task"])


if __name__ == "__main__":
    unittest.main()
