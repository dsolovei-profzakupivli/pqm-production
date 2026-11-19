"""Additive integrity contract for the date-only/status integrated tree."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST = Path("date_only_edr_status_integrated_v1.json")
MANIFEST_SHA256 = "b39769187968f9f3849c0050ea74b68120821f1d0b9ce140183d5929cc02a4e8"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def digest(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


def repository_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "edr_sync_v2.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate integrated date-only/status tree")


class DateOnlyEdrStatusIntegratedIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical(MANIFEST, (self.root / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_manifest_pins_integrated_baseline_scope_and_contract(self):
        self.assertEqual(set(self.manifest), {
            "baseline", "behavior", "baseline_files", "contract", "files",
            "historical_manifests", "mutation_targets", "version",
        })
        self.assertEqual(self.manifest["baseline"], "15b8e663d343f462eb60a99694b346f265babb37")
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-date-only-midnight-with-edr-status-integrated")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["mutation_targets"]))
        self.assertEqual(self.manifest["behavior"], {
            "date_only_is_kyiv_midnight_for_ordering": True,
            "date_only_storage_remains_date_only": True,
            "exact_timestamp_precision_is_seconds": True,
            "equal_timestamp_manager_or_status_change_is_conflict": True,
            "active_qualifications_do_not_set_edr_registered": True,
            "status_projection_and_ui_date_formatting_unchanged": True,
            "google_writer_update_append_and_supplier_classification_preserved": True,
            "old_contracts_execute_on_exact_97788_and_15b8_trees": True,
        })

    def test_integrated_files_and_baseline_owned_files_match_exact_hashes(self):
        for relative, expected in self.manifest["files"].items():
            with self.subTest(scope="integrated", path=relative):
                self.assertEqual(digest(relative, (self.root / relative).read_bytes()), expected)
        for relative, expected in self.manifest["baseline_files"].items():
            with self.subTest(scope="preserved baseline", path=relative):
                self.assertEqual(digest(relative, (self.root / relative).read_bytes()), expected)

    def test_historical_manifests_are_unchanged(self):
        for relative, expected in self.manifest["historical_manifests"].items():
            with self.subTest(path=relative):
                self.assertEqual(digest(relative, (self.root / relative).read_bytes()), expected)

    def test_single_byte_addition_deletion_and_content_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            raw = canonical(relative, (self.root / relative).read_bytes())
            mutations = (bytes([raw[0] ^ 1]) + raw[1:], raw + b"\x00", raw[:-1])
            for changed in mutations:
                with self.subTest(path=relative, size=len(changed)):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), expected)

    def test_edr_status_remains_evidence_driven_and_equal_time_changes_fail_closed(self):
        sync = (self.root / "edr_sync_v2.py").read_text(encoding="utf-8")
        self.assertIn("Active qualifications determine Prozorro activity; they are not an EDR", sync)
        self.assertIn("admission_day and _has_edr_checking_officer(admission_officer)", sync)
        self.assertIn('row_conflicts.append("same_timestamp_verification_conflict")', sync)
        status_test = (self.root / "validation/local_release_20260911/test_edr_sync_v2.py").read_text(encoding="utf-8")
        self.assertIn("test_same_timestamp_status_change_conflicts_until_a_newer_check", status_test)
        safety_test = (self.root / "validation/local_release_20260911/test_permanent_edr_sync_safety.py").read_text(encoding="utf-8")
        self.assertIn("test_equal_date_only_manager_or_status_difference_is_blocked", safety_test)

    def test_monitoring_classification_and_date_display_sources_remain_at_15b8(self):
        for relative in ("server.py", "supplier_registry_integration.py", "supplier_classification.py",
                         "index.html", "app.js",
                         "validation/local_release_20260911/test_edr_monitoring.py",
                         "validation/local_release_20260911/test_single_supplier_edr_workflow.py"):
            self.assertEqual(digest(relative, (self.root / relative).read_bytes()),
                             self.manifest["baseline_files"][relative])

    def test_exact_baseline_overlays_are_wired_without_rewriting_old_contracts(self):
        runner = (self.root / "validation/run_local_release.py").read_text(encoding="utf-8")
        helper = (self.root / "validation/run_date_only_previous_contract_overlays.py").read_text(encoding="utf-8")
        self.assertIn("test_google_edr_date_only_midnight_integrity_v1", runner)
        self.assertIn("test_edr_status_evidence_integrity_v1", runner)
        self.assertIn("google_edr_date_only_midnight_v1_97788.zip", helper)
        self.assertIn("edr_status_evidence_v1_15b8.zip", helper)
        self.assertIn("fb6ac2224de07ac0a2a71feb727c3d03e1900a6eed7aaad82d7577cc77d9b8b7", helper)
        self.assertIn("772a73e079027a2c45024bc61bac20f5a178ffd962f953372dbbfb80f4b0aec0", helper)


if __name__ == "__main__":
    unittest.main()
