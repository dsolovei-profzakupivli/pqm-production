"""Run the immutable second-reconciliation v1 source pins on their 0347404 snapshot."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "validation/fixtures/partial_reconciliation_second_run_v1_exact_0347404.zip"
FIXTURE_SHA256 = "1b570a5b166ff20b28e174dc78cf61ce2d0e4400787469449d55fcfc529cb178"
MANIFEST = "validation/local_release_20260911/partial_reconciliation_second_run_v1.json"


def main():
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Second partial reconciliation exact-source fixture hash mismatch")
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    expected = (set(manifest["expected_file_scope"]) | set(manifest["preserved_sources"])
                | set(manifest["preserved_manifests"]) | {MANIFEST})
    with tempfile.TemporaryDirectory(prefix="pqm-partial-reconcile-v1-history-") as temporary:
        target = Path(temporary).resolve()
        with zipfile.ZipFile(FIXTURE) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != expected:
                raise SystemExit("Unexpected second partial reconciliation fixture members")
            for relative in sorted(members):
                output = (target / relative).resolve()
                if not output.is_relative_to(target):
                    raise SystemExit("Unsafe path in second partial reconciliation fixture")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(relative))
        print("INTEGRITY OVERLAY: partial reconciliation v1 exact 0347404 source tree", flush=True)
        env = os.environ.copy()
        env["PQM_RELEASE_SOURCE_ROOT"] = str(target)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "test_partial_reconciliation_second_integrity_v1", "-v"],
            cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
