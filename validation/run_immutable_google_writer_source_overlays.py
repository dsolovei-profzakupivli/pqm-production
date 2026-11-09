"""Run historical Google Writer exact-source checks from immutable snapshots."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = (
    ("google_writer_legacy_reconciliation_v3_immutable.zip",
     "test_legacy_append_reconciliation_integrity_v3"),
    ("google_writer_legacy_sheet_bounds_v1_immutable.zip",
     "validation.local_release_20260911.test_legacy_sheet_read_bounds_integrity_v1"),
)


def extract_snapshot(archive_path, destination):
    base = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(base):
                raise RuntimeError("Unsafe path in immutable Google Writer snapshot")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))


def main():
    for archive_name, module in SNAPSHOTS:
        archive_path = ROOT / "validation/fixtures" / archive_name
        with tempfile.TemporaryDirectory(prefix="pqm-google-writer-legacy-snapshot-", dir=ROOT) as tmp:
            destination = Path(tmp).resolve()
            extract_snapshot(archive_path, destination)
            environment = os.environ.copy()
            environment["PQM_RELEASE_SOURCE_ROOT"] = str(destination)
            environment.pop("PQM_RELEASE_MODE", None)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "-v", module],
                cwd=destination, env=environment, check=False,
            )
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
