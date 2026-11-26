"""Run immutable Production history and the current EDR candidate separately."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "validation/production_edr_integration_v1.json"
MANIFEST_SHA256 = "0a8711b9ad178be88195865b225d2c86c07772e7c90702f84c8e25d4c51c49a2"
HISTORICAL_ONLY_MODULES = {
    "test_production_documents_integrity.py",
    "test_production_edr_display_toasts_integrity.py",
    "test_production_edr_google_nazk_daily_sync_integrity_v2.py",
    "test_production_edr_google_nazk_integrity.py",
}
HISTORICAL_MODULES = [
    "test_production_documents_integrity.py",
    "test_production_edr_display_toasts_integrity.py",
    "test_production_edr_google_nazk_daily_sync_integrity_v2.py",
    "test_production_edr_google_nazk_integrity.py",
    "test_production_memory_integrity.py",
    "test_production_experience_integrity.py",
    "test_production_integrity_routes.py",
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in {".py", ".js", ".cjs", ".css", ".html", ".json", ".md", ".txt", ".yaml", ".yml"}:
        raw = raw.replace(b"\r\n", b"\n")
    return sha256(raw)


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def manifest_payload() -> dict:
    raw = MANIFEST.read_bytes()
    if sha256(raw) != MANIFEST_SHA256:
        raise AssertionError("Production EDR V1 manifest digest mismatch")
    payload = json.loads(raw)
    if payload.get("contract_id") != "pqm_production_edr_integration_v1":
        raise AssertionError("Unexpected Production EDR integrity contract")
    candidate = payload.get("candidate_paths")
    if not isinstance(candidate, dict) or not candidate:
        raise AssertionError("Production EDR candidate pins are missing")
    for name, expected in candidate.items():
        path = ROOT / name
        if not path.is_file() or file_sha256(path) != expected:
            raise AssertionError("Production EDR candidate file mismatch: " + name)
    protected = payload.get("protected_paths")
    if not isinstance(protected, dict) or not protected:
        raise AssertionError("Historical Production contract pins are missing")
    for name, expected in protected.items():
        path = ROOT / name
        if not path.is_file() or file_sha256(path) != expected:
            raise AssertionError("Historical Production contract changed: " + name)
    if payload.get("historical_modules") != HISTORICAL_MODULES:
        raise AssertionError("Unexpected historical Production test routing")
    return payload


def reconstruct_baseline(source: Path, destination: Path, manifest: dict) -> Path:
    archive_path = source / manifest["baseline_override_archive"]
    archive_raw = archive_path.read_bytes()
    if sha256(archive_raw) != manifest["baseline_override_archive_sha256"]:
        raise AssertionError("Production EDR baseline archive digest mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        index_raw = archive.read("INDEX.json")
        if sha256(index_raw) != manifest["baseline_index_sha256"]:
            raise AssertionError("Production EDR baseline index digest mismatch")
        index = json.loads(index_raw)
        if (index.get("base_commit") != manifest["baseline_commit"]
                or index.get("base_tree") != manifest["baseline_tree"]
                or len(index.get("files", {})) != manifest["baseline_file_count"]):
            raise AssertionError("Production EDR baseline identity mismatch")
        override_paths = index.get("overrides", [])
        expected_members = {"INDEX.json", *["files/" + name for name in override_paths]}
        if set(archive.namelist()) != expected_members:
            raise AssertionError("Unexpected Production EDR baseline archive members")
        if set(override_paths) != set(manifest["override_paths"]):
            raise AssertionError("Unexpected Production EDR baseline override set")
        overrides = {name: archive.read("files/" + name) for name in override_paths}

    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for name, metadata in index["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError("Unsafe path in Production EDR baseline index")
        if name in overrides:
            content = overrides[name]
        else:
            current_path = source / relative
            if not current_path.is_file():
                raise AssertionError("Baseline source file unavailable: " + name)
            content = current_path.read_bytes()
            if git_blob(content) != metadata["oid"]:
                normalized = content.replace(b"\r\n", b"\n")
                if git_blob(normalized) != metadata["oid"]:
                    raise AssertionError("Unchanged baseline blob mismatch: " + name)
                content = normalized
        if git_blob(content) != metadata["oid"]:
            raise AssertionError("Baseline Git blob mismatch: " + name)
        target = destination / relative
        target.resolve().relative_to(destination.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if metadata.get("mode") == "100755":
            target.chmod(0o755)
    return destination


def prepare_candidate_copy(source: Path, destination: Path) -> Path:
    excluded = {".git", ".playwright-tmp", "data", "backups", "logs", "evidence", "output", "__pycache__"}
    destination.mkdir(parents=True)
    for item in source.iterdir():
        if item.name in excluded or item.name.startswith(".pqm-"):
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif item.is_file():
            shutil.copy2(item, target)

    package = destination / "validation/local_release_20260911"
    for name in HISTORICAL_ONLY_MODULES:
        module = package / name
        if not module.is_file():
            raise AssertionError("Required historical contract missing: " + name)
        module.rename(module.with_name("baseline_" + name))
    return destination


def execute(label: str, cwd: Path, command: list[str], env: dict[str, str]) -> tuple[int, int, str]:
    print("\nPRODUCTION EDR V1:", label, flush=True)
    child_env = env.copy()
    # Codex/IDE hosts can inject a Git config tuple for their own operations.
    # Keep that process-local override out of test subprocesses; never touch
    # user/system Git configuration.
    for key in tuple(child_env):
        if (key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
                or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", key)):
            child_env.pop(key, None)
    child_env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(command, cwd=cwd, env=child_env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    output = []
    assert process.stdout is not None
    for line in process.stdout:
        output.append(line)
        print(line, end="", flush=True)
    returncode = process.wait()
    full_output = "".join(output)
    match = re.search(r"Ran (\d+) tests? in", full_output)
    count = int(match.group(1)) if match else 0
    if returncode:
        print("\nPRODUCTION EDR V1 FAILURE SUMMARY:", label, flush=True)
        lines = full_output.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(("FAIL: ", "ERROR: ")):
                detail = next((value.strip() for value in reversed(lines[index + 1:min(index + 30, len(lines))])
                               if value.strip().startswith(("AssertionError:", "ImportError:", "ModuleNotFoundError:", "sqlite3.", "OSError:", "TypeError:", "ValueError:"))), "")
                print(line + (" — " + detail if detail else ""), flush=True)
        summary = next((line for line in reversed(lines) if line.startswith(("FAILED (", "OK"))), "no unittest summary")
        print(summary, flush=True)
    return returncode, count, full_output


def main() -> int:
    manifest = manifest_payload()
    with tempfile.TemporaryDirectory(prefix="pqm-production-edr-v1-") as temp:
        temp_root = Path(temp)
        baseline = reconstruct_baseline(ROOT, temp_root / "baseline", manifest)
        base_env = os.environ.copy()
        base_env.update(PQM_ENV="local", PQM_SANDBOX="0", PQM_ENABLE_GOOGLE="0",
                        PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_NAZK_WORKFLOW="0",
                        PQM_TEST_NETWORK_ISOLATION="1",
                        PYTHONUTF8="1",
                        PQM_PRODUCTION_DOCUMENTS_SOURCE_ROOT=str(baseline),
                        PQM_DATA_DIR=str(temp_root / "baseline-data"),
                        PQM_DB_PATH=str(temp_root / "baseline-data" / "synthetic.sqlite3"))
        base_count = 0
        for pattern in HISTORICAL_MODULES:
            base_rc, count, _ = execute(
                "immutable Production baseline contract " + pattern, baseline,
                [sys.executable, "-B", "validation/run_local_release.py", pattern], base_env)
            base_count += count
            if base_rc:
                return base_rc
        print("\nPRODUCTION EDR V1: baseline contracts passed at " + manifest["baseline_commit"], flush=True)
        history_rc, history_count, _ = execute(
            "immutable Production document/history contracts", baseline,
            [sys.executable, "-B", "validation/run_production_documents.py", "--history"], base_env)
        if history_rc:
            return history_rc

        candidate_root = temp_root / "candidate"
        prepare_candidate_copy(ROOT, candidate_root)
        candidate_env = os.environ.copy()
        candidate_env.update(PQM_ENV="local", PQM_SANDBOX="0", PQM_ENABLE_GOOGLE="0",
                             PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_NAZK_WORKFLOW="0",
                             PQM_TEST_NETWORK_ISOLATION="1",
                             PYTHONUTF8="1",
                             PQM_PRODUCTION_DOCUMENTS_SOURCE_ROOT=str(candidate_root),
                             PQM_PRODUCTION_EDR_BASELINE_ROOT=str(baseline),
                             PQM_DATA_DIR=str(temp_root / "candidate-data"),
                             PQM_DB_PATH=str(temp_root / "candidate-data" / "synthetic.sqlite3"))
        candidate_rc, candidate_count, _ = execute(
            "current Production candidate with historical assertions routed to immutable baseline",
            candidate_root,
            [sys.executable, "-B", "validation/run_local_release.py"], candidate_env)
        if candidate_rc:
            return candidate_rc
        print(f"\nPRODUCTION EDR V1 RELEASE GATE: PASS — baseline={base_count} candidate={candidate_count} history={history_count}; no historical assertions removed", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
