"""Run the delivered LOCAL suite on a disposable WEB-code/synthetic-DB fixture.

The delivered tests expect source and tests side-by-side, unlike ZIP layout.
No production/local database or credential is read. Outbound network is denied.
"""
import os
import gc
import logging
import hashlib
import zipfile
from contextlib import closing
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PQM_PRODUCTION_DOCUMENTS_SOURCE_ROOT', str(ROOT))
def main():
    with tempfile.TemporaryDirectory(prefix='pqm-local-suite-') as tmp:
        root=Path(tmp)
        for source in ROOT.iterdir():
            if source.name.startswith('.') or source.name in {'data','validation','__pycache__','backups','output','logs','evidence'}:continue
            if source.is_dir():shutil.copytree(source,root/source.name)
            else:shutil.copy2(source,root/source.name)
        for source in (ROOT/'validation/local_release_20260911').glob('test_*.py'):
            shutil.copy2(source,root/source.name)
        # Preserve test-only namespace imports and Node UI probes inside the
        # disposable fixture; never fall back to a different source checkout.
        shutil.copytree(ROOT/'validation', root/'validation',
                        ignore=shutil.ignore_patterns('__pycache__'))
        # These immutable contracts pin LF bytes. Canonicalize only CRLF in
        # the disposable Windows fixture; never rewrite the source manifests.
        for name in ('production_edr_google_nazk_ea3079_v1.json',
                     'production_edr_google_nazk_daily_sync_ea3079_v2.json',
                     'production_edr_display_toasts_1b3ff_v1.json'):
            manifest = root/'validation/fixtures'/name
            manifest.write_bytes(manifest.read_bytes().replace(b'\r\n', b'\n'))
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
            with closing(server.db()) as con:
                with con:scheduler_runtime.migrate(con)
            # Historical byte guards must see the original fixture, while
            # functional tests below use its current connection ownership.
            from production_integrity_overlay import historical_integrity_root
            historical_root = historical_integrity_root(root)
            if historical_root == root:
                raise AssertionError('Historical fixture must be isolated from current functional tests')
            parent = root/'validation/fixtures/production_memory_nazk_test_parent_a53234f.zip'
            if hashlib.sha256(parent.read_bytes()).hexdigest() != '21619cb4e55592f508035f88a466c53e5f9afe024e29ae100bf85203acee54c6':
                raise AssertionError('Historical connection fixture archive changed')
            name = 'validation/local_release_20260911/test_nazk_full_contract.py'
            with zipfile.ZipFile(parent) as archive:
                if set(archive.namelist()) != {name}:
                    raise AssertionError('Unexpected historical fixture members')
                (historical_root/name).write_bytes(archive.read(name))
            suite=unittest.defaultTestLoader.discover(str(root),pattern=sys.argv[1] if len(sys.argv)>1 else 'test_*.py')
            from validation.production_integrity_routes import route_integrity_suite
            route_integrity_suite(suite, root)
            from validation.production_documents_routes import route_suite as document_routes
            document_routes(suite, ROOT)
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            socket.socket.connect=original_connect
            socket.getfqdn=original_getfqdn
            os.chdir(old_cwd)
            gc.collect()
            logging.shutdown()

if __name__=='__main__':raise SystemExit(main())
