"""Additive v3 integrity contract for independent EDR mirror review behavior."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "validation/local_release_20260911/google_writer_update_append_v3.json"
PINNED_MANIFEST_SHA256_LF = "0a8a6c51da91733bb6e8bf6c68f81901e51ba965fea72a2bf6b8a7b489ae6921"
V2_MANIFEST = ROOT / "validation/local_release_20260911/google_writer_update_append_v2.json"
V2_MANIFEST_SHA256_LF = "26af0547da5fe3170f5d76b96a88da07de6c26c111a3a12ab2bdb1411700cd84"


def canonical_text(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def git_blob_sha1(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


class GoogleWriterUpdateAppendV3Integrity(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = canonical_text(MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), PINNED_MANIFEST_SHA256_LF)
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_v3_additively_references_immutable_v2(self):
        self.assertEqual(self.manifest["baseline"], "b988f140af37c45bd5461735cf40d18cd00d741a")
        self.assertEqual(self.manifest["contract"], "pqm-google-writer-update-append")
        self.assertEqual(self.manifest["version"], 3)
        self.assertEqual(self.manifest["normalization"],
                         "CRLF-to-LF only for text files before Git blob hashing")
        self.assertEqual(self.manifest["extends"], {
            "manifest": "validation/local_release_20260911/google_writer_update_append_v2.json",
            "manifest_sha256_lf": V2_MANIFEST_SHA256_LF,
            "version": 2,
            "immutable": True,
        })
        v2_bytes = canonical_text(V2_MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(v2_bytes).hexdigest(), V2_MANIFEST_SHA256_LF)
        v2 = json.loads(v2_bytes.decode("utf-8"))
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["baseline"], self.manifest["baseline"])
        self.assertIn("conflicts_and_write_protection", v2["behavior"])
        self.assertTrue(v2["behavior"]["google_writer_F_date_independence"])
        self.assertEqual(v2["behavior"]["google_owned_columns"], ["G", "J", "K", "M"])

    def test_exact_additional_git_blob_pins_and_mutations_fail(self):
        files = self.manifest["files"]
        self.assertEqual(set(files), {
            "sandbox_edr_review.py",
            "validation/local_release_20260911/test_sandbox_edr_review.py",
        })
        for name, entry in files.items():
            relative = Path(name)
            normalized = canonical_text((ROOT / relative).read_bytes())
            expected = entry["git_blob_sha1_lf"]
            with self.subTest(path=name):
                self.assertEqual(git_blob_sha1(normalized), expected)
                for changed in (normalized + b"\0", normalized[:-1]):
                    self.assertNotEqual(git_blob_sha1(changed), expected)

    def test_contract_records_only_the_approved_independent_mirror_exception(self):
        self.assertEqual(self.manifest["behavior"], {
            "google_owned_fields": [
                "termination_decision_details", "termination_record_date",
                "termination_record_number", "edr_notes",
            ],
            "independent_mirrors_when_verification_is_blocked":
                "show and apply only when explicitly marked independent_mirror_only",
            "confirmed_blank_values":
                "clear the corresponding PQM mirror field only for a present, successfully read source cell",
            "unapproved_conflicts": "block mirror updates",
            "verification_timestamps": "retain existing timestamp and conflict rules",
            "writer_protection": "retain v2 direction, protected-cell, source-shape, and duplicate checks",
        })

    def test_review_and_conflict_regressions(self):
        tests = self.manifest["behavior_tests"]
        self.assertEqual(tests, [
            "validation.local_release_20260911.test_sandbox_edr_review.SandboxEdrReviewTests.test_independent_mirrors_remain_reviewable_when_verification_fields_are_date_blocked",
            "validation.local_release_20260911.test_sandbox_edr_review.SandboxEdrReviewTests.test_confirmed_blank_google_owned_values_clear_pqm",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_approved_same_timestamp_conflict_applies_only_google_owned_mirrors",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_unapproved_row_conflict_blocks_mirror_updates",
        ])
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", *tests],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
