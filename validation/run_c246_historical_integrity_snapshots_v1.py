"""Run c246-era integrity contracts against their exact Git source snapshots.

This runner intentionally reads raw Git blobs (rather than ``git archive``,
which can apply checkout line-ending conversions). Missing or altered history
is a hard BLOCKED result; it never substitutes files from the candidate tree.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "validation/c246_historical_integrity_snapshots_v1.json"
MANIFEST_SHA256 = "9cc63f46d931ac18e83f1bcce8693c23604e740640031fc312b6e93d4b38eff8"
CONTRACT = "pqm-c246-historical-integrity-snapshots"
VERSION = 1
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class SnapshotError(RuntimeError):
    """A pinned historical snapshot cannot be established safely."""


def git(git_dir: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    command = ["git", "-C", str(git_dir), *args]
    try:
        result = subprocess.run(command, input=input_bytes, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise SnapshotError(f"cannot execute git ({type(exc).__name__})") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SnapshotError(detail[-1][:240] if detail else f"git exited {result.returncode}")
    return result.stdout


def load_manifest(path: Path = MANIFEST, expected_sha256: str = MANIFEST_SHA256) -> dict:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SnapshotError("c246 snapshot route manifest unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SnapshotError("c246 snapshot route manifest SHA-256 mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("c246 snapshot route manifest is invalid") from exc
    if value.get("contract") != CONTRACT or value.get("version") != VERSION:
        raise SnapshotError("unsupported c246 snapshot route contract")
    routes = value.get("routes")
    if not isinstance(routes, list) or not routes:
        raise SnapshotError("c246 snapshot route list is empty")
    modules: set[str] = set()
    commits: set[str] = set()
    for route in routes:
        commit, tree, tests = route.get("commit"), route.get("tree"), route.get("tests")
        if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
            raise SnapshotError("route has an invalid full commit SHA")
        if not isinstance(tree, str) or not FULL_SHA.fullmatch(tree):
            raise SnapshotError(f"{commit}: route has an invalid tree SHA")
        if "archive" in route or "archive_sha256" in route:
            archive = route.get("archive")
            archive_sha = route.get("archive_sha256")
            archive_path = PurePosixPath(archive) if isinstance(archive, str) else None
            if (archive_path is None or archive_path.is_absolute() or ".." in archive_path.parts
                    or "\\" in archive or not isinstance(archive_sha, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", archive_sha)):
                raise SnapshotError(f"{commit}: invalid historical archive pin")
        if commit in commits:
            raise SnapshotError(f"duplicate historical commit route: {commit}")
        commits.add(commit)
        if not isinstance(tests, list) or not tests:
            raise SnapshotError(f"{commit}: route has no test modules")
        for test in tests:
            module, relative, expected = test.get("module"), test.get("path"), test.get("sha256")
            if not isinstance(module, str) or not re.fullmatch(r"test_[A-Za-z0-9_]+", module):
                raise SnapshotError(f"{commit}: invalid test module name")
            if module in modules:
                raise SnapshotError(f"historical test routed more than once: {module}")
            modules.add(module)
            path_obj = PurePosixPath(relative) if isinstance(relative, str) else None
            if (path_obj is None or path_obj.is_absolute() or ".." in path_obj.parts
                    or "\\" in relative or path_obj.suffix != ".py"
                    or path_obj.stem != module):
                raise SnapshotError(f"{commit}: unsafe or inconsistent test path")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise SnapshotError(f"{commit}: invalid pinned test SHA-256")
    return value


def parse_tree(raw: bytes) -> list[tuple[str, str, str]]:
    entries = []
    seen_paths: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, path_bytes = record.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split(" ")
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SnapshotError("historical Git tree listing is malformed") from exc
        parts = PurePosixPath(path).parts
        if (not path or path.startswith("/") or ".." in parts or "\\" in path
                or ":" in path or path in seen_paths):
            raise SnapshotError("unsafe or duplicate path in historical Git tree")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise SnapshotError(f"unsupported object type in historical tree: {path}")
        if not FULL_SHA.fullmatch(oid):
            raise SnapshotError(f"invalid Git blob id in historical tree: {path}")
        seen_paths.add(path)
        entries.append((oid, path, mode))
    return entries


def tree_oid_from_entries(entries: list[dict]) -> str:
    """Rebuild a Git tree id from the authenticated full path/mode/blob list."""
    root: dict = {}
    seen: set[str] = set()
    for entry in entries:
        path, oid, mode = entry.get("path"), entry.get("oid"), entry.get("mode")
        if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
                or ":" in path or ".." in PurePosixPath(path).parts
                or mode not in {"100644", "100755"} or not isinstance(oid, str)
                or not FULL_SHA.fullmatch(oid) or path in seen):
            raise SnapshotError("snapshot index contains an invalid Git tree entry")
        seen.add(path)
        parts = PurePosixPath(path).parts
        node = root
        for directory in parts[:-1]:
            current = node.setdefault(directory, {})
            if not isinstance(current, dict):
                raise SnapshotError("snapshot index has a file/directory path collision")
            node = current
        if parts[-1] in node:
            raise SnapshotError("snapshot index has a duplicate Git tree path")
        node[parts[-1]] = (mode, oid)

    def digest_tree(node: dict) -> str:
        records = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, oid, sort_name = "40000", digest_tree(value), name + "/"
            else:
                mode, oid = value
                sort_name = name
            records.append((sort_name.encode("utf-8"), mode, name, oid))
        body = bytearray()
        for _sort_name, mode, name, oid in sorted(records, key=lambda item: item[0]):
            body.extend(mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
        return hashlib.sha1(b"tree " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()

    return digest_tree(root)


def materialize_archived_snapshot(archive_path: Path, expected_archive_sha256: str,
                                  route: dict, destination: Path) -> list[dict]:
    """Materialize an authenticated, commit-derived subset for offline CI."""
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as exc:
        raise SnapshotError("historical snapshot archive unavailable") from exc
    if hashlib.sha256(archive_bytes).hexdigest() != expected_archive_sha256:
        raise SnapshotError("historical snapshot archive SHA-256 mismatch")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if "snapshot-index.json" not in names or archive.testzip() is not None:
                raise SnapshotError("historical snapshot archive is malformed")
            index = json.loads(archive.read("snapshot-index.json").decode("utf-8"))
            if (index.get("contract") != "pqm-c246-raw-git-tree-archive" or index.get("version") != 1
                    or index.get("commit") != route["commit"] or index.get("tree") != route["tree"]):
                raise SnapshotError("historical snapshot archive identity mismatch")
            entries = index.get("entries")
            archive_files = index.get("archive_files")
            if not isinstance(entries, list) or not isinstance(archive_files, list):
                raise SnapshotError("historical snapshot archive index is incomplete")
            if tree_oid_from_entries(entries) != route["tree"]:
                raise SnapshotError("historical snapshot archive tree SHA mismatch")
            by_path = {entry["path"]: entry for entry in entries}
            if len(by_path) != len(entries):
                raise SnapshotError("historical snapshot archive index has duplicate files")
            expected_names = {"snapshot-index.json"}
            for relative in archive_files:
                path_obj = PurePosixPath(relative) if isinstance(relative, str) else None
                if (path_obj is None or path_obj.is_absolute() or ".." in path_obj.parts
                        or "\\" in relative or relative not in by_path):
                    raise SnapshotError("historical snapshot archive has an unsafe file path")
                expected_names.add("snapshot/" + relative)
            if names != expected_names:
                raise SnapshotError("historical snapshot archive inventory mismatch")
            for test in route["tests"]:
                if test["path"] not in archive_files:
                    raise SnapshotError(f"archived historical test is missing: {test['path']}")
            target_root = destination.resolve()
            target_root.mkdir(parents=True, exist_ok=False)
            data_by_path = {}
            for relative in archive_files:
                data = archive.read("snapshot/" + relative)
                entry = by_path[relative]
                actual_oid = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
                if actual_oid != entry["oid"]:
                    raise SnapshotError(f"archived historical Git blob SHA mismatch: {relative}")
                destination_path = (target_root / Path(*PurePosixPath(relative).parts)).resolve()
                if not destination_path.is_relative_to(target_root):
                    raise SnapshotError("historical archive extraction escaped its temporary root")
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                destination_path.write_bytes(data)
                if entry["mode"] == "100755":
                    destination_path.chmod(destination_path.stat().st_mode | 0o111)
                data_by_path[relative] = data
            for test in route["tests"]:
                if hashlib.sha256(data_by_path[test["path"]]).hexdigest() != test["sha256"]:
                    raise SnapshotError(f"archived historical test SHA-256 mismatch: {test['path']}")
    except SnapshotError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"historical snapshot archive read failed ({type(exc).__name__})") from exc
    return route["tests"]


def raw_blobs(git_dir: Path, entries: list[tuple[str, str, str]]):
    """Yield (entry, raw bytes) from cat-file --batch and verify Git object IDs."""
    command = ["git", "-C", str(git_dir), "cat-file", "--batch"]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    except OSError as exc:
        raise SnapshotError(f"cannot read Git objects ({type(exc).__name__})") from exc
    assert process.stdin is not None and process.stdout is not None
    try:
        for entry in entries:
            oid, path, _mode = entry
            process.stdin.write(oid.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().rstrip(b"\n").split()
            if len(header) != 3 or header[0].decode("ascii", "replace") != oid or header[1] != b"blob":
                raise SnapshotError(f"historical Git blob unavailable or invalid: {path}")
            try:
                size = int(header[2])
            except ValueError as exc:
                raise SnapshotError(f"invalid Git blob size: {path}") from exc
            data = process.stdout.read(size)
            terminator = process.stdout.read(1)
            if len(data) != size or terminator != b"\n":
                raise SnapshotError(f"truncated historical Git blob: {path}")
            git_oid = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0" + data).hexdigest()
            if git_oid != oid:
                raise SnapshotError(f"historical Git blob object SHA mismatch: {path}")
            yield entry, data
    finally:
        process.stdin.close()
        process.stdout.close()
        stderr = process.stderr.read() if process.stderr else b""
        if process.stderr:
            process.stderr.close()
        return_code = process.wait()
        if return_code:
            detail = stderr.decode("utf-8", "replace").strip().splitlines()
            raise SnapshotError(detail[-1][:240] if detail else "git cat-file failed")


def materialize_snapshot(git_dir: Path, route: dict, destination: Path) -> list[dict]:
    commit, expected_tree = route["commit"], route["tree"]
    if not FULL_SHA.fullmatch(commit):
        raise SnapshotError("invalid pinned commit SHA")
    resolved = git(git_dir, "rev-parse", f"{commit}^{{commit}}").decode("ascii").strip()
    if resolved != commit:
        raise SnapshotError(f"historical commit resolution mismatch: {commit}")
    actual_tree = git(git_dir, "rev-parse", f"{commit}^{{tree}}").decode("ascii").strip()
    if actual_tree != expected_tree:
        raise SnapshotError(f"{commit}: historical tree SHA mismatch")
    entries = parse_tree(git(git_dir, "ls-tree", "-rz", "--full-tree", commit))
    if not entries:
        raise SnapshotError(f"{commit}: historical tree is empty")
    by_path = {path: (oid, mode) for oid, path, mode in entries}
    for test in route["tests"]:
        if test["path"] not in by_path:
            raise SnapshotError(f"{commit}: required historical test is missing: {test['path']}")

    target_root = destination.resolve()
    target_root.mkdir(parents=True, exist_ok=False)
    test_bytes: dict[str, bytes] = {}
    for (_oid, relative, mode), data in raw_blobs(git_dir, entries):
        target = (target_root / Path(*PurePosixPath(relative).parts)).resolve()
        if not target.is_relative_to(target_root):
            raise SnapshotError("historical extraction escaped its temporary root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if mode == "100755":
            target.chmod(target.stat().st_mode | 0o111)
        if any(test["path"] == relative for test in route["tests"]):
            test_bytes[relative] = data
    for test in route["tests"]:
        data = test_bytes.get(test["path"])
        if data is None or hashlib.sha256(data).hexdigest() != test["sha256"]:
            raise SnapshotError(f"{commit}: pinned historical test SHA-256 mismatch: {test['path']}")
    return route["tests"]


def run_route(git_dir: Path, route: dict, temp_root: Path) -> tuple[int, int]:
    route_root = temp_root / route["commit"]
    object_check = subprocess.run(["git", "-C", str(git_dir), "cat-file", "-e",
                                   f"{route['commit']}^{{commit}}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if object_check.returncode == 0:
        tests = materialize_snapshot(git_dir, route, route_root)
    elif route.get("archive") and route.get("archive_sha256"):
        tests = materialize_archived_snapshot(ROOT / route["archive"], route["archive_sha256"],
                                               route, route_root)
        print(f"C246 HISTORICAL SNAPSHOT: authenticated offline copy for {route['commit']}", flush=True)
    else:
        raise SnapshotError(f"{route['commit']}: exact Git commit is unavailable and no verified historical copy exists")
    env = os.environ.copy()
    env["PQM_RELEASE_SOURCE_ROOT"] = str(route_root)
    env["PQM_RELEASE_INFRA_ROOT"] = str(route_root)
    env["PQM_RELEASE_MODE"] = "historical_integrity"
    env["PQM_HISTORICAL_SNAPSHOT_GIT_DIR"] = str(git_dir)
    old_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(route_root) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    modules = [test["module"] for test in tests]
    print(f"C246 HISTORICAL SNAPSHOT: {route['commit']} ({len(modules)} modules)", flush=True)
    result = subprocess.run([sys.executable, "-B", "-m", "unittest", "-v", *modules],
                            cwd=route_root, env=env, check=False)
    return result.returncode, len(modules)


def main() -> int:
    try:
        manifest = load_manifest()
        git_dir = Path(os.environ.get("PQM_HISTORICAL_SNAPSHOT_GIT_DIR") or ROOT).resolve()
        with tempfile.TemporaryDirectory(prefix="pqm-c246-history-") as tmp:
            temp_root = Path(tmp).resolve()
            total_modules = 0
            failures = []
            for route in manifest["routes"]:
                try:
                    code, count = run_route(git_dir, route, temp_root)
                except SnapshotError as exc:
                    failures.append(f"{route['commit']}: BLOCKED ({exc})")
                    print(f"C246 HISTORICAL SNAPSHOT: BLOCKED: {failures[-1]}", file=sys.stderr, flush=True)
                    continue
                total_modules += count
                if code:
                    failures.append(f"{route['commit']}: unittest exit {code}")
        if failures:
            print("C246 HISTORICAL SNAPSHOTS: FAIL/BLOCKED: " + "; ".join(failures), file=sys.stderr)
            return 1
        print(f"C246 HISTORICAL SNAPSHOTS: PASS ({total_modules} modules, {len(manifest['routes'])} exact Git snapshots)")
        return 0
    except SnapshotError as exc:
        print(f"C246 HISTORICAL SNAPSHOTS: BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
