"""Run the unchanged Preview workflow v1 contract on its exact 067e2e8 tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "validation/fixtures/sandbox_preview_workflow_v1_exact_067e2e8.zip"
FIXTURE_SHA256 = "c995751ff59f1cb3ea10d6e729f7d3a6f0e79d133bd4e809c5a91843d6c3600a"


def main():
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Sandbox Preview workflow v1 exact-source fixture hash mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-preview-workflow-v1-history-") as temporary:
        target = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            for member in archive.infolist():
                output = (target / member.filename).resolve()
                if not output.is_relative_to(target):
                    raise SystemExit("Unsafe path in Sandbox Preview workflow v1 fixture")
                if member.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(member))
        print("INTEGRITY OVERLAY: Sandbox Preview workflow v1 exact 067e2e8 tree", flush=True)
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "test_sandbox_preview_workflow_integrity_v1", "-v"],
            cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
