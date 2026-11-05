"""Run the immutable checkpoint v1 integrity suite on its exact c8 tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "validation/local_release_20260911/partial_reconciliation_second_run_v1.json"
FIXTURE = ROOT / "validation/fixtures/checkpointed_apply_v1_exact_c8a97d6.zip"


def main():
    import json
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = manifest["historical_checkpoint_fixture_sha256"]
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Checkpoint v1 exact-baseline fixture hash mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-checkpoint-v1-", dir=ROOT) as temporary:
        target = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            for member in archive.infolist():
                output = (target / member.filename).resolve()
                if not output.is_relative_to(target):
                    raise RuntimeError("Unsafe path in checkpoint v1 fixture")
                if member.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(member))
        print("INTEGRITY OVERLAY: checkpointed Apply v1 exact c8a97d6 tree", flush=True)
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "test_checkpointed_apply_integrity_v1", "-v"],
            cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
