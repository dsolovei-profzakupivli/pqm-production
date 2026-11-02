"""Run unchanged Messages/NAZK historical integrity on the exact 6c310 app.js baseline."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


FIXTURE = Path("validation/fixtures/messages_integrated_v1_appjs_baseline_6c310.zip")
FIXTURE_SHA256 = "3bf1aff4aa18d5dd917b417430fac963fca07f3c386f942621302af80c2d58d4"
PARENT_FIXTURE = Path("validation/fixtures/messages_parent_c246edef.zip")
PARENT_FIXTURE_SHA256 = "2fc0787617767048d92870559d4654dd989e356a898ef58c06015453ebaf71ad"
SANDBOX_RUNTIME_FIXTURE = Path("sandbox_runtime_messages_integrated_v1_86ea864.py")
SANDBOX_RUNTIME_SHA256 = "7ce145ff533c134440ad138651660e0c0434a1a7028ba4a7fd8698daf9407499"
HISTORICAL_COMPONENTS = {
    "auth_access.py", "auth_ui.js", "scheduler_runtime.py", "nazk_workflow.py",
    "google_writer_execution.py", "sandbox_runtime.py", "table_widths_ui.js", "violation_protocol_docx.py",
    "theme.css", "styles.css",
}


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    archive_path = repo / FIXTURE
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Messages historical app.js baseline fixture SHA-256 mismatch")
    parent_path = repo / PARENT_FIXTURE
    parent_bytes = parent_path.read_bytes()
    if hashlib.sha256(parent_bytes).hexdigest() != PARENT_FIXTURE_SHA256:
        raise SystemExit("Messages historical parent fixture SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-messages-v1-history-") as temporary:
        tree = Path(temporary).resolve()
        shutil.copytree(
            repo,
            tree,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                ".git", ".venv-gate", ".venv-release", ".release-tmp", ".gate-tmp",
                ".test-packages", "data", "output", "logs", "evidence", "__pycache__",
                ".pytest_cache",
            ),
        )
        # The historical Messages integrity suite compares these components
        # to the exact c246 parent tree. Restore pinned sources before running
        # it so later additive features do not masquerade as historical edits.
        with zipfile.ZipFile(parent_path) as archive:
            parent_files = {item.filename for item in archive.infolist() if not item.is_dir()}
            if not HISTORICAL_COMPONENTS.issubset(parent_files):
                raise SystemExit("Missing historical components in pinned Messages parent fixture")
            for relative in sorted(HISTORICAL_COMPONENTS):
                target = (tree / relative).resolve()
                if not target.is_relative_to(tree):
                    raise SystemExit("Unsafe Messages parent fixture path")
                target.write_bytes(archive.read(relative))
        # This historical integrated manifest pins the exact runtime source at
        # 86ea864. Restore that one component so a later reviewed digest change
        # is tested by its additive contract instead of rewriting v1 history.
        runtime_bytes = SANDBOX_RUNTIME_FIXTURE.read_bytes()
        if hashlib.sha256(runtime_bytes.replace(b"\r\n", b"\n")).hexdigest() != SANDBOX_RUNTIME_SHA256:
            raise SystemExit("Messages v1 sandbox runtime baseline fixture SHA-256 mismatch")
        runtime_target = (tree / "sandbox_runtime.py").resolve()
        if not runtime_target.is_relative_to(tree):
            raise SystemExit("Unsafe Messages v1 sandbox runtime fixture path")
        runtime_target.write_bytes(runtime_bytes)
        with zipfile.ZipFile(archive_path) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != {"app.js"}:
                raise SystemExit("Unexpected Messages historical baseline fixture members")
            target = (tree / "app.js").resolve()
            if not target.is_relative_to(tree):
                raise SystemExit("Unsafe path in Messages historical baseline fixture")
            target.write_bytes(archive.read("app.js"))
        env = os.environ.copy()
        env.pop("PQM_RELEASE_SOURCE_ROOT", None)
        env.pop("PQM_RELEASE_MODE", None)
        # Keep test-only dependencies available when the isolated child changes
        # its working directory. CI installations continue to use site-packages.
        test_packages = repo / ".test-packages"
        if test_packages.is_dir():
            inherited = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(test_packages) + (os.pathsep + inherited if inherited else "")
        return subprocess.run(
            [sys.executable, "validation/run_integrated_messages_v1_integrity.py"],
            cwd=tree,
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
