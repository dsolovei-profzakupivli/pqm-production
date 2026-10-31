"""Additive exact-content and mutation contract for the PQM → Google writer."""
import hashlib
import json
import unittest
from pathlib import Path


BASELINE = "64f7fda1660c228cbe49c502c6a053fb10c19db1"
MANIFEST = Path("validation/local_release_20260911/google_writer_update_append_v1.json")
MANIFEST_SHA256_LF = "ad8df0ead516fbdc6fd1f51e9f2abca0acf2b4244c395aaad730594a868ee2d7"


def canonical(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def repository_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "supplier_registry_integration.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate repository root for Google writer update/append integrity")


class GoogleWriterUpdateAppendIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_manifest_sha_scope_and_business_contract(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.assertEqual(self.manifest["baseline"], BASELINE)
        self.assertEqual(self.manifest["contract"], "pqm-google-writer-update-append")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest), {"baseline", "contract", "files", "normalization", "version", "behavior"})
        self.assertEqual(set(self.manifest["behavior"]), {
            "business_columns_written", "verification_pair_atomic", "append_requires_decided_event",
            "pending_never_append_or_update", "post_admission_rejection_preserves_verification_pair",
            "active_qualification_wins_over_later_rejection", "exact_timestamp_timezone",
            "date_only_is_not_a_timestamp_ordering_proof", "unowned_columns_never_written",
            "identifier_is_text_and_preserves_leading_zeroes", "append_formula_A_copied_from_audited_template",
            "apply_requires_preview_ticket_and_digest_recheck", "apply_uses_bounded_exact_cell_ranges",
            "uncertain_write_is_not_retried_automatically", "history_is_preserved"})
        behavior = self.manifest["behavior"]
        self.assertEqual(behavior["business_columns_written"], ["C", "D", "E", "F", "H", "I", "L"])
        self.assertEqual(behavior["verification_pair_atomic"], ["D", "E", "I", "L"])
        self.assertEqual(behavior["unowned_columns_never_written"], ["G", "J", "K", "M", "N", "O", "P"])
        self.assertEqual(behavior["exact_timestamp_timezone"], "Europe/Kyiv")
        for flag in ("append_requires_decided_event", "pending_never_append_or_update",
                     "post_admission_rejection_preserves_verification_pair",
                     "active_qualification_wins_over_later_rejection",
                     "date_only_is_not_a_timestamp_ordering_proof", "identifier_is_text_and_preserves_leading_zeroes",
                     "append_formula_A_copied_from_audited_template", "apply_requires_preview_ticket_and_digest_recheck",
                     "apply_uses_bounded_exact_cell_ranges", "uncertain_write_is_not_retried_automatically",
                     "history_is_preserved"):
            self.assertIs(behavior[flag], True)

    def test_exact_candidate_files_match_pinned_hashes(self):
        self.assertEqual(set(self.manifest["files"]), {
            "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs",
            "scripts/pqm-google-writer/PqmSandboxAppendApply.gs",
            "scripts/pqm-google-writer/PqmSandboxControlledApply.gs",
            "scripts/pqm-google-writer/PqmSandboxExpandedChangeAudit.gs",
            "scripts/pqm-google-writer/PqmSandboxFullApply.gs",
            "scripts/pqm-google-writer/PqmSandboxPreview.gs",
            "scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs",
            "scripts/pqm-google-writer/PqmVerificationDatetime.gs",
            "scripts/pqm-google-writer/fixture-preview.json",
            "scripts/pqm-google-writer/sandbox-append-daily-cycle.test.cjs",
            "scripts/pqm-google-writer/sandbox-controlled-apply.test.cjs",
            "scripts/pqm-google-writer/sandbox-expanded-change-audit.test.cjs",
            "scripts/pqm-google-writer/sandbox-full-apply.test.cjs",
            "scripts/pqm-google-writer/sandbox-guard-profiler.test.cjs",
            "scripts/pqm-google-writer/sandbox-preview-audit.test.cjs",
            "scripts/pqm-google-writer/sandbox-temporal-guard.test.cjs",
            "scripts/pqm-google-writer/update-append-business-matrix.test.cjs",
            "supplier_registry_integration.py",
        })
        for relative, entry in self.manifest["files"].items():
            with self.subTest(path=relative):
                content = canonical((self.root / relative).read_bytes())
                self.assertEqual(set(entry), {"sha256_lf"})
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry["sha256_lf"])

    def test_byte_append_delete_and_content_mutations_are_rejected(self):
        for relative, entry in self.manifest["files"].items():
            original = canonical((self.root / relative).read_bytes())
            pinned = entry["sha256_lf"]
            mutations = (bytes([original[0] ^ 1]) + original[1:], original + b"\x00", original[:-1])
            for changed in mutations:
                with self.subTest(path=relative, length=len(changed)):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), pinned)

    def test_writer_scope_has_no_google_owned_or_append_ranges(self):
        deps = (self.root / "scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs").read_text(encoding="utf-8")
        self.assertIn("var PQM_GOOGLE_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        self.assertIn("var PQM_GOOGLE_APPEND_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        planner = (self.root / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        self.assertIn("function blockVerificationPair()", planner)
        self.assertIn("[3, 4, 8, 11]", planner)
        self.assertIn("(decision === 'admit' ? item.google_sync_last_decided_protocol_officer : '')", planner)
        for column in (6, 9, 10, 12, 13, 14):
            self.assertNotIn(f"cells[{column}] =", planner)

    def test_only_decided_application_events_are_writer_eligible(self):
        source = (self.root / "supplier_registry_integration.py").read_text(encoding="utf-8")
        self.assertIn('"google_writer_eligible": code in latest_decisions,', source)
        self.assertNotIn('"google_writer_eligible": code in latest_decisions or code in monitoring_codes,', source)


if __name__ == "__main__":
    unittest.main()
