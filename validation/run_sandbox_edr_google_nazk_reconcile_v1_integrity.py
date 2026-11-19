"""Run the unchanged EDR/NAZK v1 integrity contract on its exact candidate overlay."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ARCHIVE = Path("validation/fixtures/edr_google_nazk_reconcile_v1_candidate_a40aa70.zip")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    archive_path = repo / ARCHIVE
    with tempfile.TemporaryDirectory(prefix="pqm-edr-nazk-v1-integrity-") as tmp:
        target = Path(tmp).resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                destination = (target / member.filename).resolve()
                if not destination.is_relative_to(target):
                    raise RuntimeError("Unsafe path in EDR/NAZK v1 candidate overlay")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run([
            sys.executable, "-B", "-m", "unittest",
            "validation.local_release_20260911.test_sandbox_edr_google_nazk_reconcile_integrity", "-v",
        ], cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
