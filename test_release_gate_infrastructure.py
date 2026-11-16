"""Regression tests for local Release Gate staging and isolation adapters."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import zipfile

import validation.run_local_release as release
import validation.run_c246_historical_integrity_snapshots_v1 as c246_snapshots


ROOT = Path(__file__).resolve().parent


class ReleaseGateInfrastructureTests(unittest.TestCase):
    def test_gitattributes_is_copied_into_candidate_staging_tree(self):
        with tempfile.TemporaryDirectory(prefix="pqm-gitattributes-stage-") as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "staged"
            source.mkdir()
            content = (
                "/validation/run_c246_historical_integrity_snapshots_v1.py text eol=lf\n"
                "/validation/c246_historical_integrity_snapshots_v1.json text eol=lf\n"
            ).encode("utf-8")
            (source / ".gitattributes").write_bytes(content)

            staged = release.stage_gitattributes(source, target)

            self.assertEqual(staged, target / ".gitattributes")
            self.assertTrue(staged.is_file())
            self.assertEqual(staged.read_bytes(), content)

    def test_integrated_history_runners_are_present_in_the_delivered_test_package(self):
        required = (
            "validation/run_integrated_writer_ui_v1_history.py",
            "validation/run_integrated_writer_ui_v2_history.py",
            "validation/run_integrated_writer_ui_v3_history.py",
            "validation/run_integrated_writer_ui_v4_history.py",
            "validation/run_integrated_writer_ui_v5_history.py",
        )
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(), f"missing staged runner: {relative}")

    def test_integrated_snapshot_archives_are_available_to_the_docker_gate(self):
        required = (
            "validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip",
            "validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip",
            "validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip",
            "validation/fixtures/pqm_sync_ui_integrated_v4_654bd0de.zip",
            "validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip",
        )
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        docker_gate = (ROOT / "validation/docker_release_gate.py").read_text(encoding="utf-8")
        runner_source = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("validation/run_local_release.py", docker_gate)
        self.assertIn("test_release_gate_infrastructure.py", docker_gate)
        self.assertNotIn("*.zip", dockerignore)
        for relative in required:
            with self.subTest(path=relative):
                self.assertIn(Path(relative).name, runner_source)
                self.assertTrue((ROOT / relative).is_file(), f"missing immutable Docker fixture: {relative}")

    def test_v5_historical_runner_uses_pinned_fixture_without_git(self):
        with tempfile.TemporaryDirectory(prefix="pqm-integrated-v5-no-git-") as temporary:
            package = Path(temporary)
            validation = package / "validation"
            (validation / "fixtures").mkdir(parents=True)
            runner = "validation/run_integrated_writer_ui_v5_history.py"
            fixture = "validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip"
            shutil.copy2(ROOT / runner, package / runner)
            shutil.copy2(ROOT / fixture, package / fixture)
            result = subprocess.run(
                [sys.executable, "-B", str(package / runner)],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v5_historical_runner_uses_pinned_fixture_without_git(self):
        with tempfile.TemporaryDirectory(prefix="pqm-integrated-v5-no-git-") as temporary:
            package = Path(temporary)
            validation = package / "validation"
            (validation / "fixtures").mkdir(parents=True)
            runner = "validation/run_integrated_writer_ui_v5_history.py"
            fixture = "validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip"
            shutil.copy2(ROOT / runner, package / runner)
            shutil.copy2(ROOT / fixture, package / fixture)
            result = subprocess.run(
                [sys.executable, "-B", str(package / runner)],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd(self):
        docker_gate = (ROOT / "validation/docker_release_gate.py").read_text(encoding="utf-8")
        self.assertIn("validation/run_local_release.py", docker_gate)
        archive = ROOT / "validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip"
        original_is_file = Path.is_file

        def archive_missing(path):
            if path == archive:
                return False
            return original_is_file(path)

        expected_cwd = Path.cwd()
        with patch.dict(os.environ, {"PQM_RELEASE_MODE": ""}):
            with patch.object(sys, "argv", ["run_local_release.py", "test_nazk_workflow.py"]):
                with patch.object(Path, "is_file", archive_missing):
                    with patch.object(
                        release.subprocess, "run", return_value=SimpleNamespace(returncode=1)
                    ) as run:
                        with self.assertRaisesRegex(
                            RuntimeError, "Integrated v2 immutable snapshot could not be staged"
                        ):
                            release.main()

        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["cwd"], expected_cwd)
        self.assertTrue(
            str(run.call_args.args[0][1]).endswith("run_integrated_writer_ui_v2_history.py")
        )

    def test_workflow_routes_historical_and_current_integrity_checks(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        c246_runner = "validation/run_c246_historical_integrity_snapshots_v1.py"
        historical_runner = "validation/run_google_writer_historical_integrity_snapshots_v1.py"
        historical_v4 = "test_google_writer_append_continuation_integrity_v4"
        historical_apply_v5 = "test_google_writer_apply_result_integrity_v5"
        historical_apply_v6 = "test_google_writer_apply_result_integrity_v6"
        previous_apply_overlay = "test_google_writer_apply_result_integrity_v7"
        historical_apply_v9 = "test_google_writer_apply_result_integrity_v9"
        historical_continuation_v5 = "test_google_writer_append_continuation_integrity_v5"
        historical_apply_v10 = "test_google_writer_apply_result_integrity_v10"
        integrated_v1 = "test_google_writer_integrated_candidate_integrity_v1"
        previous_overlay = "test_google_writer_integrated_candidate_integrity_v3"
        previous_integrated_overlay = "test_google_writer_integrated_candidate_integrity_v5"
        current_overlay = "test_google_writer_integrated_candidate_integrity_v6"
        integrated_v1_runner = "validation/run_integrated_writer_ui_v1_history.py"
        integrated_v1_snapshot = "3eda8169d8dae0d76bf14b276c16e6773dd746d6"
        integrated_v2_runner = "validation/run_integrated_writer_ui_v2_history.py"
        integrated_v2_snapshot = "0d7e05984fb9b1fc7276b4cc1d8176dec383ef08"
        integrated_v3_runner = "validation/run_integrated_writer_ui_v3_history.py"
        integrated_v4_runner = "validation/run_integrated_writer_ui_v4_history.py"
        integrated_v5_runner = "validation/run_integrated_writer_ui_v5_history.py"
        integrated_v4_snapshot = "654bd0de0e5b3de6be61c5293a9fc00cf17217c3"
        integrated_v3_snapshot = "8c6ba07372196b1919a88beb7da3078e6c53d4d0"
        direct_historical_test = "python -B -m unittest -v test_legacy_reconciliation_evidence_v2_integrity"

        self.assertIn("node --test", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/legacy-reconciliation-evidence-v2.test.cjs", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python -m venv \"$RUNNER_TEMP/pqm-release-python\"", workflow)
        self.assertIn("pip install --disable-pip-version-check -r requirements.txt", workflow)
        self.assertIn("$RUNNER_TEMP/pqm-release-python/bin/python\" -B validation/run_c246_historical_integrity_snapshots_v1.py", workflow)
        self.assertIn("git archive ce722e3ed654a0e30be3b048a292e1e7e6ba0828", workflow)
        self.assertIn("git archive 2a4e4bff0bbbe84670d3bb10a5ba4b90347a7d78", workflow)
        self.assertIn("test_google_writer_append_continuation_integrity_v2", workflow)
        self.assertIn("test_google_writer_append_continuation_integrity_v3", workflow)
        self.assertIn("test_google_writer_update_append_v2_integrity", workflow)
        self.assertIn("test_google_writer_update_append_v3_integrity", workflow)
        self.assertIn(c246_runner, workflow)
        self.assertIn(historical_runner, workflow)
        self.assertIn(historical_v4, workflow)
        self.assertIn(historical_apply_v5, workflow)
        self.assertIn(historical_apply_v6, workflow)
        self.assertIn("git archive 86b6ad82105fdcd7fa530a872943525af812ec47", workflow)
        self.assertIn("git archive 8bf5fb0188bebf6f2b35583ec018848c914b714c", workflow)
        self.assertIn("git archive 926ae60ff3412a9c236c903b70623881459d871c", workflow)
        self.assertIn("git archive b988f140af37c45bd5461735cf40d18cd00d741a", workflow)
        self.assertIn("git archive 9b38a258c0d279f33541dac6e95d12d3057a9b70", workflow)
        self.assertIn(previous_apply_overlay, workflow)
        self.assertIn(historical_apply_v9, workflow)
        self.assertIn(historical_continuation_v5, workflow)
        self.assertIn(historical_apply_v10, workflow)
        self.assertIn(integrated_v1_runner, workflow)
        self.assertIn(integrated_v2_runner, workflow)
        self.assertIn(integrated_v3_runner, workflow)
        self.assertIn(integrated_v4_runner, workflow)
        self.assertIn(integrated_v5_runner, workflow)
        for version in ("V1", "V2", "V3", "V4"):
            self.assertNotIn(f"PQM_INTEGRATED_{version}_ARCHIVE_OUT=validation/fixtures/", workflow)
        self.assertIn(
            "test_release_gate_infrastructure.ReleaseGateInfrastructureTests."
            "test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd", workflow
        )
        self.assertIn(current_overlay, workflow)
        self.assertNotIn(previous_overlay, workflow)
        self.assertNotIn(direct_historical_test, workflow)
        self.assertLess(workflow.index(c246_runner), workflow.index(historical_runner))
        self.assertLess(workflow.index(historical_apply_v5), workflow.index(historical_runner))
        self.assertLess(workflow.index(historical_runner), workflow.index(historical_apply_v6))
        self.assertLess(workflow.index(historical_apply_v6), workflow.index(previous_apply_overlay))
        self.assertIn("test_google_writer_apply_result_integrity_v8)", workflow)
        self.assertLess(workflow.index(previous_apply_overlay), workflow.index("test_google_writer_apply_result_integrity_v8)"))
        self.assertLess(workflow.index("test_google_writer_apply_result_integrity_v8)"), workflow.index(historical_apply_v9))
        self.assertLess(workflow.index(historical_apply_v9), workflow.index(historical_continuation_v5))
        self.assertLess(workflow.index(historical_continuation_v5), workflow.index(historical_apply_v10))
        self.assertLess(workflow.index(historical_apply_v10), workflow.index(integrated_v1_runner))
        self.assertLess(workflow.index(integrated_v1_runner), workflow.index(integrated_v2_runner))
        self.assertLess(workflow.index(integrated_v2_runner), workflow.index(integrated_v3_runner))
        self.assertLess(workflow.index(integrated_v3_runner), workflow.index(integrated_v4_runner))
        self.assertLess(workflow.index(integrated_v4_runner), workflow.index(integrated_v5_runner))
        self.assertLess(workflow.index(integrated_v5_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))

        snapshot_route = workflow.split('writer_v5_v10_snapshot=', 1)[1].split(integrated_v1_runner, 1)[0]
        self.assertIn('git archive 9b38a258c0d279f33541dac6e95d12d3057a9b70', snapshot_route)
        self.assertIn('(cd "$writer_v5_v10_snapshot"', snapshot_route)
        self.assertIn(historical_continuation_v5, snapshot_route)
        self.assertIn(historical_apply_v10, snapshot_route)
        self.assertNotIn(current_overlay, snapshot_route)
        self.assertNotIn(integrated_v1, snapshot_route)
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))

        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        integrated_history_runner = (ROOT / integrated_v1_runner).read_text(encoding="utf-8")
        integrated_v2_history_runner = (ROOT / integrated_v2_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v1_snapshot, integrated_history_runner)
        self.assertIn("git', 'archive', '--format=zip'", integrated_history_runner)
        self.assertIn(integrated_v1, integrated_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip')", integrated_history_runner)
        self.assertIn(integrated_v2_snapshot, integrated_v2_history_runner)
        self.assertIn("'git', 'archive', '--format=zip'", integrated_v2_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v2", integrated_v2_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip')", integrated_v2_history_runner)
        integrated_v3_history_runner = (ROOT / integrated_v3_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v3_snapshot, integrated_v3_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v3", integrated_v3_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip')", integrated_v3_history_runner)
        integrated_v4_history_runner = (ROOT / integrated_v4_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v4_snapshot, integrated_v4_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v4", integrated_v4_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v4_654bd0de.zip')", integrated_v4_history_runner)
        integrated_v5_history_runner = (ROOT / integrated_v5_runner).read_text(encoding="utf-8")
        self.assertIn("cd01e1376114781e43d408b5b83ee15e22050a53", integrated_v5_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v5", integrated_v5_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip')", integrated_v5_history_runner)
        self.assertIn("'test_legacy_reconciliation_evidence_v2_integrity'", runner)
        self.assertIn("c246 contracts are run by the mandatory workflow snapshot step", runner)
        self.assertNotIn("run_c246_historical_integrity_snapshots_v1.py", runner)
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", runner)
        self.assertNotIn("'test_google_writer_apply_result_diagnostic'", runner.split("HISTORICAL_INTEGRITY_MODULES", 1)[1].split("}\nEXACT_TREE_OVERLAY_MODULES", 1)[0])
        historical_modules = runner.split("HISTORICAL_INTEGRITY_MODULES", 1)[1].split("}\nEXACT_TREE_OVERLAY_MODULES", 1)[0]
        self.assertNotIn("'test_google_writer_integrated_candidate_integrity_v1'", historical_modules)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v2'", historical_modules)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v3'", historical_modules)
        exact_modules = runner.split("EXACT_TREE_OVERLAY_MODULES", 1)[1].split("}", 1)[0]
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v1'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v2'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v3'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v4'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v6'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v2'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v3'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v4'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v5'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v5'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v6'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v7'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v8'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v9'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v10'", exact_modules)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v2", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v3", runner)
        self.assertIn("run_integrated_writer_ui_v1_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v2_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v3_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v4_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v5_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v6", runner)
        self.assertIn("pqm_sync_ui_integrated_v1_3eda816.zip", runner)
        self.assertIn("pqm_sync_ui_integrated_v2_0d7e059.zip", runner)
        self.assertIn("pqm_sync_ui_integrated_v4_654bd0de.zip", runner)
        self.assertIn("pqm_sync_ui_integrated_v5_cd01e13.zip", runner)
        self.assertNotIn("'test_google_writer_update_append_v2_integrity'", exact_modules)
        self.assertNotIn("'test_google_writer_update_append_v3_integrity'", exact_modules)
        self.assertNotIn("'test_google_writer_apply_result_diagnostic'", exact_modules)
        self.assertIn("test_google_writer_apply_result_integrity_v7", workflow)
        self.assertIn("test_google_writer_apply_result_integrity_v8", workflow)
        self.assertIn("test_google_writer_saved_continuation_audit", workflow)
        browser_runner = (ROOT / "validation/google_writer_preview_modal_browser.cjs").read_text(encoding="utf-8")
        self.assertIn("validation/google_writer_apply_result_ui.test.cjs", browser_runner)
        self.assertIn("node validation/google_writer_preview_modal_browser.cjs", workflow)
        layout_runner = (ROOT / "validation/google_writer_apply_modal_layout_browser.cjs").read_text(encoding="utf-8")
        self.assertIn("innerWidth", layout_runner)
        self.assertIn("footer stays fixed while scrolling", layout_runner)
        self.assertIn("node validation/google_writer_apply_modal_layout_browser.cjs", workflow)

    def test_c246_route_manifest_is_pinned_and_covers_all_historical_modules_once(self):
        manifest_path = ROOT / "validation/c246_historical_integrity_snapshots_v1.json"
        raw = manifest_path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), c246_snapshots.MANIFEST_SHA256)
        manifest = c246_snapshots.load_manifest()
        modules = [test["module"] for route in manifest["routes"] for test in route["tests"]]
        self.assertEqual(len(modules), 16)
        self.assertEqual(len(set(modules)), len(modules))
        self.assertEqual(
            set(modules),
            {
                "test_google_sandbox_baseline_compatibility", "test_halloween_motion_integration",
                "test_sandbox_personal_theme", "test_sandbox_appeals_scenario_api_integrity",
                "test_sandbox_appeals_scenario_readonly_integrity", "test_sandbox_nazk_scroll_integrity",
                "test_sandbox_dst_hotfix_integrity", "test_sandbox_nazk_appeals_stabilization_integrity",
                "test_sandbox_nazk_appeals_stabilization_v3_integrity",
                "test_sandbox_nazk_appeals_stabilization_v4_integrity",
                "test_sandbox_nazk_appeals_stabilization_v5_integrity",
                "test_sandbox_nazk_recovery_integrity", "test_sandbox_nazk_recovery_qualification_integrity",
                "test_sandbox_nazk_columns_integrity", "test_sandbox_nazk_preview_integrity",
                "test_sandbox_ui_integrated_d457_integrity",
            },
        )
        routes_by_commit = {route["commit"]: {test["module"] for test in route["tests"]}
                            for route in manifest["routes"]}
        self.assertEqual(routes_by_commit, {
            "b2027e6d687bc4018a2720f10fae228ccff7b201": {
                "test_google_sandbox_baseline_compatibility", "test_halloween_motion_integration"},
            "fbcce44cecf0923e4818ddeab269e478fe73939d": {"test_sandbox_personal_theme"},
            "b529ae3648f30708df23c87c9603d2bf45df6ac9": {
                "test_sandbox_appeals_scenario_api_integrity", "test_sandbox_appeals_scenario_readonly_integrity",
                "test_sandbox_nazk_scroll_integrity"},
            "990483222f7e65517befc285516a9d80aee2580d": {"test_sandbox_dst_hotfix_integrity"},
            "f6070a003c2442558303cfd9692d68cc6dfc268e": {"test_sandbox_nazk_appeals_stabilization_integrity"},
            "c246edefaa676d137d3f38d40f18d039f7b5bac2": {
                "test_sandbox_nazk_appeals_stabilization_v3_integrity",
                "test_sandbox_nazk_appeals_stabilization_v4_integrity",
                "test_sandbox_nazk_appeals_stabilization_v5_integrity",
                "test_sandbox_nazk_recovery_integrity", "test_sandbox_nazk_recovery_qualification_integrity"},
            "a168b61506fbde4f7a8d8bb80bbb40a98d6073f0": {"test_sandbox_nazk_columns_integrity"},
            "af8202b4e968f09e55ac5c6855ad29a6f2c05bc1": {"test_sandbox_nazk_preview_integrity"},
            "bddd5f6515f594304162e99e203fa82ece065cbf": {"test_sandbox_ui_integrated_d457_integrity"},
        })
        self.assertEqual(len(manifest["routes"]), 9)
        archived_routes = [route for route in manifest["routes"] if "archive" in route]
        self.assertEqual(len(archived_routes), 1)
        self.assertEqual(archived_routes[0]["archive_sha256"],
                         "e0931cc43d5c99a001771fdd12ef5bea6a87003400a458c9a3f197372671c865")

    def test_c246_snapshot_materialization_fails_closed_on_missing_commit_and_bad_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Snapshot Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "snapshot-test@example.invalid"], check=True)
            (repo / "test_example_integrity.py").write_bytes(b"# exact historical test\n")
            subprocess.run(["git", "-C", str(repo), "add", "test_example_integrity.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "snapshot fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
            test_hash = hashlib.sha256((repo / "test_example_integrity.py").read_bytes()).hexdigest()
            route = {"commit": commit, "tree": tree, "tests": [{
                "module": "test_example_integrity", "path": "test_example_integrity.py", "sha256": test_hash,
            }]}
            snapshot_root = root / "snapshot"
            c246_snapshots.materialize_snapshot(repo, route, snapshot_root)
            self.assertEqual((snapshot_root / "test_example_integrity.py").read_bytes(), b"# exact historical test\n")

            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, {**route, "commit": "0" * 40}, root / "missing-commit")
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, {**route, "tree": "0" * 40}, root / "wrong-tree")
            bad_test = {**route, "tests": [{**route["tests"][0], "sha256": "0" * 64}]}
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, bad_test, root / "wrong-test-hash")

    def test_c246_offline_historical_copy_is_pinned_to_the_exact_git_tree(self):
        manifest = c246_snapshots.load_manifest()
        route = next(route for route in manifest["routes"] if route["commit"].startswith("af8202b"))
        archive = ROOT / route["archive"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_git = root / "no-git-history"
            empty_git.mkdir()
            materialized = root / "materialized"
            materialized.mkdir()
            code, count = c246_snapshots.run_route(empty_git, route, materialized)
            self.assertEqual((code, count), (0, 1))
            snapshot_root = materialized / route["commit"]
            self.assertTrue((snapshot_root / "test_sandbox_nazk_preview_integrity.py").is_file())
            self.assertTrue((snapshot_root / "validation/fixtures/nazk_preview_baseline_f394d4c.zip").is_file())
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_archived_snapshot(
                    archive, "0" * 64, route, Path(tmp) / "corrupt")

    def test_historical_fixture_staging_uses_authentic_fixture_only_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historic = root / "historic"
            infrastructure = root / "infrastructure"
            old_fixture = historic / "validation/fixtures" / "snapshot.zip"
            pinned_fixture = infrastructure / "validation/fixtures" / "snapshot.zip"
            old_fixture.parent.mkdir(parents=True)
            pinned_fixture.parent.mkdir(parents=True)
            old_fixture.write_bytes(b"historical-source-fixture")
            pinned_fixture.write_bytes(b"pinned-fixture")
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "historical_integrity"), old_fixture)

            old_fixture.unlink()
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "historical_integrity"), pinned_fixture)
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "candidate"), old_fixture)
            with self.assertRaises(ValueError):
                release.release_fixture_source(historic, infrastructure, "../server.py", "historical_integrity")

    def test_windows_sqlite_uri_is_normalized_without_changing_mode_or_other_uris(self):
        normalized = release.normalize_windows_sqlite_uri(r"file:C:\pqm-test\db.sqlite3?mode=ro")
        self.assertTrue(normalized.startswith("file:///"))
        self.assertTrue(normalized.endswith("?mode=ro"))
        self.assertEqual(release.normalize_windows_sqlite_uri("file:relative.sqlite3?mode=ro"),
                         "file:relative.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri("file:///tmp/pqm-test.sqlite3?mode=ro"),
                         "file:///tmp/pqm-test.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri(":memory:"), ":memory:")

    def test_historical_snapshot_ledger_is_complete_and_archive_hashes_match(self):
        ledger_path = ROOT / "validation/google_writer_historical_integrity_snapshots_v1.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        archive_path = ROOT / ledger["archive"]
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), ledger["archive_sha256"])
        self.assertGreaterEqual(len(ledger["snapshots"]), 11)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for snapshot_id, snapshot in ledger["snapshots"].items():
                prefix = f"snapshots/{snapshot_id}/"
                self.assertIn(prefix + snapshot["test"], names)
                self.assertTrue(snapshot["commit"].startswith(tuple("0123456789abcdef")))
                self.assertEqual({name[len(prefix):] for name in names if name.startswith(prefix)},
                                 set(snapshot["files"]))
                for relative, expected in snapshot["files"].items():
                    with self.subTest(snapshot=snapshot_id, path=relative):
                        self.assertEqual(hashlib.sha256(archive.read(prefix + relative)).hexdigest(), expected)

    def test_historical_runner_fails_closed_instead_of_falling_back_to_current_files(self):
        runner = (ROOT / "validation/run_google_writer_historical_integrity_snapshots_v1.py").read_text(encoding="utf-8")
        self.assertIn("snapshot ledger missing; refusing candidate-source fallback", runner)
        self.assertIn("snapshot archive missing; refusing candidate-source fallback", runner)
        harness = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", harness)
        self.assertIn("google_writer_historical_integrity_snapshots_v1_compact.zip", harness)
        self.assertIn("google_writer_historical_integrity_snapshots_v1.json", harness)
        self.assertIn("PQM_RELEASE_INFRA_ROOT", harness)
        self.assertIn("Path(__file__).resolve().parents[1]).resolve()", harness)
        self.assertIn("sandbox_runtime_messages_integrated_v1_86ea864.py", harness)


if __name__ == "__main__":
    unittest.main()
