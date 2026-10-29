"""Run the unchanged timezone-alias integrity contract on its exact 6c310 baseline."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


FIXTURE = Path("validation/fixtures/google_edr_timezone_alias_v1_baseline_6c310.zip")
FIXTURE_SHA256 = "854794f04c376f3e019b8371c06b5dc041592a875df7c57760a2c9b98b47ffc6"
EXPECTED_FILES = {
    "server.py",
    "validation/local_release_20260911/google_edr_timezone_alias_v1.json",
    "validation/local_release_20260911/test_google_edr_timezone_alias_integrity_v1.py",
    "validation/local_release_20260911/test_sandbox_edr_review.py",
    "validation/local_release_20260911/test_sandbox_edr_google_nazk_contract_v2_integrity.py",
    "validation/run_local_release.py",
    "validation/fixtures/edr_google_nazk_contract_v2_baseline_64f7fda.zip",
}


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    fixture = repo / FIXTURE
    content = fixture.read_bytes()
    if hashlib.sha256(content).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Timezone-alias historical baseline fixture SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-google-edr-tz-v1-") as temporary:
        tree = Path(temporary).resolve()
        with zipfile.ZipFile(fixture) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != EXPECTED_FILES:
                raise SystemExit("Unexpected timezone-alias historical fixture members")
            for relative in sorted(members):
                destination = (tree / relative).resolve()
                if not destination.is_relative_to(tree):
                    raise SystemExit("Unsafe path in timezone-alias historical fixture")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(relative))
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(tree)
        return subprocess.run([
            sys.executable, "-B", "-m", "unittest",
            "validation.local_release_20260911.test_google_edr_timezone_alias_integrity_v1", "-v",
        ], cwd=tree, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
