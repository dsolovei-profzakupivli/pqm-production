"""On-demand, cached PDF export for generated violation protocol DOCX files."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path


_CONVERSION_LOCK = threading.RLock()


def _soffice_executable() -> str | None:
    configured = str(os.environ.get("PQM_SOFFICE_EXE") or "").strip()
    candidates = [configured, shutil.which("soffice"), shutil.which("libreoffice")]
    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ])
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def _export_with_libreoffice(source: Path, output: Path, executable: str) -> None:
    with tempfile.TemporaryDirectory(prefix="pqm-protocol-pdf-") as folder:
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", folder, str(source)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        candidate = Path(folder) / f"{source.stem}.pdf"
        if result.returncode or not candidate.is_file():
            detail = (result.stderr or result.stdout or "LibreOffice не створив PDF").strip()
            raise RuntimeError(f"Не вдалося сформувати PDF: {detail}")
        shutil.copyfile(candidate, output)


def _export_with_word(source: Path, output: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    word = Path(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE")
    if not powershell or not word.is_file():
        raise RuntimeError("PDF renderer недоступний")
    environment = dict(os.environ, PQM_PDF_SOURCE=str(source), PQM_PDF_TARGET=str(output))
    script = (
        "$word=New-Object -ComObject Word.Application;"
        "$word.Visible=$false;$word.DisplayAlerts=0;"
        "try{$doc=$word.Documents.Open($env:PQM_PDF_SOURCE,$false,$true);"
        "$doc.ExportAsFixedFormat($env:PQM_PDF_TARGET,17);$doc.Close($false)}"
        "finally{$word.Quit()}"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment, capture_output=True, text=True, timeout=120,
        check=False, creationflags=creationflags,
    )
    if result.returncode or not output.is_file():
        detail = (result.stderr or result.stdout or "Microsoft Word не створив PDF").strip()
        raise RuntimeError(f"Не вдалося сформувати PDF: {detail}")


def _word_available() -> bool:
    return bool((shutil.which("powershell.exe") or shutil.which("pwsh.exe")) and
                Path(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE").is_file())


def _running_on_windows() -> bool:
    return os.name == "nt"


def _export_faithfully(source: Path, output: Path) -> str:
    """Export the DOCX itself; never approximate its layout through HTML."""
    failures = []
    if _running_on_windows() and _word_available():
        try:
            _export_with_word(source, output)
            return "word_com"
        except RuntimeError as exc:
            failures.append(str(exc))
    if executable := _soffice_executable():
        try:
            _export_with_libreoffice(source, output, executable)
            return "libreoffice"
        except RuntimeError as exc:
            failures.append(str(exc))
    detail = " | ".join(failures)
    if detail:
        raise RuntimeError(
            "PDF export недоступний у поточному сеансі. "
            "Потрібен Microsoft Word або LibreOffice. " + detail
        )
    raise RuntimeError(
        "PDF export недоступний: не знайдено Microsoft Word або LibreOffice."
    )


def ensure_pdf(source_path: str | Path, output_path: str | Path) -> Path:
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise FileNotFoundError("DOCX протоколу не знайдено")
    output.parent.mkdir(parents=True, exist_ok=True)
    with _CONVERSION_LOCK:
        provenance = output.with_suffix(output.suffix + ".converter")
        cached_converter = provenance.read_text(encoding="utf-8").strip() if provenance.is_file() else ""
        if (output.is_file() and output.stat().st_mtime_ns >= source.stat().st_mtime_ns
                and cached_converter in {"word_com", "libreoffice"}):
            return output
        temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.pdf")
        temporary_provenance = provenance.with_name(f".{provenance.name}.{uuid.uuid4().hex}.tmp")
        try:
            converter = _export_faithfully(source, temporary)
            if temporary.read_bytes()[:5] != b"%PDF-":
                raise RuntimeError("PDF renderer повернув некоректний файл")
            os.replace(temporary, output)
            temporary_provenance.write_text(converter, encoding="utf-8")
            os.replace(temporary_provenance, provenance)
        finally:
            temporary.unlink(missing_ok=True)
            temporary_provenance.unlink(missing_ok=True)
    return output
