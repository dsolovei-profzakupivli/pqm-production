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


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    archive_path = repo / FIXTURE
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != FIXTURE_SHA256:
        raise SystemExit("Messages historical app.js baseline fixture SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="pqm-messages-v1-history-") as temporary:
        tree = Path(temporary).resolve()
        shutil.copytree(
            repo,
            tree,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                ".git", ".venv-gate", ".release-tmp", "data", "output", "logs",
                "evidence", "__pycache__", ".pytest_cache",
            ),
        )
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
        return subprocess.run(
            [sys.executable, "validation/run_integrated_messages_v1_integrity.py"],
            cwd=tree,
            env=env,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
