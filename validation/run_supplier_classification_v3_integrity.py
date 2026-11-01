"""Run the v3 integrity suite from its exact baseline Git tree.

The v3 test and contract remain byte-for-byte historical. The temporary tree
is archived from the pinned baseline commit, then only listed historical text
manifests are materialized as LF so the unchanged Windows-era raw-byte check
is deterministic across Windows and Linux checkouts.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


BASELINE = "59177be3e98540c53484962cc7f349a157e7b0bf"
TEST_MODULE = "test_supplier_classification_v3_integrity"


def main():
    root = Path(__file__).resolve().parents[1]
    resolved = subprocess.check_output(
        ["git", "rev-parse", f"{BASELINE}^{{commit}}"], cwd=root, text=True
    ).strip()
    if resolved != BASELINE:
        raise RuntimeError("Pinned supplier-classification v3 baseline mismatch")

    with tempfile.TemporaryDirectory(
        prefix=".classification-v3-exact-baseline-", dir=root
    ) as temporary:
        temporary = Path(temporary)
        archive = temporary / "baseline.zip"
        tree = temporary / "tree"
        tree.mkdir()
        subprocess.run(
            ["git", "archive", "--format=zip", f"--output={archive}", BASELINE],
            cwd=root,
            check=True,
        )
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (tree / member.filename).resolve()
                if not target.is_relative_to(tree):
                    raise RuntimeError("Unsafe path in exact v3 baseline archive")
            bundle.extractall(tree)

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
