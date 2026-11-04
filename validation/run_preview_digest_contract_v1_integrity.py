"""Run the unchanged digest v1 integrity contract on its exact 3a63ac tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "validation/fixtures/preview_digest_contract_v1_baseline_3a63ac.zip"
ARCHIVE_SHA256 = "ac725c784a9684003a44a4bc074b66a940f054b188acD39a18967865057e9ac1".lower()


def main():
    archive_bytes = ARCHIVE.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("Preview digest v1 exact-baseline fixture hash mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-preview-digest-v1-") as temporary:
        target = Path(temporary)
        base = target.resolve()
        with zipfile.ZipFile(ARCHIVE) as source:
            for member in source.infolist():
                destination = (target / member.filename).resolve()
                if not destination.is_relative_to(base):
                    raise RuntimeError("Unsafe path in Preview digest v1 fixture")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read(member))
        print("INTEGRITY OVERLAY: Preview digest v1 exact 3a63ac tree", flush=True)
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest",
             "test_preview_digest_contract_integrity_v1", "-v"],
            cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
