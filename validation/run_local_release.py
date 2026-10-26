"""Run the delivered LOCAL suite on a disposable WEB-code/synthetic-DB fixture.

The delivered tests expect source and tests side-by-side, unlike ZIP layout.
No production/local database or credential is read. Outbound network is denied.
"""
import os
import gc
import logging
from contextlib import closing
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
        # Preserve namespace imports used by root-level regressions. The flat
        # copies above remain the discovery layout expected by delivered tests.
        shutil.copytree(ROOT/'validation/local_release_20260911',
                        root/'validation/local_release_20260911',
                        ignore=shutil.ignore_patterns('__pycache__'))
        # The integrated UI-v2 integrity contract pins this local-only
        # destination/safety smoke helper; include it in the disposable tree
        # so exact-tree and adversarial mutation checks see the same fixture.
        shutil.copy2(ROOT/'validation/sandbox_editable_smoke.py',
                     root/'validation/sandbox_editable_smoke.py')
        fixture_target=root/'validation/fixtures'
        fixture_target.mkdir(parents=True,exist_ok=True)
        for fixture_name in ('protocol_integrity_history.zip',
                             'nazk_integrity_baseline_de77401.zip',
                             'column_widths_baseline_4625498.zip',
                             'nazk_preview_baseline_f394d4c.zip',
                             'appeals_scenario_v11_tail.zip',
                             'appeals_scenario_v11_api_tail.zip',
                             'table_widths_v11_tail.zip'):
            fixture_source=ROOT/'validation/fixtures'/fixture_name
            shutil.copy2(fixture_source,fixture_target/fixture_name)
        for helper in ('nazk_preview_fixture.py', 'nazk_preview_browser_fixture.py'):
            shutil.copy2(ROOT/'validation'/helper, root/'validation'/helper)
        # The runner is itself pinned by the column-width integrity variant.
        shutil.copy2(ROOT/'validation/run_local_release.py',root/'validation/run_local_release.py')
        shutil.copy2(ROOT/'validation/docker_release_gate.py',root/'validation/docker_release_gate.py')
        # The integrated UI integrity manifest now guards the required host-runner
        # browser workflow, so include that exact CI file in the disposable tree.
        workflow_source=ROOT/'.github/workflows/release-checks.yml'
        workflow_target=root/'.github/workflows/release-checks.yml'
        workflow_target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(workflow_source,workflow_target)
        # Node regressions run against this same disposable source fixture.
        for source in (ROOT/'validation').glob('*.cjs'):
            shutil.copy2(source,root/'validation'/source.name)
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
            suite=unittest.defaultTestLoader.discover(str(root),pattern=sys.argv[1] if len(sys.argv)>1 else 'test_*.py')
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            socket.socket.connect=original_connect
            socket.getfqdn=original_getfqdn
            os.chdir(old_cwd)
            gc.collect()  # Release cyclic SQLite handles before Windows cleanup.
            logging.shutdown()

if __name__=='__main__':raise SystemExit(main())
