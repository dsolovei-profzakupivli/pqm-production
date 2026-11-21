"""Production-only assertions run unchanged in their pinned source, not Sandbox."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from validation.memory_v28_history import snapshot_root

class HistoricalNazkContract(unittest.TestCase):
    def test_all_original_nazk_assertions_in_pinned_tree(self):
        root=snapshot_root('nazk')
        with tempfile.TemporaryDirectory(prefix='pqm-nazk-historical-data-') as data:
            env=dict(os.environ,PQM_ENV='local',PQM_SANDBOX='0',PQM_DATA_DIR=data,
                     PQM_DB_PATH=str(Path(data)/'synthetic.sqlite3'),PQM_AUTH_ENABLED='0',
                     PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_BROWSER='0',
                     PQM_ENABLE_BIDS_UPDATE='0',PQM_BIDS_MODE='disabled',PQM_USERS_JSON='')
            code="import socket,unittest; socket.socket.connect=lambda *args: (_ for _ in ()).throw(RuntimeError('External access forbidden')); suite=unittest.defaultTestLoader.discover('validation/local_release_20260911',pattern='test_nazk_full_contract.py'); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Ran 3 tests',result.stderr)
