"""Exercise the immutable v1 snapshot verifier against real archived bytes."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
import re
import unittest
import zipfile

from validation import run_google_writer_legacy_source_snapshots_v1_history as history


ROOT = Path(__file__).resolve().parent
EXECUTION_MANIFEST = Path("validation/local_release_20261110/google_writer_legacy_snapshot_execution_v2.json")
EXECUTION_MANIFEST_SHA256 = "a5c49e57da039983bb0efcf24b46e28cd41e521daab215221fc894713ded3f2f"
SELF_FILE = "test_google_writer_legacy_source_snapshots_history_v2.py"
SELF_PINNED_TESTS = {
    SELF_FILE,
    "test_google_writer_manifest_compatibility_integrity_v2.py",
    "test_google_writer_legacy_source_snapshots_integrity_v1.py",
}


def canonical(raw):
    return raw.replace(b"\r\n", b"\n")


def canonical_self(raw):
    return re.sub(
        rb'(?m)^EXECUTION_MANIFEST_SHA256 = "(?:<pending>|[0-9a-f]{64})"$',
        b'EXECUTION_MANIFEST_SHA256 = "<manifest-sha256>"', canonical(raw),
    )


def copy_snapshot_inputs(source_root, destination):
    _, manifest = history.load_manifest(source_root)
    paths = set(manifest["scope"]) | set(manifest["preserved_manifests"])
    paths.update((str(history.MANIFEST_REL), str(history.LEGACY_ARCHIVE_REL),
                  str(history.RUNNER_FIXTURE_REL)))
    for relative in paths:
        source = history.safe_target(source_root, relative)
        target = history.safe_target(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


class GoogleWriterLegacySnapshotHistoryRunnerTests(unittest.TestCase):
    def test_additive_execution_overlay_pins_harness_and_preserves_v1(self):
        raw = canonical((ROOT / EXECUTION_MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXECUTION_MANIFEST_SHA256)
        manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-legacy-snapshot-execution")
        self.assertEqual(manifest["version"], 2)
        self.assertEqual(set(manifest["scope"]), set(manifest["files"]))
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            if relative in SELF_PINNED_TESTS:
                data = re.sub(
                    rb'(?m)^(?:MANIFEST_SHA256|EXECUTION_MANIFEST_SHA256) = "(?:<pending>|[0-9a-f]{64})"$',
                    b'PIN_SHA256 = "<manifest-sha256>"', canonical(data),
                )
            else:
                data = canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
        for relative, expected in manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_v1_integrity_test_passes_against_materialized_historical_tree(self):
        self.assertEqual(history.run_history_test(ROOT), 0)

    def test_corrupt_historical_source_file_fails_materialization(self):
        with tempfile.TemporaryDirectory(prefix="pqm-snapshot-corrupt-source-", dir=ROOT) as tmp:
            source = Path(tmp) / "source"
            destination = Path(tmp) / "tree"
            source.mkdir()
            destination.mkdir()
            copy_snapshot_inputs(ROOT, source)
            pinned = history.safe_target(source, "sandbox_runtime.py")
            pinned.write_bytes(pinned.read_bytes() + b"\ncorruption\n")
            with self.assertRaisesRegex(history.SnapshotIntegrityError, "checksum mismatch"):
                history.materialize_snapshot(source, destination)

    def test_corrupt_archive_file_fails_archive_checksum(self):
        with tempfile.TemporaryDirectory(prefix="pqm-snapshot-corrupt-archive-", dir=ROOT) as tmp:
            bad_archive = Path(tmp) / "damaged.zip"
            with zipfile.ZipFile(ROOT / history.LEGACY_ARCHIVE_REL, "r") as original:
                members = [(name, original.read(name)) for name in original.namelist()]
            with zipfile.ZipFile(bad_archive, "w", compression=zipfile.ZIP_DEFLATED) as damaged:
                for name, data in members:
                    if name == "google_writer_execution.py":
                        data += b"\ncorruption\n"
                    damaged.writestr(name, data)
            with tempfile.TemporaryDirectory(prefix="pqm-snapshot-archive-tree-", dir=ROOT) as tree:
                with self.assertRaisesRegex(history.SnapshotIntegrityError, "archive checksum mismatch"):
                    history.materialize_snapshot(ROOT, Path(tree), archive_path=bad_archive)

    def test_changed_manifest_checksum_fails_before_copy(self):
        with tempfile.TemporaryDirectory(prefix="pqm-snapshot-wrong-manifest-pin-", dir=ROOT) as tmp:
            with self.assertRaisesRegex(history.SnapshotIntegrityError, "manifest checksum mismatch"):
                history.load_manifest(ROOT, expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
