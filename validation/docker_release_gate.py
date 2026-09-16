"""Pre-deploy STOP/GO on the built image, using disposable synthetic data only.

Never inherits live PQM config/secrets or opens persistent storage. A failure
exits nonzero so Render keeps the previous maintenance instance running.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root / "validation/test_runtime"),
        "PQM_TEST_NETWORK_ISOLATION": "1",
        "PQM_RELEASE_SCHEMA_ONLY": "1",
        "PQM_ENABLE_NAZK_WORKFLOW": "0",
    }
    commands = [
        [sys.executable, str(root / "validation/release_0916_smoke.py")],
        [sys.executable, "-m", "unittest", "discover", "-s",
         "validation/local_release_20260911", "-p", "test_nazk_registry_evidence.py", "-v"],
        ["node", "validation/nazk_evidence_ui.cjs"],
    ]
    for command in commands:
        print("DOCKER GATE: synthetic check", command[-1], flush=True)
        subprocess.run(command, cwd=root, env=env, check=True, timeout=180)

    # Converter smoke cannot generate or replace any operational document.
    from docx import Document
    exe = shutil.which("soffice", path=env["PATH"]) or shutil.which("libreoffice", path=env["PATH"])
    if not exe:
        raise RuntimeError("STOP: DOCX/PDF converter unavailable in image")
    with tempfile.TemporaryDirectory(prefix="pqm-docker-pdf-gate-") as tmp:
        folder = Path(tmp)
        source = folder / "synthetic.docx"
        doc = Document()
        doc.add_paragraph("PQM — синтетична перевірка PDF; без робочих даних.")
        doc.save(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        subprocess.run([exe, "-env:UserInstallation=" + (folder / "profile").as_uri(),
                        "--headless", "--convert-to", "pdf", "--outdir", tmp, str(source)],
                       env=env, check=True, timeout=120)
        if not (folder / "synthetic.pdf").read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("STOP: invalid PDF output")
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise RuntimeError("STOP: converter altered source DOCX")
    print("DOCKER GATE: GO — HTTP, evidence, UI and PDF fixture passed; live DB writes=0", flush=True)


if __name__ == "__main__":
    main()
