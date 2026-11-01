"""Run the v3 integrity suite from its pinned exact-baseline fixture.

The historical v3 contract and test stay unchanged. The committed fixture is a
Git archive of the exact baseline tree paths required by that test, pinned by
SHA-256 in both this runner and the additive v4 integrity contract. No Git
executable or repository metadata is needed at runtime.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


BASELINE = "59177be3e98540c53484962cc7f349a157e7b0bf"
FIXTURE_RELATIVE = Path("validation/fixtures/supplier_classification_v3_baseline_59177.zip")
FIXTURE_SHA256 = "49445ff35cb5f77c77095c96b8fb4f06de358b81c40b3ccd7dc0753b8c855bf8"
TEST_MODULE = "test_supplier_classification_v3_integrity"


def _relative_files(info_list):
    files = set()
    for info in info_list:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise RuntimeError("Unsafe path in exact v3 baseline fixture")
        if not info.is_dir():
            files.add(path.as_posix())
    return files


def main():
    root = Path(__file__).resolve().parents[1]
    candidate_contract = json.loads(
        (root / "supplier_manual_classification_v4_contract.json").read_text(encoding="utf-8")
    )
    if candidate_contract.get("parent") != BASELINE:
        raise RuntimeError("Manual-classification v4 baseline mismatch")
    if candidate_contract.get("files", {}).get(FIXTURE_RELATIVE.as_posix()) != FIXTURE_SHA256:
        raise RuntimeError("Exact v3 fixture is not pinned by the additive v4 contract")
    fixture = root / FIXTURE_RELATIVE
    fixture_bytes = fixture.read_bytes()
    actual_fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    if actual_fixture_sha256 != FIXTURE_SHA256:
        raise RuntimeError("Pinned supplier-classification v3 baseline fixture mismatch")

    with tempfile.TemporaryDirectory(
        prefix=".classification-v3-exact-baseline-", dir=root
    ) as temporary:
        tree = Path(temporary) / "tree"
        tree.mkdir()
        with zipfile.ZipFile(fixture) as archive:
            members = archive.infolist()
            archive_files = _relative_files(members)
            manifest_path = "supplier_classification_v3_contract.json"
            test_path = "test_supplier_classification_v3_integrity.py"
            manifest_info = next((item for item in members if item.filename == manifest_path), None)
            if manifest_info is None:
                raise RuntimeError("Exact v3 baseline fixture is missing its contract")
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
            expected_files = (
                set(manifest["files"])
                | set(manifest["historical_manifests"])
                | {manifest_path, test_path}
            )
            if archive_files != expected_files:
                raise RuntimeError("Exact v3 baseline fixture has an unexpected file set")

            for member in members:
                relative = PurePosixPath(member.filename)
                target = (tree / Path(*relative.parts)).resolve()
                if not target.is_relative_to(tree):
                    raise RuntimeError("Unsafe path in exact v3 baseline fixture")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))

        manifest_path = tree / "supplier_classification_v3_contract.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative in manifest["historical_manifests"]:
            path = (tree / relative).resolve()
            if not path.is_relative_to(tree):
                raise RuntimeError("Unsafe historical manifest path in v3 contract")
            raw = path.read_bytes()
            lf = raw.replace(b"\r\n", b"\n")
            if b"\r" in lf:
                raise RuntimeError(f"Unexpected lone CR in historical text file: {relative}")
            path.write_bytes(lf)

        env = os.environ.copy()
        env.pop("PQM_RELEASE_SOURCE_ROOT", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", TEST_MODULE, "-v"],
            cwd=tree,
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
