"""Run the unchanged Messages v1 overlay with its original workflow pin."""
import hashlib
from pathlib import Path
import tempfile
import zipfile

import run_messages_integrated_v1_history as history


ORIGINAL_PARENT_SHA256 = "2fc0787617767048d92870559d4654dd989e356a898ef58c06015453ebaf71ad"
WORKFLOW = ".github/workflows/release-checks.yml"
BASELINE_WORKFLOW = "validation/fixtures/release_checks_baseline_0347404.yml"


def main():
    repo = Path(history.__file__).resolve().parents[1]
    parent = repo / history.PARENT_FIXTURE
    if hashlib.sha256(parent.read_bytes()).hexdigest() != ORIGINAL_PARENT_SHA256:
        raise SystemExit("Messages historical parent fixture SHA-256 mismatch")
    baseline_workflow = (repo / BASELINE_WORKFLOW).read_bytes()
    with tempfile.TemporaryDirectory(prefix="pqm-messages-parent-addendum-") as temporary:
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
