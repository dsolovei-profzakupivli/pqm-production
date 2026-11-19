"""Run the additive prewrite read-only integrity overlay against this checkout."""
from pathlib import Path
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    raise SystemExit(subprocess.run([sys.executable,'-B','-m','unittest','-v',
        'test_google_writer_prewrite_readonly_integrity_v1'],cwd=ROOT,check=False).returncode)
