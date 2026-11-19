"""Additive integrity and mutation contract for authoritative EDR status evidence."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST_RELATIVE = Path("validation/local_release_20260911/edr_status_evidence_v1.json")
MANIFEST_SHA256_LF = "c9c3d2484eccbaf982c47625f43c4c7dd3dbde8df9228a1cf7d71088af5f55e8"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def sha(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


def repository_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST_RELATIVE).is_file() and (candidate / "edr_sync_v2.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate repository root for EDR status evidence integrity")


class EdrStatusEvidenceIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical(MANIFEST_RELATIVE, (self.root / MANIFEST_RELATIVE).read_bytes())
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_manifest_pins_exact_scope_and_baseline(self):
        self.assertEqual(self.manifest["baseline"], "97788b2549f08a7a15738bdeecc508ee3cf545ad")
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-authoritative-edr-status-evidence")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(set(self.manifest), {"baseline", "contract", "files", "historical_manifests",
                                               "mutation_targets", "normalization", "version", "behavior"})
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["mutation_targets"]))
        self.assertEqual(set(self.manifest["files"]), {
            "edr_sync_v2.py",
            "server.py",
            "supplier_registry_integration.py",
            "validation/local_release_20260911/test_edr_monitoring.py",
            "validation/local_release_20260911/test_legacy_google_factual_edr_apply.py",
            "validation/local_release_20260911/test_legacy_google_factual_edr_preview.py",
            "validation/local_release_20260911/test_legacy_google_factual_edr_audit.py",
            "validation/local_release_20260911/test_permanent_edr_sync_safety.py",
            "validation/local_release_20260911/test_single_supplier_edr_workflow.py",
            "validation/local_release_20260911/test_supplier_registry_integration.py",
            "validation/run_local_release.py",
            "validation/run_integrated_source_integrity_overlays.py",
            "validation/fixtures/google_writer_supplier_types_integration_v1_97788.zip",
        })
        self.assertEqual(self.manifest["behavior"], {
            "active_qualifications_do_not_set_edr_registered": True,
            "latest_confirmed_edr_status_persists_until_newer_eligible_event": True,
            "admission_requires_identified_officer_to_set_registered": True,
            "monitoring_card_and_google_writer_share_edr_projection": True,
            "historical_v1_integration_tree_checked_on_original_baseline": "97788b2549f08a7a15738bdeecc508ee3cf545ad",
        })

    def test_candidate_files_match_exact_hashes(self):
        for relative, expected in self.manifest["files"].items():
            with self.subTest(path=relative):
                self.assertEqual(sha(relative, (self.root / relative).read_bytes()), expected)

    def test_byte_addition_deletion_and_content_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            if relative.endswith(".zip"):
                continue
            original = canonical(relative, (self.root / relative).read_bytes())
            for changed in (bytes([original[0] ^ 1]) + original[1:], original + b"\x00", original[:-1]):
                with self.subTest(path=relative, length=len(changed)):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), expected)

    def test_historical_manifest_hashes_remain_pinned(self):
        for relative, expected in self.manifest["historical_manifests"].items():
            with self.subTest(path=relative):
                self.assertEqual(sha(relative, (self.root / relative).read_bytes()), expected)

    def test_manifest_mutations_are_rejected(self):
        for changed in (self.manifest_bytes + b" ", self.manifest_bytes[:-1],
                        self.manifest_bytes.replace(b"\"version\": 1", b"\"version\": 2", 1)):
            self.assertNotEqual(hashlib.sha256(changed).hexdigest(), MANIFEST_SHA256_LF)

    def test_contract_asserts_authoritative_status_rules(self):
        source = (self.root / "edr_sync_v2.py").read_text(encoding="utf-8")
        self.assertIn("Active qualifications determine Prozorro activity; they are not an EDR", source)
        self.assertIn("admission_day and _has_edr_checking_officer(admission_officer)", source)
        monitoring = (self.root / "server.py").read_text(encoding="utf-8")
        registry = (self.root / "supplier_registry_integration.py").read_text(encoding="utf-8")
        self.assertIn("edr_status_current", monitoring)
        self.assertIn("edr_status_current", registry)


if __name__ == "__main__":
    unittest.main()
