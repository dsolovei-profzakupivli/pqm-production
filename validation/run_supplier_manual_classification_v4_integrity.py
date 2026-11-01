"""Run the v4 manual-classification contract against its exact e0fed baseline."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


BASELINE = "e0fed4139438a6e3521ac643e0dc88bdf82aebf4"
FIXTURE_RELATIVE = Path("validation/fixtures/supplier_manual_classification_v4_baseline_e0fed.zip")
FIXTURE_SHA256 = "919313390abbe5d426263800cecb48eed6826434c1b0046e514d3d5779ba94e5"
TEST_MODULE = "test_supplier_manual_classification_v4_integrity"
MANIFEST = "supplier_manual_classification_v4_contract.json"


def _files(infos):
    result = set()
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise RuntimeError("Unsafe path in exact v4 baseline fixture")
        if not info.is_dir():
            result.add(path.as_posix())
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    fixture = root / FIXTURE_RELATIVE
    raw_fixture = fixture.read_bytes()
    if hashlib.sha256(raw_fixture).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("Pinned manual-classification v4 fixture mismatch")

    with tempfile.TemporaryDirectory(prefix=".manual-classification-v4-baseline-", dir=root) as temporary:
        tree = Path(temporary) / "tree"
        tree.mkdir()
        with zipfile.ZipFile(fixture) as archive:
            infos = archive.infolist()
            paths = _files(infos)
            manifest_info = next((item for item in infos if item.filename == MANIFEST), None)
            if manifest_info is None:
                raise RuntimeError("Exact v4 baseline fixture is missing its manifest")
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
            if manifest.get("parent") != "59177be3e98540c53484962cc7f349a157e7b0bf":
                raise RuntimeError("Manual-classification v4 historical parent changed")
            if paths != set(manifest["files"]) | {MANIFEST}:
                raise RuntimeError("Exact v4 baseline fixture has an unexpected file set")
            for member in infos:
                relative = PurePosixPath(member.filename)
                target = (tree / Path(*relative.parts)).resolve()
                if not target.is_relative_to(tree):
                    raise RuntimeError("Unsafe path in exact v4 baseline fixture")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))

        env = __import__("os").environ.copy()
        env.pop("PQM_RELEASE_SOURCE_ROOT", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", TEST_MODULE, "-v"],
            cwd=tree,
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
