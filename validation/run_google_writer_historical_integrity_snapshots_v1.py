"""Run immutable Google Writer integrity overlays against exact source snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "validation/google_writer_historical_integrity_snapshots_v1.json"


def fail(message: str) -> int:
    print(f"HISTORICAL SNAPSHOTS: FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if not LEDGER.is_file():
        return fail("snapshot ledger missing; refusing candidate-source fallback")
    try:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"snapshot ledger unreadable ({type(exc).__name__})")
    if ledger.get("contract") != "pqm-google-writer-historical-integrity-snapshots" or ledger.get("version") != 1:
        return fail("unsupported snapshot ledger contract")
    archive_path = ROOT / ledger.get("archive", "")
    if not archive_path.is_file():
        return fail("snapshot archive missing; refusing candidate-source fallback")
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != ledger.get("archive_sha256"):
        return fail("snapshot archive SHA-256 mismatch")

    with tempfile.TemporaryDirectory(prefix="pqm-writer-history-") as tmp:
        temp_root = Path(tmp).resolve()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                for name in names:
                    target = (temp_root / name).resolve()
                    if not target.is_relative_to(temp_root):
                        return fail("unsafe path in snapshot archive")
                for snapshot_id, snapshot in ledger.get("snapshots", {}).items():
                    prefix = f"snapshots/{snapshot_id}/"
                    declared = snapshot.get("files", {})
                    archived = {name[len(prefix):] for name in names if name.startswith(prefix)}
                    if archived != set(declared):
                        return fail(f"{snapshot_id}: snapshot file inventory mismatch")
                    snapshot_root = temp_root / "snapshots" / snapshot_id
                    for relative, expected in declared.items():
                        data = archive.read(prefix + relative)
                        if hashlib.sha256(data).hexdigest() != expected:
                            return fail(f"{snapshot_id}: pinned file hash mismatch: {relative}")
                        destination = snapshot_root / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            return fail(f"snapshot extraction failed ({type(exc).__name__})")

        failures = []
        for snapshot_id, snapshot in ledger["snapshots"].items():
            snapshot_root = temp_root / "snapshots" / snapshot_id
            module = Path(snapshot["test"]).stem
            if not (snapshot_root / snapshot["test"]).is_file():
                failures.append(f"{snapshot_id}: pinned test missing")
                continue
            env = os.environ.copy()
            env["PQM_RELEASE_SOURCE_ROOT"] = str(snapshot_root)
            env["PQM_RELEASE_MODE"] = "historical_integrity"
            print(f"HISTORICAL SNAPSHOT: {snapshot_id} @ {snapshot['commit']}", flush=True)
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", "-v", module],
                                    cwd=snapshot_root, env=env, check=False)
            if result.returncode:
                failures.append(f"{snapshot_id}: unittest exit {result.returncode}")
        if failures:
            return fail("; ".join(failures))
    print(f"HISTORICAL SNAPSHOTS: PASS ({len(ledger['snapshots'])} immutable snapshots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
