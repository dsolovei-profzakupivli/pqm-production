"""Build byte-pinned minimal source snapshots for immutable Writer overlays.

This is a maintainer utility, not part of the product runtime. It reads Git
objects only and emits the fixture ZIP plus its SHA-256 ledger.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import zipfile


SNAPSHOTS = {
    "admin_close_v1": ("5c08d5037873500204dec68045793efcc6d93b51", "test_google_writer_admin_close_integrity_v1.py"),
    "manifest_compatibility_v2": ("2f13f2b7ab2419a4f8376ac4590a94c94bbdd8f7", "test_google_writer_manifest_compatibility_integrity_v2.py"),
    "legacy_snapshot_execution_v2": ("2f13f2b7ab2419a4f8376ac4590a94c94bbdd8f7", "test_google_writer_legacy_source_snapshots_history_v2.py"),
    "preview_formula_v1": ("5c08d5037873500204dec68045793efcc6d93b51", "test_google_writer_preview_formula_integrity_v1.py"),
    "prewrite_stage_v1": ("a39f1ac60db807d441d085241ccace1c529454cc", "test_google_writer_prewrite_stage_integrity_v1.py"),
    "legacy_reconciliation_evidence_v2": ("9037e57728c09fe8aaea02d44b994da860944283", "test_legacy_reconciliation_evidence_v2_integrity.py"),
    "prewrite_diagnostics_v2": ("6696a2d0b7425a2bd69c47641539a05072d47dbb", "test_google_writer_prewrite_diagnostics_integrity_v2.py"),
    "prewrite_readonly_v1": ("1b142282e1c5170c9a8a918d085f82491fd1e58b", "test_google_writer_prewrite_readonly_integrity_v1.py"),
    "execution_envelope_v1": ("c9bc1fef7ccf2adae0185f87ba18cfd2ef42f897", "test_sandbox_execution_envelope_limit_v1.py"),
    "prewrite_egress_v1": ("b4f35fc3c55ad2919dd1c08925fa2cfd13acd657", "test_sandbox_execution_prewrite_egress_integrity_v1.py"),
    "append_continuation_v1": ("85dc98bf5d0870266b2d895ad1a5e8be957dfcaa", "test_google_writer_append_continuation_integrity_v1.py"),
}
OUTPUT_ZIP = "validation/fixtures/google_writer_historical_integrity_snapshots_v1_compact.zip"
OUTPUT_LEDGER = "validation/google_writer_historical_integrity_snapshots_v1.json"
EXTRA_PATHS = {
    "admin_close_v1": ("test_google_writer_admin_close.py", "scripts/pqm-google-writer/mirror-alignment/admin-close-unknown.test.cjs", "validation/legacy_snapshots/google_writer_ui_admin_close_v1.js"),
    "manifest_compatibility_v2": ("test_google_writer_all_scope_recovery.py", "test_google_writer_durable_append_recovery.py"),
    "legacy_snapshot_execution_v2": ("validation/run_google_writer_legacy_source_snapshots_v1_history.py", "test_google_writer_legacy_source_snapshots_integrity_v1.py"),
    "preview_formula_v1": ("scripts/pqm-google-writer/mirror-alignment/preview-formula-display.test.cjs",),
    "prewrite_stage_v1": ("test_google_writer_prewrite_stage_contract.py", "scripts/pqm-google-writer/mirror-alignment/sandbox/prewrite-stage-contract.test.cjs"),
    "legacy_reconciliation_evidence_v2": ("scripts/pqm-google-writer/mirror-alignment/sandbox/legacy-reconciliation-evidence-v2.test.cjs",),
    "prewrite_diagnostics_v2": (),
    "prewrite_readonly_v1": (),
    "execution_envelope_v1": ("test_sandbox_execution_transport.py", "scripts/pqm-google-writer/sandbox-full-apply.test.cjs"),
    "prewrite_egress_v1": ("test_sandbox_execution_transport.py",),
    "append_continuation_v1": ("test_google_writer_append_continuation.py", "test_google_writer_execution.py", "scripts/pqm-google-writer/sandbox-full-apply.test.cjs"),
}


def tree_map(commit: str) -> dict[str, str]:
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--full-tree", commit])
    result = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        if kind == "blob":
            result[path.decode("utf-8")] = oid
    return result


def load_blobs(tree: dict[str, str], paths: set[str], cache: dict[str, bytes]) -> None:
    missing = sorted(path for path in paths if path in tree and path not in cache)
    if not missing:
        return
    request = b"".join((tree[path] + "\n").encode("ascii") for path in missing)
    output = subprocess.check_output(["git", "cat-file", "--batch"], input=request)
    cursor = 0
    for path in missing:
        header_end = output.index(b"\n", cursor)
        oid, kind, size = output[cursor:header_end].decode("ascii").split()
        if kind != "blob":
            raise RuntimeError(f"Snapshot input is not a blob: {path}")
        cursor = header_end + 1
        length = int(size)
        cache[path] = output[cursor:cursor + length]
        cursor += length + 1  # cat-file's record separator newline


def discover_paths(snapshot_id: str, commit: str, test_path: str) -> tuple[set[str], dict[str, bytes]]:
    tree = tree_map(commit)
    paths = {test_path}
    cache: dict[str, bytes] = {}
    load_blobs(tree, paths, cache)
    if test_path not in cache:
        raise FileNotFoundError(f"Pinned test missing at {commit}: {test_path}")
    test_tree = ast.parse(cache[test_path])
    paths.update(EXTRA_PATHS[snapshot_id])
    primary_manifests = set()
    if snapshot_id == "legacy_snapshot_execution_v2":
        historical_manifest = "validation/local_release_20261109/google_writer_legacy_source_snapshots_v1.json"
        paths.add(historical_manifest)
        primary_manifests.add(historical_manifest)
    for node in test_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        manifest_names = {name for name in names if name == "MANIFEST" or name.endswith("_MANIFEST")}
        if manifest_names and isinstance(node.value, ast.Call) and node.value.args:
            try:
                primary_manifest = ast.literal_eval(node.value.args[0])
                paths.add(primary_manifest)
                primary_manifests.add(primary_manifest)
            except (ValueError, TypeError):
                pass
        if names.intersection({"MANIFEST", "PRESERVED_SHA256", "PRESERVED_PINNED", "SOURCE_SHA256", "EXPECTED_SHA256"}):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if isinstance(value, str):
                paths.add(value)
            elif isinstance(value, dict):
                paths.update(key for key in value if isinstance(key, str))

    # Follow historical manifest declarations until no new files are found.
    examined = set()
    while True:
        load_blobs(tree, paths, cache)
        new_paths = set()
        for path in (paths - examined) & primary_manifests:
            examined.add(path)
            if path not in cache or not path.endswith(".json"):
                continue
            try:
                manifest = json.loads(cache[path])
            except json.JSONDecodeError:
                continue
            for field in ("files", "scope", "preserved_manifests"):
                value = manifest.get(field, [])
                new_paths.update(value if isinstance(value, list) else value.keys())
        new_paths.intersection_update(tree)
        if new_paths.issubset(paths):
            break
        paths.update(new_paths)
    return paths.intersection(tree), cache


def main() -> None:
    archive_rows = {}
    with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for snapshot_id, (commit, test_path) in SNAPSHOTS.items():
            rows = {}
            included, cache = discover_paths(snapshot_id, commit, test_path)
            for relative in sorted(included):
                data = cache[relative]
                archive_path = f"snapshots/{snapshot_id}/{relative}"
                info = zipfile.ZipInfo(archive_path, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
                rows[relative] = hashlib.sha256(data).hexdigest()
            archive_rows[snapshot_id] = {"commit": commit, "test": test_path, "files": rows}

    archive_bytes = open(OUTPUT_ZIP, "rb").read()
    ledger = {
        "contract": "pqm-google-writer-historical-integrity-snapshots",
        "version": 1,
        "archive": OUTPUT_ZIP,
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "snapshots": archive_rows,
    }
    with open(OUTPUT_LEDGER, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(ledger, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"snapshots={len(archive_rows)} archive_bytes={len(archive_bytes)} archive_sha256={ledger['archive_sha256']}")
    for name, snapshot in archive_rows.items():
        print(f"{name}: files={len(snapshot['files'])} commit={snapshot['commit']}")


if __name__ == "__main__":
    main()
