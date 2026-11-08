"""Run the prepared-APPEND_ONLY retry v1 integrity pin on its exact snapshot."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "validation/fixtures/prepared_append_only_retry_v1_exact_d386586.zip"
MODULE = "test_partial_reconciliation_prepared_append_only_retry_integrity_v1"


def main():
    with tempfile.TemporaryDirectory(prefix="pqm-prepared-retry-v1-") as temporary:
        destination = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise RuntimeError("Unsafe member in prepared retry historical fixture")
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
            cwd=destination,
            env=environment,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
