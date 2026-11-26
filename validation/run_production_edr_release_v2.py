"""Run immutable Production EDR V1 and the current V2 permission candidate."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
MANIFEST = ROOT / "validation/production_edr_integration_v2.json"
MANIFEST_SHA256 = "b45850370f4d51dfe2a6c20a3bc303b349b73e8eba080fcda308513ea23371ea"
V1_MANIFEST_SHA256 = "0a8711b9ad178be88195865b225d2c86c07772e7c90702f84c8e25d4c51c49a2"
V1_COMMIT = "192e07f5c4e9a439feac63ff993385ff7a43c407"
V1_TREE = "e2223939eaa4bfcdf8f1a0c14181367cbce28aaf"
EXCLUDED = {".git", ".playwright-tmp", "data", "backups", "logs", "evidence", "output", "__pycache__"}
V1_TESTS_TO_HIDE = {
    "test_production_edr_apply_permissions_v2.py",
    "test_production_edr_integration_integrity_v2.py",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in {".py", ".js", ".cjs", ".css", ".html", ".json", ".md", ".txt", ".yaml", ".yml"}:
        raw = raw.replace(b"\r\n", b"\n")
    return sha256(raw)


def read_manifest() -> dict:
    raw = MANIFEST.read_bytes()
    if sha256(raw) != MANIFEST_SHA256:
        raise AssertionError("Production EDR V2 manifest digest mismatch")
    payload = json.loads(raw)
    if payload.get("contract_id") != "pqm_production_edr_integration_v2":
        raise AssertionError("Unexpected Production EDR V2 contract")
    if payload.get("v1_candidate_commit") != V1_COMMIT or payload.get("v1_candidate_tree") != V1_TREE:
        raise AssertionError("V1 candidate identity mismatch")
    if payload.get("v1_manifest_sha256") != V1_MANIFEST_SHA256:
        raise AssertionError("Historical V1 manifest pin mismatch")
    for section in ("candidate_paths", "protected_paths"):
        pins = payload.get(section)
        if not isinstance(pins, dict) or not pins:
            raise AssertionError("Missing V2 integrity pins: " + section)
        for relative, expected in pins.items():
            path = ROOT / relative
            if not path.is_file() or file_sha256(path) != expected:
                raise AssertionError(f"Production EDR V2 {section} mismatch: {relative}")
    return payload


def copy_tree(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in EXCLUDED or name.startswith(".pqm-")}
    shutil.copytree(source, destination, ignore=ignore)


def restore_v1_snapshot(manifest: dict, destination: Path) -> Path:
    archive_path = ROOT / manifest["v1_candidate_archive"]
    archive_raw = archive_path.read_bytes()
    if sha256(archive_raw) != manifest["v1_candidate_archive_sha256"]:
        raise AssertionError("V1 candidate snapshot archive digest mismatch")
    v1_manifest_path = ROOT / "validation/production_edr_integration_v1.json"
    v1_payload = json.loads(v1_manifest_path.read_bytes())
    expected_files = set(v1_payload["candidate_paths"])
    with zipfile.ZipFile(archive_path) as archive:
        names = {name for name in archive.namelist() if not name.endswith("/")}
        if names != expected_files:
            raise AssertionError("Unexpected V1 candidate snapshot members")
        files = {name: archive.read(name) for name in names}
    copy_tree(ROOT, destination)
    unchanged_tests_path = ROOT / manifest["v1_unchanged_tests_archive"]
    unchanged_tests_raw = unchanged_tests_path.read_bytes()
    if sha256(unchanged_tests_raw) != manifest["v1_unchanged_tests_archive_sha256"]:
        raise AssertionError("V1 unchanged-test fixture archive digest mismatch")
    with zipfile.ZipFile(unchanged_tests_path) as archive:
        expected_unchanged = set(manifest["v1_unchanged_test_paths"])
        if set(archive.namelist()) != expected_unchanged:
            raise AssertionError("Unexpected V1 unchanged-test fixture archive members")
        for relative in sorted(expected_unchanged):
            content = archive.read(relative)
            if file_sha256_bytes(relative, content) != manifest["v1_unchanged_test_sha256"][relative]:
                raise AssertionError("V1 unchanged-test fixture pin mismatch: " + relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    for relative, content in files.items():
        if file_sha256_bytes(relative, content) != v1_payload["candidate_paths"][relative]:
            raise AssertionError("V1 candidate snapshot pin mismatch: " + relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name in V1_TESTS_TO_HIDE:
        target = destination / "validation/local_release_20260911" / name
        if target.exists():
            target.rename(target.with_name("v2_only_" + name))
    return destination


def file_sha256_bytes(relative: str, raw: bytes) -> str:
    if Path(relative).suffix.lower() in {".py", ".js", ".cjs", ".css", ".html", ".json", ".md", ".txt", ".yaml", ".yml"}:
        raw = raw.replace(b"\r\n", b"\n")
    return sha256(raw)


def prepare_v2_candidate(destination: Path, v1_candidate_only_modules: list[str]) -> Path:
    copy_tree(ROOT, destination)
    modules = {*v1_candidate_only_modules, "test_production_edr_integration_integrity_v1.py"}
    for name in modules:
        old_test = destination / "validation/local_release_20260911" / name
        if not old_test.is_file():
            raise AssertionError("V1 candidate-only test missing: " + name)
        old_test.rename(old_test.with_name("v1_baseline_" + old_test.name))
    return destination


def run(label: str, cwd: Path, command: list[str], env: dict[str, str]) -> tuple[int, int]:
    print("\nPRODUCTION EDR V2:", label, flush=True)
    child_env = env.copy()
    for key in tuple(child_env):
        if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or re.fullmatch(r"GIT_CONFIG_(?:KEY|VALUE)_\d+", key):
            child_env.pop(key, None)
    child_env.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(command, cwd=cwd, env=child_env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        output.append(line)
    code = process.wait()
    combined = "".join(output)
    match = re.search(r"Ran (\d+) tests? in", combined)
    count = int(match.group(1)) if match else 0
    summary = next((line.strip() for line in reversed(combined.splitlines())
                    if line.startswith(("OK", "FAILED ("))), "no unittest summary")
    print(f"PRODUCTION EDR V2 RESULT: {label}: exit={code}, tests={count}, {summary}", flush=True)
    return code, count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-only", action="store_true",
                        help="re-run the V2 candidate after V1 history already passed")
    args = parser.parse_args(argv)
    manifest = read_manifest()
    with tempfile.TemporaryDirectory(prefix="pqm-production-edr-v2-") as temporary:
        temp = Path(temporary)
        v1 = restore_v1_snapshot(manifest, temp / "v1-candidate")
        base_env = os.environ.copy()
        base_env.update(PQM_ENV="local", PQM_SANDBOX="0", PQM_ENABLE_GOOGLE="0",
                        PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_NAZK_WORKFLOW="0",
                        PQM_TEST_NETWORK_ISOLATION="1", PYTHONUTF8="1")
        if not args.candidate_only:
            v1_code, v1_tests = run("immutable V1 candidate and history", v1,
                                   [sys.executable, "-B", "validation/run_production_edr_release_v1.py"], base_env)
            if v1_code:
                return v1_code

        v1_runner_path = v1 / "validation/run_production_edr_release_v1.py"
        spec = importlib.util.spec_from_file_location("pqm_v1_integrity_runner", v1_runner_path)
        if spec is None or spec.loader is None:
            raise AssertionError("Cannot load immutable V1 integrity runner")
        v1_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(v1_runner)
        v1_manifest = v1_runner.manifest_payload()
        production_baseline = v1_runner.reconstruct_baseline(v1, temp / "production-baseline", v1_manifest)

        v2 = prepare_v2_candidate(temp / "v2-candidate", manifest["v1_candidate_only_modules"])
        v2_env = base_env.copy()
        # The legacy positive route fixture predates the independent V2 gate.
        # It is explicitly granted here; the V2 default-off and denial tests
        # clear/override this variable independently.
        v2_env.update(PQM_PRODUCTION_DOCUMENTS_SOURCE_ROOT=str(v2),
                      PQM_PRODUCTION_EDR_SOURCE_ROOT=str(v2),
                      PQM_PRODUCTION_EDR_BASELINE_ROOT=str(production_baseline),
                      # Existing positive EDR fixtures exercise the sync path;
                      # V2's independent default-off and denial behavior is covered
                      # by the explicit permission matrix tests.
                      PQM_PRODUCTION_EDR_SYNC_ENABLED="1",
                      PQM_PRODUCTION_EDR_APPLY_ENABLED="1",
                      PQM_DATA_DIR=str(temp / "v2-data"),
                      PQM_DB_PATH=str(temp / "v2-data" / "synthetic.sqlite3"))
        v2_code, v2_tests = run("current V2 candidate full local Production suite", v2,
                               [sys.executable, "-B", "validation/run_local_release.py"], v2_env)
        if v2_code:
            return v2_code
        v1_label = "already passed V1 history" if args.candidate_only else f"immutable V1={v1_tests}"
        print(f"\nPRODUCTION EDR INTEGRATION V2 RELEASE GATE: PASS — {v1_label}, V2 candidate={v2_tests}; schema/migration sources match V1; live DB/Google writes=0", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
