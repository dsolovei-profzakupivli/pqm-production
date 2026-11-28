"""Run additive Messages/NAZK tests on the exact historical Git snapshot.

The default entrypoint also preserves the existing Messages v1 overlay. The
``--history-only`` mode is called by the V31.1 bridge and checks the original
86ea864 tree without overlaying selected old files onto the current candidate.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
import unittest
import zipfile
from pathlib import PurePosixPath

RUNNER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_ROOT))
import run_messages_integrated_v1_history as history
from validation.v31_1 import bridge


ORIGINAL_PARENT_SHA256 = "2fc0787617767048d92870559d4654dd989e356a898ef58c06015453ebaf71ad"
WORKFLOW = ".github/workflows/release-checks.yml"
BASELINE_WORKFLOW = "validation/fixtures/release_checks_baseline_0347404.yml"
HISTORY_COMMIT = "86ea864399869e77a4b1f841098e01e04c5a5e74"
HISTORY_TREE = "fe9e2000919923a6442f75da422a5217a17325c8"
HISTORY_TESTS = (
    "test_sandbox_messages_integrity",
    "test_sandbox_nazk_messages_integrated_integrity",
    "validation.local_release_20260911.test_nazk_authority_request_integrity",
    "test_messages_historical_line_endings",
)
HISTORY_TEST_COUNT = 21
CURRENT_CANDIDATE_TEST = (
    "validation.local_release_20260911.test_nazk_authority_request_integrity."
    "NazkAuthorityRequestIntegrityTests.test_generation_route_uses_tasks_manage_and_direction_is_separate"
)


def _git(repo, *args):
    return bridge._git(repo, *args).strip()


def verify_history_identity(repo, commit=HISTORY_COMMIT):
    """Fail closed unless the approved commit and tree are both available."""
    if commit != HISTORY_COMMIT:
        raise RuntimeError("Unapproved Messages/NAZK historical commit")
    resolved = _git(repo, "rev-parse", "--verify", commit + "^{commit}")
    tree = _git(repo, "rev-parse", "--verify", resolved + "^{tree}")
    if resolved != HISTORY_COMMIT or tree != HISTORY_TREE:
        raise RuntimeError("Messages/NAZK historical Git identity mismatch")
    return resolved, tree


def _safe_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or "\\" in name or not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise RuntimeError("Unsafe historical Git archive path")
    return path


def verify_exported_blob(name, oid, raw, exported):
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if actual != oid.decode("ascii"):
        raise RuntimeError("Historical Git blob mismatch: " + name)
    if exported != raw and not (b"\r\n" not in raw and raw.replace(b"\n", b"\r\n") == exported):
        raise RuntimeError("Unexpected Git archive content transformation: " + name)


def extract_history_snapshot(repo, target, commit=HISTORY_COMMIT):
    """Materialize exact pinned Git blobs without requiring Git at runtime."""
    if commit != HISTORY_COMMIT:
        raise RuntimeError("Unapproved Messages/NAZK historical commit")
    repo, target = Path(repo).resolve(), Path(target).resolve()
    if repo == target or repo in target.parents or target in repo.parents:
        raise RuntimeError("Historical snapshot destination overlaps its source")
    target.mkdir(parents=True, exist_ok=False)
    manifest = bridge.validate_addendum(repo)
    snapshot = manifest["history_snapshot"]
    if snapshot["commit"] != HISTORY_COMMIT or snapshot["tree"] != HISTORY_TREE:
        raise RuntimeError("Messages/NAZK package does not match the approved historical snapshot")
    archive_bytes = base64.b64decode(snapshot["delta_zip_base64"], validate=True)
    if hashlib.sha256(archive_bytes).hexdigest() != snapshot["delta_zip_sha256"]:
        raise RuntimeError("Pinned Messages/NAZK delta archive SHA-256 mismatch")
    records = snapshot["files"]
    if (repo / ".git").exists():
        verify_history_identity(repo, commit)
        raw_listing = subprocess.check_output(
            ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", commit],
            env=bridge._git_environment())
        actual = {}
        for entry in raw_listing.split(b"\x00"):
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, oid = header.split(b" ", 2)
            if kind != b"blob" or mode not in {b"100644", b"100755"}:
                raise RuntimeError("Unsupported object in pinned historical Git tree")
            actual[name.decode("utf-8", "strict")] = (mode.decode("ascii"), oid.decode("ascii"))
        expected = {name: (record["mode"], record["git_blob"]) for name, record in records.items()}
        if actual != expected:
            raise RuntimeError("Pinned historical package does not match the exact Git tree")
    extracted = set()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        infos = archive.infolist()
        delta_names = {name for name, record in records.items() if record["delivery"] == "delta"}
        if (len(infos) != len({item.filename for item in infos})
                or {item.filename for item in infos} != delta_names):
            raise RuntimeError("Pinned Messages/NAZK delta membership mismatch")
        delta = {item.filename: archive.read(item) for item in infos}
    for name, record in records.items():
        relative = _safe_member(name)
        if record["delivery"] == "delta":
            exported = delta[name]
            blob = exported.replace(b"\r\n", b"\n") if record["archive_eol"] == "crlf" else exported
        else:
            candidate = (repo / Path(*relative.parts)).read_bytes()
            candidates = (candidate, candidate.replace(b"\r\n", b"\n"))
            blob = next((candidate_blob for candidate_blob in candidates
                        if hashlib.sha1(b"blob " + str(len(candidate_blob)).encode("ascii") + b"\0" + candidate_blob)
                        .hexdigest() == record["git_blob"]), None)
            if blob is None:
                raise RuntimeError("Candidate-delivered historical blob mismatch: " + name)
            exported = (blob.replace(b"\n", b"\r\n")
                        if record["archive_eol"] == "crlf" and b"\r\n" not in blob else blob)
        verify_exported_blob(name, record["git_blob"].encode("ascii"), blob, exported)
        if (hashlib.sha256(blob).hexdigest() != record["blob_sha256"]
                or hashlib.sha256(exported).hexdigest() != record["sha256"]):
            raise RuntimeError("Pinned historical file SHA-256 mismatch: " + name)
        destination = (target / Path(*relative.parts)).resolve()
        if target not in destination.parents:
            raise RuntimeError("Historical snapshot destination escaped its root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(exported)
        if record["mode"] == "100755":
            destination.chmod(destination.stat().st_mode | 0o111)
        extracted.add(name)
    if len(extracted) != snapshot["file_count"] or extracted != set(records):
        raise RuntimeError("Pinned historical snapshot has incomplete membership")
    return len(extracted)


def _run(command, *, cwd, env, expected_count=None, label):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(label + " failed with exit code " + str(result.returncode) + "\n" + output[-12000:])
    if expected_count is not None:
        match = re.search(r"Ran (\d+) tests? in ", output)
        if not match or int(match.group(1)) != expected_count:
            raise RuntimeError(label + " ran an unexpected number of tests\n" + output[-12000:])
        if re.search(r"\bOK \(skipped=", output):
            raise RuntimeError(label + " skipped a required historical test")
    print(output, end="", flush=True)
    return output


def _isolated_temp_root(repo):
    configured = Path(os.environ.get("PQM_V311_TEMP_ROOT") or tempfile.gettempdir()).resolve()
    if configured == repo or repo in configured.parents or configured in repo.parents:
        # The bridge stages this runner below its own temporary root. Use a
        # sibling directory for the runner's historical extraction, preserving
        # the disjoint-source guard instead of weakening it.
        configured = repo.parent.parent / (repo.parent.name + "-messages-temp")
        configured = configured.resolve()
        configured.mkdir(parents=True, exist_ok=True)
    if configured == repo or repo in configured.parents or configured in repo.parents:
        raise RuntimeError("Messages/NAZK temporary root is missing or overlaps the source")
    if not configured.is_dir():
        raise RuntimeError("Messages/NAZK temporary root is missing")
    return configured


def run_current_candidate(repo):
    """Run the pinned current test from this delivered tree in its child env."""
    repo = Path(repo).resolve()
    executing_root = Path(__file__).resolve().parents[1]
    if repo != executing_root or Path(bridge.__file__).resolve() != repo / "validation/v31_1/bridge.py":
        raise RuntimeError("Messages/NAZK candidate runner is not executing from its delivered source tree")
    manifest = bridge.validate_addendum(repo)
    module_name, class_name, method_name = CURRENT_CANDIDATE_TEST.rsplit(".", 2)
    module_path = Path(*module_name.split(".")).with_suffix(".py")
    candidate_file = bridge.safe_source(repo, module_path.as_posix())
    expected = manifest["candidate_lf_sha256"].get(module_path.as_posix())
    if not expected:
        raise RuntimeError("Current V31.1 NAZK test lacks a staged content pin")
    verified_bytes = bridge.validate_lf_file(repo, module_path.as_posix(), expected)
    sys.path.insert(0, str(repo))
    spec = importlib.util.spec_from_file_location(module_name, candidate_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load current V31.1 NAZK test from delivered staging")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    exec(compile(verified_bytes, str(candidate_file), "exec"), module.__dict__)
    suite = unittest.defaultTestLoader.loadTestsFromName(
        class_name + "." + method_name, module=module)
    if suite.countTestCases() != 1:
        raise RuntimeError("Current V31.1 NAZK route regression is missing or duplicated")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError("Current V31.1 NAZK route regression failed")
    return 0


def run_history_matrix(repo):
    repo = Path(repo).resolve()
    executing_root = Path(__file__).resolve().parents[1]
    if repo != executing_root or Path(bridge.__file__).resolve() != repo / "validation/v31_1/bridge.py":
        raise RuntimeError("Messages/NAZK runner is not executing from its delivered source tree")
    manifest = bridge.validate_addendum(repo)
    if manifest.get("candidate_test") != CURRENT_CANDIDATE_TEST:
        raise RuntimeError("Current V31.1 NAZK test identity mismatch")
    # The source tree's own isolated temp root is used when configured by the bridge.
    temp_root = _isolated_temp_root(repo)
    with tempfile.TemporaryDirectory(prefix="pqm-v311-86ea-", dir=temp_root) as folder:
        snapshot = Path(folder) / "history"
        count = extract_history_snapshot(repo, snapshot)
        env = os.environ.copy()
        for key in tuple(env):
            if key.startswith("GIT_") or key in {"PQM_RELEASE_SOURCE_ROOT", "PQM_V311_SOURCE_ROOT", "PQM_V311_BASELINE"}:
                env.pop(key, None)
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PQM_ENV="test_web",
                   PQM_ENABLE_GOOGLE="0", PQM_DISABLE_BACKGROUND_JOBS="1",
                   PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_NAZK_SCHEDULER="0",
                   PQM_ENABLE_PROZORRO_SCHEDULER="0", PQM_ENABLE_VIOLATION_SCHEDULER="0")
        env["PYTHONPATH"] = str(snapshot) + os.pathsep + str(snapshot / "validation/local_release_20260911")
        _run([sys.executable, "-B", "-m", "unittest", "-v", *HISTORY_TESTS],
             cwd=snapshot, env=env, expected_count=HISTORY_TEST_COUNT,
             label="Messages/NAZK 86ea historical matrix")
        # This behavior is still required of the current V31.1 candidate; it is
        # run independently so historical PASS cannot stand in for current code.
        candidate = executing_root
        current_env = os.environ.copy()
        for key in tuple(current_env):
            if key.startswith("GIT_") or key in {"PQM_RELEASE_SOURCE_ROOT", "PQM_V311_SOURCE_ROOT", "PQM_V311_BASELINE"}:
                current_env.pop(key, None)
        current_env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PQM_ENV="test_web",
                           PQM_ENABLE_GOOGLE="0", PQM_DISABLE_BACKGROUND_JOBS="1",
                           PQM_ENABLE_SCHEDULER="0", PQM_ENABLE_NAZK_SCHEDULER="0",
                           PQM_ENABLE_PROZORRO_SCHEDULER="0", PQM_ENABLE_VIOLATION_SCHEDULER="0")
        current_env["PYTHONPATH"] = str(candidate) + os.pathsep + str(candidate / "validation/local_release_20260911")
        current_env["PQM_RELEASE_SOURCE_ROOT"] = str(candidate)
        # Re-enter this runner in the sanitized child process. It verifies the
        # actual staged bytes before compiling them, so environment isolation
        # and delivered-file identity are both preserved.
        _run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--candidate-only"],
             cwd=candidate, env=current_env, expected_count=1,
             label="Current V31.1 NAZK route regression")
        report = {"history_commit": HISTORY_COMMIT, "history_tree": HISTORY_TREE,
                  "snapshot_files": count, "historical_tests": HISTORY_TEST_COUNT,
                  "candidate_test": CURRENT_CANDIDATE_TEST, "status": "PASS"}
        evidence = Path(os.environ.get("PQM_V311_EVIDENCE") or candidate / "evidence")
        evidence.mkdir(parents=True, exist_ok=True)
        path = evidence / ("V311_messages_nazk_addendum_86ea864_" + uuid.uuid4().hex + ".json")
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Messages/NAZK additive history PASS:", json.dumps(report), flush=True)
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--candidate-only", action="store_true")
    args = parser.parse_args()
    # The runner's own delivered location is authoritative. PQM_V311_SOURCE_ROOT
    # identifies the parent checkout for staging and must not redirect a child
    # delegate away from the copy it is meant to verify.
    repo = Path(__file__).resolve().parents[1]
    if args.candidate_only:
        return run_current_candidate(repo)
    if args.history_only:
        return run_history_matrix(repo)
    parent = repo / history.PARENT_FIXTURE
    if hashlib.sha256(parent.read_bytes()).hexdigest() != ORIGINAL_PARENT_SHA256:
        raise SystemExit("Messages historical parent fixture SHA-256 mismatch")
    baseline_workflow = (repo / BASELINE_WORKFLOW).read_bytes()
    temp_root = Path(os.environ.get("PQM_V311_TEMP_ROOT") or os.environ.get("RUNNER_TEMP")
                     or tempfile.gettempdir()).resolve()
    if not temp_root.is_dir() or temp_root == repo or repo in temp_root.parents or temp_root in repo.parents:
        raise SystemExit("Messages historical overlay temporary root is missing or overlaps the source")
    with tempfile.TemporaryDirectory(prefix="pqm-messages-parent-addendum-", dir=temp_root) as temporary:
        patched_parent = Path(temporary) / "messages-parent-with-pinned-workflow.zip"
        with zipfile.ZipFile(parent) as source, zipfile.ZipFile(patched_parent, "w", zipfile.ZIP_DEFLATED) as target:
            if WORKFLOW not in source.namelist():
                raise SystemExit("Messages parent fixture lacks the pinned workflow")
            for item in source.infolist():
                content = source.read(item.filename) if not item.is_dir() else b""
                if item.filename == WORKFLOW:
                    content = baseline_workflow
                target.writestr(item, content)
        history.PARENT_FIXTURE = patched_parent
        history.PARENT_FIXTURE_SHA256 = hashlib.sha256(patched_parent.read_bytes()).hexdigest()
        history.HISTORICAL_COMPONENTS = set(history.HISTORICAL_COMPONENTS) | {WORKFLOW}
        return history.main()


if __name__ == "__main__":
    raise SystemExit(main())
