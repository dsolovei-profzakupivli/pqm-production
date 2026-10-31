"""Run the two unchanged feature contracts against their exact source trees."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = (
    ("classification", "validation/fixtures/integrated_classification_v1_overlay_6b9830b.zip",
     "2f671afe120e52b169bc354ee568a9af19c32772b105061835f40fb1146b5166",
     "test_supplier_classification_integrity.py"),
    ("writer", "validation/fixtures/integrated_writer_v1_overlay_64f7fda.zip",
     "6507d95a38b96fbe0b2bac4d5c061f85c47ef52c5ed0ad109c5a875d52ac78b7",
     "validation/local_release_20260911/test_google_writer_update_append_integrity.py"),
)


def extract_checked(archive_path, destination):
    base = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(base):
                raise RuntimeError("Unsafe path in source integrity overlay")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))


def main():
    with tempfile.TemporaryDirectory(prefix="pqm-integrity-overlays-") as temporary:
        for name, relative, expected_sha, test_module in OVERLAYS:
            archive = ROOT / relative
            raw = archive.read_bytes()
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                raise RuntimeError(f"{name} exact-tree overlay SHA-256 mismatch")
            target = Path(temporary) / name
            target.mkdir()
            extract_checked(archive, target)
            print(f"INTEGRITY OVERLAY: {name} exact source tree", flush=True)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", test_module, "-v"],
                cwd=target, env=os.environ.copy(), check=False)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
