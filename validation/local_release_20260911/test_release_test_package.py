"""Tests for deterministic and complete Release Gate package staging."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from validation.release_test_package import (
    PACKAGE_MANIFEST,
    format_preflight_error,
    load_package_manifest,
    package_dependency_map,
    preflight_dependency_map,
    resolve_package_source_root,
    stage_dependency_map,
)


ROOT = resolve_package_source_root(__file__)


class ReleaseTestPackageTests(unittest.TestCase):
    def test_single_manifest_covers_history_runners_tests_and_support(self):
        manifest = load_package_manifest(ROOT)
        dependencies = {path for path, _sources in package_dependency_map(
            ROOT, ROOT, manifest=manifest
        )}
        for version in manifest["integrated_history_versions"]:
            self.assertIn(f"validation/run_integrated_writer_ui_v{version}_history.py", dependencies)
        for version in manifest["integrity_test_versions"]:
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
            for version in range(1, 19):
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

    def test_flattened_test_copy_runs_manifest_readers_from_another_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="pqm-flat-source-") as source_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-flat-stage-") as stage_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-flat-cwd-") as cwd_tmp:
            source = Path(source_tmp)
            stage = Path(stage_tmp)
            cwd = Path(cwd_tmp)
            manifest = load_package_manifest(ROOT)
            (source / "validation").mkdir(parents=True)
            shutil.copy2(ROOT / "validation/release_test_package_v1.json",
                         source / "validation/release_test_package_v1.json")
            for version in manifest["integrated_history_versions"]:
                shutil.copy2(
                    ROOT / f"validation/run_integrated_writer_ui_v{version}_history.py",
                    source / f"validation/run_integrated_writer_ui_v{version}_history.py",
                )
            for name in ("integrated_snapshot_archive.py", "integrated_git_snapshot.py"):
                shutil.copy2(ROOT / "validation" / name, source / "validation" / name)

            (stage / "validation").mkdir()
            shutil.copy2(Path(__file__), stage / "test_release_test_package.py")
            shutil.copy2(ROOT / "validation/release_test_package.py",
                         stage / "validation/release_test_package.py")
            shutil.copy2(ROOT / "validation/release_test_package_v1.json",
                         stage / "validation/release_test_package_v1.json")

            environment = os.environ.copy()
            environment["PQM_RELEASE_SOURCE_ROOT"] = str(source)
            environment["PYTHONPATH"] = str(stage)
            environment.pop("PYTHONHOME", None)
            command = [
                sys.executable, "-B", "-m", "unittest", "-v",
                "test_release_test_package.ReleaseTestPackageTests.test_single_manifest_covers_history_runners_tests_and_support",
                "test_release_test_package.ReleaseTestPackageTests.test_runner_dependencies_stage_between_separate_gitless_roots",
            ]
            result = subprocess.run(command, cwd=cwd, env=environment,
                                    capture_output=True, text=True, timeout=60)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Ran 2 tests", result.stderr)
            self.assertIn("OK", result.stderr)
            self.assertFalse((source / ".git").exists())
            self.assertFalse((stage / ".git").exists())
            self.assertFalse((cwd / ".git").exists())

    def test_source_root_resolution_validates_explicit_environment_and_control_file(self):
        with tempfile.TemporaryDirectory(prefix="pqm-source-root-") as source_tmp, \
             tempfile.TemporaryDirectory(prefix="pqm-flat-module-") as module_tmp:
            source = Path(source_tmp)
            (source / "validation").mkdir(parents=True)
            module = Path(module_tmp) / "test_release_test_package.py"
            shutil.copy2(ROOT / "validation/release_test_package_v1.json",
                         source / "validation/release_test_package_v1.json")
            module.parent.mkdir(parents=True, exist_ok=True)
            module.touch()

            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(source)}):
                self.assertEqual(resolve_package_source_root(module), source.resolve())

            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(source / "missing")}):
                with self.assertRaisesRegex(RuntimeError, "does not name an existing directory"):
                    resolve_package_source_root(module)

            empty_root = Path(module_tmp) / "empty-root"
            empty_root.mkdir()
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(empty_root)}):
                with self.assertRaisesRegex(RuntimeError, "missing or invalid package manifest"):
                    resolve_package_source_root(module)
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": "  "}):
                with self.assertRaisesRegex(RuntimeError, "is set but empty"):
                    resolve_package_source_root(module)

            malformed = Path(module_tmp) / "bad-root"
            (malformed / "validation").mkdir(parents=True)
            (malformed / "validation/release_test_package_v1.json").write_text("{", encoding="utf-8")
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(malformed)}):
                with self.assertRaisesRegex(RuntimeError, "missing or invalid package manifest"):
                    resolve_package_source_root(module)

            invalid_shape = Path(module_tmp) / "bad-shape"
            (invalid_shape / "validation").mkdir(parents=True)
            (invalid_shape / "validation/release_test_package_v1.json").write_text(
                '{"schema_version":1,"integrated_history_versions":"not-a-list"}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(invalid_shape)}):
                with self.assertRaisesRegex(RuntimeError, "missing or invalid package manifest"):
                    resolve_package_source_root(module)

            invalid_top_level = Path(module_tmp) / "bad-top-level"
            (invalid_top_level / "validation").mkdir(parents=True)
            (invalid_top_level / "validation/release_test_package_v1.json").write_text(
                "[]", encoding="utf-8"
            )
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(invalid_top_level)}):
                with self.assertRaisesRegex(RuntimeError, "missing or invalid package manifest"):
                    resolve_package_source_root(module)

            with patch.dict(os.environ, {}, clear=True):
                discovered = resolve_package_source_root(ROOT / "validation/local_release_20260911/test_release_test_package.py")
                self.assertEqual(discovered, ROOT.resolve())
                with self.assertRaisesRegex(FileNotFoundError, "Could not find"):
                    resolve_package_source_root(module)

    def test_invalid_explicit_source_root_never_falls_back_to_nearby_manifest(self):
        with tempfile.TemporaryDirectory(prefix="pqm-invalid-explicit-root-") as temporary:
            parent = Path(temporary)
            (parent / "validation").mkdir()
            shutil.copy2(ROOT / "validation/release_test_package_v1.json",
                         parent / "validation/release_test_package_v1.json")
            module = parent / "nested" / "test_release_test_package.py"
            module.parent.mkdir()
            module.touch()
            invalid_explicit = parent / "does-not-exist"
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(invalid_explicit)}):
                with self.assertRaisesRegex(RuntimeError, "does not name an existing directory"):
                    resolve_package_source_root(module)


if __name__ == "__main__":
    unittest.main()
