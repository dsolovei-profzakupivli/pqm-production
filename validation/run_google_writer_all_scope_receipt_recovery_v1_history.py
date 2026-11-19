"""Run the immutable 9037e57 ALL-scope overlay on its original source tree."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import zipfile


ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'validation/fixtures/google_writer_all_scope_receipt_recovery_v1_9037e57.zip'


def main():
    with tempfile.TemporaryDirectory(prefix='pqm-all-scope-recovery-v1-',dir=ROOT) as tmp:
        destination=Path(tmp).resolve()
        with zipfile.ZipFile(ARCHIVE) as archive:
            for member in archive.infolist():
                target=(destination/member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise RuntimeError('Unsafe path in immutable ALL-scope recovery snapshot')
                if member.is_dir():target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(archive.read(member))
        environment=os.environ.copy()
        environment['PQM_RELEASE_SOURCE_ROOT']=str(destination)
        environment.pop('PQM_RELEASE_MODE',None)
        return subprocess.run([sys.executable,'-B','-m','unittest','-v',
            'test_google_writer_all_scope_receipt_recovery_integrity_v1'],
            cwd=destination,env=environment,check=False).returncode


if __name__=='__main__':
    raise SystemExit(main())
