"""Run superseded exact-tree contracts on their original candidate trees."""
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
OVERLAYS = (
    ("edr_preview_skipped_v1", "validation/fixtures/edr_preview_skipped_v1_6b9830b.zip",
     "6188d492d9f95fb9d23f11a7660c8188fef4c210b610dbc20f0356e603540726",
     ("validation.local_release_20260911.test_edr_preview_skipped_integrity",
      "validation.local_release_20260911.test_edr_preview_skipped_rows"), ()),
    ("google_writer_supplier_types_v1", "validation/fixtures/google_writer_supplier_types_v1_97788.zip",
     "95919f57f4df9e141fb1e4cb7461d2a26d506e64034b5e608fc6620f13b3c061",
     ("test_google_writer_supplier_types_integrity",), (
         ("validation/fixtures/integrated_classification_v1_overlay_6b9830b.zip",
          "2f671afe120e52b169bc354ee568a9af19c32772b105061835f40fb1146b5166"),
         ("validation/fixtures/integrated_writer_v1_overlay_64f7fda.zip",
          "6507d95a38b96fbe0b2bac4d5c061f85c47ef52c5ed0ad109c5a875d52ac78b7"),
         ("validation/fixtures/supplier_classification_parent_integrity_6b9830b.zip",
          "8fc44d8ddcb9c0fd3e5f9a3b4999c89f4b4fdc0a498fa05144dbadf5176aad71"),
     )),
    ("date_only_v1_97788", "validation/fixtures/google_edr_date_only_midnight_v1_97788.zip",
     "fb6ac2224de07ac0a2a71feb727c3d03e1900a6eed7aaad82d7577cc77d9b8b7",
     ("test_google_edr_date_only_midnight_integrity_v1",), ()),
    ("edr_status_v1_15b8", "validation/fixtures/edr_status_evidence_v1_15b8.zip",
     "772a73e079027a2c45024bc61bac20f5a178ffd962f953372dbbfb80f4b0aec0",
     ("validation.local_release_20260911.test_edr_status_evidence_integrity_v1",), ()),
    ("date_only_status_integrated_v1_12329",
     "validation/fixtures/date_only_edr_status_integrated_v1_12329.zip",
     "05d2359d57155097d3f87e0fb26fdd222fc9aa2e808250ac6f03a1da1e3d12a8",
     ("test_date_only_edr_status_integrated_integrity_v1",), ()),
)


def extract_checked(archive_path, destination):
    base = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(base):
                raise RuntimeError("Unsafe path in date-only historical overlay")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))


def add_checked_shared_fixtures(repo, target, fixtures):
    for relative, expected in fixtures:
        source = repo / relative
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError(f"Shared historical fixture SHA-256 mismatch: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    with tempfile.TemporaryDirectory(prefix="pqm-date-only-history-") as temporary:
        for name, relative, expected_sha, modules, shared_fixtures in OVERLAYS:
            archive = ROOT / relative
            raw = archive.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                raise RuntimeError(f"{name} baseline overlay SHA-256 mismatch")
            target = Path(temporary) / name
            target.mkdir()
            extract_checked(archive, target)
            add_checked_shared_fixtures(ROOT, target, shared_fixtures)
            manifest_relative = {
                "date_only_v1_97788": "google_edr_date_only_midnight_v1.json",
                "edr_status_v1_15b8": "validation/local_release_20260911/edr_status_evidence_v1.json",
                "date_only_status_integrated_v1_12329": "date_only_edr_status_integrated_v1.json",
            }.get(name)
            if manifest_relative:
                manifest = json.loads((target / manifest_relative).read_text(encoding="utf-8"))
                for path, digest in manifest["files"].items():
                    destination = target / path
                    if destination.exists() or not path.lower().endswith(".zip"):
                        continue
                    source = ROOT / path
                    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                        raise RuntimeError(f"{name} omitted fixture is absent or has changed: {path}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            print(f"INTEGRITY OVERLAY: {name} exact source tree", flush=True)
            for module in modules:
                result = subprocess.run([sys.executable, "-B", "-m", "unittest", module, "-v"],
                                        cwd=target, env=os.environ.copy(), check=False)
                if result.returncode:
                    return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
