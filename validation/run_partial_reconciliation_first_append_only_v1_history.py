"""Run the immutable first APPEND_ONLY profile contract on its exact 1fd48f4 tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "validation/fixtures/partial_reconciliation_first_append_only_v1_exact_1fd48f4.zip"
FIXTURE_SHA256 = "f2a98f2d78c5b0e2735db61ead28a7f04d0d05c023f48e4eece6036ebfe1d879"


def main():
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("First APPEND_ONLY v1 exact-source fixture hash mismatch")
    with tempfile.TemporaryDirectory(prefix=".pqm-first-append-only-v1-history-", dir=ROOT) as temporary:
        target = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            for member in archive.infolist():
                output = (target / member.filename).resolve()
                if not output.is_relative_to(target):
                    raise SystemExit("Unsafe path in first APPEND_ONLY v1 fixture")
                if member.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(member))
        print("INTEGRITY OVERLAY: first APPEND_ONLY v1 exact 1fd48f4 source tree", flush=True)
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest",
             "test_partial_reconciliation_first_append_only_integrity_v1", "-v"],
            cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
