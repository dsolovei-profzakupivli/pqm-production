"""Run the additive prewrite diagnostics v2 integrity overlay."""
from pathlib import Path
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    raise SystemExit(subprocess.run([sys.executable,'-B','-m','unittest','-v',
        'test_google_writer_prewrite_diagnostics_integrity_v2'],cwd=ROOT,check=False).returncode)
