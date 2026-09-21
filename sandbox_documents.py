"""Explicit sandbox-only protocol generation and network-denied PDF transport."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

_launch = threading.local()
WORKER = Path(__file__).resolve().with_name('sandbox_pdf_worker.py')


def enabled():
    return os.environ.get('PQM_SANDBOX') == '1' and os.environ.get('PQM_SANDBOX_DOCUMENTS') == '1'


def route_allowed(method, path):
    # Existing auth/RBAC/readiness/final and historical checks remain mandatory.
    # No cancellation, reviews, task completion, refresh or template replacement.
    return enabled() and method == 'POST' and path in {
        '/api/protocol/readiness', '/api/protocol/generate'}


def permitted_process(event, args):
    expected = getattr(_launch, 'expected', None)
    return (event == 'subprocess.Popen' and expected is not None
            and tuple(args[1]) == expected[0] and args[0] == sys.executable
            and args[2] == expected[1] and args[3] == expected[2])


def export_pdf(source, output):
    if not enabled():
        raise RuntimeError('Sandbox document generation is disabled')
    import sandbox_runtime
    data, _, _ = sandbox_runtime.validate_environment()
    root = data / 'protocols'
    source, output = Path(source).resolve(), Path(output).resolve()
    if (not source.is_relative_to(root) or not output.is_relative_to(root)
            or source.suffix.lower() != '.docx' or not source.is_file()):
        raise RuntimeError('Sandbox PDF paths must remain in owned protocols storage')
    with tempfile.TemporaryDirectory(prefix='pqm-sandbox-pdf-') as temp:
        folder = Path(temp).resolve()
        command = [sys.executable, '-I', '-B', str(WORKER), str(source), str(folder)]
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        _launch.expected = (tuple(command), str(folder), environment)
        try:
            process = subprocess.Popen(command, cwd=str(folder), env=environment,
                                       close_fds=True, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                process.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise RuntimeError('Isolated sandbox PDF conversion timed out')
        finally:
            _launch.expected = None
        candidate = folder / (source.stem + '.pdf')
        if process.returncode or not candidate.is_file() or not candidate.read_bytes().startswith(b'%PDF-'):
            raise RuntimeError('Isolated sandbox PDF conversion failed')
        shutil.copyfile(candidate, output)
