"""Run the unchanged date-only/status v2 contract on its exact candidate tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


FIXTURE = Path("validation/fixtures/date_only_status_integrated_v2_a1f8.zip")
FIXTURE_SHA256 = "1df484d5a57fc9bd02548b58d63ec5d5faddeb9fbb2b8541c488473ea4792b02"


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    archive = repo / FIXTURE
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Date-only/status v2 exact-tree fixture SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-date-only-status-v2-") as temporary:
        tree = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = (tree / member.filename).resolve()
                if not target.is_relative_to(tree):
                    raise SystemExit("Unsafe path in date-only/status v2 fixture")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read(member))
        env = os.environ.copy()
        env.pop("PQM_RELEASE_SOURCE_ROOT", None)
        env.pop("PQM_RELEASE_MODE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest",
             "validation.local_release_20260911.test_date_only_edr_status_integrated_integrity_v2", "-v"],
            cwd=tree, env=env, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
