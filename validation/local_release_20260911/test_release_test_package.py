"""Tests for deterministic and complete Release Gate package staging."""
from pathlib import Path
import tempfile
import unittest

from validation.release_test_package import (
    PACKAGE_MANIFEST,
    format_preflight_error,
    load_package_manifest,
    package_dependency_map,
    preflight_dependency_map,
    stage_dependency_map,
)


ROOT = Path(__file__).resolve().parents[2]


class ReleaseTestPackageTests(unittest.TestCase):
    def test_single_manifest_covers_history_runners_tests_and_support(self):
        manifest = load_package_manifest(ROOT)
        dependencies = {path for path, _sources in package_dependency_map(
            ROOT, ROOT, manifest=manifest
        )}
        for version in range(1, 13):
            self.assertIn(f"validation/run_integrated_writer_ui_v{version}_history.py", dependencies)
        for version in range(1, 14):
            self.assertIn(f"test_google_writer_integrated_candidate_integrity_v{version}.py", dependencies)
            self.assertIn(
                f"validation/local_release_20261116/pqm_sync_ui_integrated_v{version}.json",
                dependencies,
            )
        self.assertIn("validation/integrated_snapshot_archive.py", dependencies)
        self.assertIn("validation/integrated_git_snapshot.py", dependencies)
        for name in manifest["required_local_release_tests"]:
            self.assertIn(f"validation/local_release_20260911/{name}", dependencies)
        self.assertIn(PACKAGE_MANIFEST.as_posix(), dependencies)
        self.assertIn("validation/run_integrated_writer_ui_v10_history.py", dependencies)
        self.assertGreaterEqual(len(manifest["release_fixture_basenames"]), 60)

    def test_runner_dependencies_stage_between_separate_gitless_roots(self):
        manifest = load_package_manifest(ROOT)
        all_dependencies = package_dependency_map(ROOT, ROOT, manifest=manifest)
        runner_dependencies = [
            (path, candidates) for path, candidates in all_dependencies
            if path.startswith("validation/run_integrated_writer_ui_v")
            or path in {
                "validation/integrated_snapshot_archive.py",
                "validation/integrated_git_snapshot.py",
            }
        ]
        with tempfile.TemporaryDirectory(prefix="pqm-package-source-") as source_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-package-stage-") as stage_tmp:
            source = Path(source_tmp)
            staged = Path(stage_tmp)
            for relative, candidates in runner_dependencies:
                origin = next(path for path in candidates if path.is_file())
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(origin.read_bytes())

            # Build the map against distinct roots, as the Docker test package does.
            source_dependencies = [
                (relative, (source / relative,))
                for relative, _candidates in runner_dependencies
            ]
            stage_dependency_map(source_dependencies, staged)
            source_missing, staging_missing = preflight_dependency_map(
                source_dependencies, staged
            )

            self.assertFalse((source / ".git").exists())
            self.assertFalse((staged / ".git").exists())
            self.assertEqual(source_missing, [])
            self.assertEqual(staging_missing, [])
            for version in range(1, 13):
                self.assertTrue(
                    (staged / f"validation/run_integrated_writer_ui_v{version}_history.py").is_file()
                )

    def test_preflight_lists_all_source_and_staging_omissions_together(self):
        with tempfile.TemporaryDirectory(prefix="pqm-package-source-") as source_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-package-stage-") as stage_tmp:
            source = Path(source_tmp)
            staged = Path(stage_tmp)
            (source / "present.py").write_text("ok", encoding="utf-8")
            (source / "stage_lost.py").write_text("ok", encoding="utf-8")
            requirements = [
                ("missing_a.py", (source / "missing_a.py",)),
                ("missing_b.py", (source / "missing_b.py",)),
                ("stage_lost.py", (source / "stage_lost.py",)),
            ]
            stage_dependency_map(requirements, staged)
            # Simulate an incomplete staging copy after source validation.
            (staged / "stage_lost.py").unlink()
            source_missing, staging_missing = preflight_dependency_map(requirements, staged)
            message = format_preflight_error(source_missing, staging_missing)

            self.assertIn("SOURCE missing:", message)
            self.assertIn("missing_a.py", message)
            self.assertIn("missing_b.py", message)
            self.assertIn("STAGING missing:", message)
            self.assertIn("stage_lost.py", message)

    def test_package_preflight_checks_separate_roots_and_reports_all_missing(self):
        minimal_manifest = {
            "integrated_history_versions": [],
            "integrity_test_versions": [],
            "integrity_manifest_dir": "validation/manifests",
            "required_local_release_tests": [],
            "snapshot_support_files": [],
            "supplemental_validation_files": [],
            "pinned_release_files": {},
            "infrastructure_auxiliary_files": [],
            "release_fixture_basenames": [],
            "root_level_release_files": [],
            "infrastructure_release_runner": "validation/run_local_release.py",
            "candidate_docker_gate": "validation/docker_release_gate.py",
            "candidate_workflow": ".github/workflows/release-checks.yml",
        }
        with tempfile.TemporaryDirectory(prefix="pqm-package-source-") as source_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-package-stage-") as stage_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-package-infra-") as infra_tmp:
            source = Path(source_tmp)
            staged = Path(stage_tmp)
            infra = Path(infra_tmp)
            (source / "source_payload.py").write_text("present", encoding="utf-8")
            (infra / "validation").mkdir(parents=True)
            (infra / "validation/run_local_release.py").write_text("runner", encoding="utf-8")
            (source / "validation").mkdir()
            (source / "validation/docker_release_gate.py").write_text("gate", encoding="utf-8")
            (source / ".github/workflows").mkdir(parents=True)
            (source / ".github/workflows/release-checks.yml").write_text("workflow", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "SOURCE missing") as raised:
                from validation.release_test_package import preflight_package
                preflight_package(source, staged, infra, "historical_integrity", minimal_manifest)

            message = str(raised.exception)
            self.assertIn("validation/release_test_package_v1.json", message)
            self.assertIn("validation/release_test_package.py", message)
            self.assertIn("STAGING missing:", message)
            self.assertIn("source_payload.py", message)
            self.assertFalse((staged / ".git").exists())


if __name__ == "__main__":
    unittest.main()
