"""Additive integrity checks for the date-only/status follow-up candidate."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST = Path("date_only_edr_status_integrated_v2.json")
MANIFEST_SHA256 = "01692fc4604bed3ea5b69ce4b7156000e449bb30b46be5cd17c5e6b9f66c4c0c"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def repository_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "edr_sync_v2.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate date-only/status follow-up tree")


class DateOnlyEdrStatusIntegratedIntegrityV2(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical(MANIFEST, (self.root / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_manifest_pins_follow_up_scope_and_baseline(self):
        self.assertEqual(set(self.manifest), {
            "baseline", "behavior", "baseline_files", "contract", "files",
            "historical_manifests", "mutation_targets", "version",
        })
        self.assertEqual(self.manifest["baseline"], "12329bd4cb428052367cba7e41c381c3a802d02e")
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-date-only-status-follow-up")
        self.assertEqual(self.manifest["version"], 2)
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["mutation_targets"]))

    def test_follow_up_files_match_exact_pins_and_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            raw = canonical(relative, (self.root / relative).read_bytes())
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
                for changed in (bytes([raw[0] ^ 1]) + raw[1:], raw + b"\x00", raw[:-1]):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), expected)

    def test_baseline_and_historical_manifests_remain_unchanged(self):
        for relative, expected in self.manifest["baseline_files"].items():
            with self.subTest(scope="preserved source", path=relative):
                self.assertEqual(hashlib.sha256(canonical(relative, (self.root / relative).read_bytes())).hexdigest(), expected)
        for relative, expected in self.manifest["historical_manifests"].items():
            with self.subTest(scope="historical manifest", path=relative):
                self.assertEqual(hashlib.sha256(canonical(relative, (self.root / relative).read_bytes())).hexdigest(), expected)

    def test_same_timestamp_blank_manager_is_equivalent_but_one_sided_blank_conflicts(self):
        source = (self.root / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        self.assertIn("pqmManagerBlank !== googleManagerBlank", source)
        self.assertIn("var managerConflict = !pqmManagerBlank", source)
        self.assertIn("var statusConflict = !equalEdr || equalEdr !==", source)
        test = (self.root / "scripts/pqm-google-writer/sandbox-append-daily-cycle.test.cjs").read_text(encoding="utf-8")
        self.assertIn("Sandbox may have no manager on either side", test)
        self.assertIn("pqm: '', google: 'Google Manager'", test)
        self.assertIn("pqm: 'PQM Manager', google: ''", test)
        self.assertIn("same_timestamp_verification_group_incomplete", test)

    def test_audit_uses_planned_edr_status_and_daily_sync_preserves_conflicts(self):
        audit = (self.root / "scripts/pqm-google-writer/PqmSandboxExpandedChangeAudit.gs").read_text(encoding="utf-8")
        self.assertIn("var plannedE = pqmSandboxExpandedAuditStatus_(cells[4], 'edr')", audit)
        self.assertIn("googleE, plannedE", audit)
        self.assertIn("googleE + ' -> ' + plannedE", audit)
        daily = (self.root / "scripts/pqm-google-writer/sandbox-full-apply.test.cjs").read_text(encoding="utf-8")
        self.assertIn("expect_conflict: index === 7", daily)
        self.assertIn("same-timestamp conflicting EDR status blocks Apply", daily)
        self.assertIn("conflict does not mutate PQM profile", daily)
        self.assertIn("conflict does not append a verification event", daily)
        self.assertIn("the 2026-10-01 precise PQM check is newer than Google date-only 2026-09-22", daily)

    def test_exact_previous_integrated_tree_overlay_is_preserved(self):
        helper = (self.root / "validation/run_date_only_previous_contract_overlays.py").read_text(encoding="utf-8")
        runner = (self.root / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("date_only_edr_status_integrated_v1_12329.zip", helper)
        self.assertIn("05d2359d57155097d3f87e0fb26fdd222fc9aa2e808250ac6f03a1da1e3d12a8", helper)
        self.assertIn("test_date_only_edr_status_integrated_integrity_v1", runner)
        self.assertIn("date_only_edr_status_integrated_v1_12329.zip", runner)


if __name__ == "__main__":
    unittest.main()
