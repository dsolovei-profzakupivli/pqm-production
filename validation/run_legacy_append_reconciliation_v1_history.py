"""Run legacy APPEND reconciliation v1 against its immutable 1111eb9 source snapshot."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "validation/fixtures/legacy_append_reconciliation_v1_exact_1111eb9.zip"
MODULE = "test_legacy_append_reconciliation_integrity_v1"


def main():
    with tempfile.TemporaryDirectory(prefix="pqm-legacy-append-reconciliation-v1-") as temporary:
        destination = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise RuntimeError("Unsafe member in legacy reconciliation historical fixture")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
        environment = os.environ.copy()
        environment["PQM_RELEASE_SOURCE_ROOT"] = str(destination)
        environment.pop("PQM_RELEASE_MODE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-q", MODULE],
            cwd=destination, env=environment, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
