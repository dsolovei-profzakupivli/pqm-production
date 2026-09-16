"""Run the delivered LOCAL suite on a disposable WEB-code/synthetic-DB fixture.

The delivered tests expect source and tests side-by-side, unlike ZIP layout.
No production/local database or credential is read. Outbound network is denied.
"""
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory(prefix='pqm-local-suite-') as tmp:
        root=Path(tmp)
        for source in ROOT.iterdir():
            if source.name.startswith('.') or source.name in {'data','validation','__pycache__','backups','output','logs'}:continue
            if source.is_dir():shutil.copytree(source,root/source.name)
            else:shutil.copy2(source,root/source.name)
        for source in (ROOT/'validation/local_release_20260911').glob('test_*.py'):
            shutil.copy2(source,root/source.name)
        # Delivered tests assume runtime DOCX copies have already been installed.
        shutil.copytree(root/'templates', root/'data/templates', dirs_exist_ok=True)
        os.environ.update(HOST='127.0.0.1',PORT='8080',PQM_ENV='local',PQM_DATA_DIR=str(root/'data'),PQM_DB_PATH=str(root/'data/pqm.sqlite3'),
                          PQM_RELEASE_SCHEMA_ONLY='0',PQM_AUTH_ENABLED='0',PQM_USERS_JSON='',
                          PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0',
                          PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_BROWSER='0',
                          PQM_ENABLE_BIDS_UPDATE='0',PQM_ENABLE_POWERBI='0',PQM_BIDS_MODE='disabled')
        original_connect=socket.socket.connect
        original_getfqdn=socket.getfqdn
        socket.getfqdn=lambda name='':name or 'localhost'
        def isolated_connect(sock,address):
            if isinstance(address,tuple) and address[0] not in {'127.0.0.1','localhost','::1'}:
                raise RuntimeError('Outbound network forbidden in release tests')
            return original_connect(sock,address)
        socket.socket.connect=isolated_connect
        old_cwd=Path.cwd()
        os.chdir(root)
        sys.path.insert(0,str(root))
        try:
            import server
            server.init_db()
            server.init_reference_tables(server.DB_PATH)
            import scheduler_runtime
            with server.db() as con:scheduler_runtime.migrate(con)
            suite=unittest.defaultTestLoader.discover(str(root),pattern=sys.argv[1] if len(sys.argv)>1 else 'test_*.py')
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            socket.socket.connect=original_connect
            socket.getfqdn=original_getfqdn
            os.chdir(old_cwd)

if __name__=='__main__':raise SystemExit(main())
