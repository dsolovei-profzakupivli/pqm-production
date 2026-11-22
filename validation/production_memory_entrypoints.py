"""Direct shared-resolver entrypoint on ephemeral config, without a Git dependency."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import hashlib

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='pqm-production-direct-gate-') as folder:
        source=Path(folder)/'source'
        shutil.copytree(ROOT,source,ignore=shutil.ignore_patterns('.git','data','evidence','__pycache__','backups','logs'))
        # The same three original LF contracts used by run_local_release.py.
        # Only the disposable fixture changes; pins, assertions and source do not.
        for name,expected in {
            'production_edr_google_nazk_ea3079_v1.json':'ffbd92ff26994d2e1e278ea64b16126aeb1159164178377632467bd609ded3e3',
            'production_edr_google_nazk_daily_sync_ea3079_v2.json':'87d6a0e36389e63093bffd8a8dde165e9727f582a3da9f8feb0db7232f0d89ad',
            'production_edr_display_toasts_1b3ff_v1.json':'0a6df86f4e8e386e9718564e8cb21a143c85d1738bdd84c9d45d08b886bda7a9',
        }.items():
            path=source/'validation/fixtures'/name
            raw=path.read_bytes().replace(b'\r\n',b'\n')
            if hashlib.sha256(raw).hexdigest()!=expected:raise AssertionError('Original LF contract changed: '+name)
            path.write_bytes(raw)
        modules=[path.stem for path in sorted(source.glob('*integrity*.py'))]
        modules+=['validation.local_release_20260911.'+path.stem for path in sorted(
            (source/'validation/local_release_20260911').glob('*integrity*.py'))]
        env=dict(os.environ,PQM_ENV='local',PQM_SANDBOX='0',PQM_DATA_DIR=folder,
                 PQM_DB_PATH=str(Path(folder)/'synthetic.sqlite3'),PQM_AUTH_ENABLED='0',PQM_USERS_JSON='',
                 PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',
                 PQM_ENABLE_NAZK_WORKFLOW='0',PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0',
                 PQM_RELEASE_SCHEMA_ONLY='1',PQM_TEST_NETWORK_ISOLATION='1',
                 PYTHONPATH=str(ROOT/'validation/test_runtime'))
        result=subprocess.run([sys.executable,'-B',str(source/'validation/production_integrity_routes.py'),*modules],
                              cwd=source,env=env,timeout=180)
        raise SystemExit(result.returncode)
