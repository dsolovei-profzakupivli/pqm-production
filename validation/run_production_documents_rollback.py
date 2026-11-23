import os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='pqm-rollback-check-') as folder:
 env=os.environ.copy();env.update(PQM_SANDBOX='0',PQM_ENV='local',PQM_DATA_DIR=folder,PQM_DB_PATH=folder+'/synthetic.sqlite3',PQM_RELEASE_SCHEMA_ONLY='1',PQM_AUTH_ENABLED='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_NAZK_WORKFLOW='0',PQM_TEST_NETWORK_ISOLATION='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'validation/test_runtime'))
 names=['validation.test_production_documents_rollback','validation.local_release_20260911.test_production_memory_runtime','validation.local_release_20260911.test_production_memory_cache','validation.local_release_20260911.test_production_memory_concurrency','validation.local_release_20260911.test_production_experience_queue','validation.local_release_20260911.test_production_memory_ui']
 result=subprocess.run([sys.executable,'-B','-m','unittest',*names,'-v'],cwd=ROOT,env=env,timeout=180)
 raise SystemExit(result.returncode)
