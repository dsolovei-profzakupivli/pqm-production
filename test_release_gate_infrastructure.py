"""Regression tests for local Release Gate staging and isolation adapters."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import validation.run_local_release as release
import validation.run_c246_historical_integrity_snapshots_v1 as c246_snapshots


ROOT = Path(__file__).resolve().parent


class ReleaseGateInfrastructureTests(unittest.TestCase):
    def test_workflow_routes_historical_and_current_integrity_checks(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        c246_runner = "validation/run_c246_historical_integrity_snapshots_v1.py"
        historical_runner = "validation/run_google_writer_historical_integrity_snapshots_v1.py"
        current_overlay = "test_google_writer_append_continuation_integrity_v3"
        direct_historical_test = "python -B -m unittest -v test_legacy_reconciliation_evidence_v2_integrity"

        self.assertIn("node --test", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/legacy-reconciliation-evidence-v2.test.cjs", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python -m venv \"$RUNNER_TEMP/pqm-release-python\"", workflow)
        self.assertIn("pip install --disable-pip-version-check -r requirements.txt", workflow)
        self.assertIn("$RUNNER_TEMP/pqm-release-python/bin/python\" -B validation/run_c246_historical_integrity_snapshots_v1.py", workflow)
        self.assertIn(c246_runner, workflow)
        self.assertIn(historical_runner, workflow)
        self.assertIn(current_overlay, workflow)
        self.assertNotIn(direct_historical_test, workflow)
        self.assertLess(workflow.index(c246_runner), workflow.index(historical_runner))
        self.assertLess(workflow.index(historical_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))

        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("'test_legacy_reconciliation_evidence_v2_integrity'", runner)
        self.assertIn("c246 contracts are run by the mandatory workflow snapshot step", runner)
        self.assertNotIn("run_c246_historical_integrity_snapshots_v1.py", runner)
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", runner)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v3'", runner.split("HISTORICAL_INTEGRITY_MODULES", 1)[1].split("]", 1)[0])

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
