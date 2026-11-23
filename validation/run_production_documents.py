"""Addressed local acceptance only; this is not the full Linux/Container Gate."""
import os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
 mode=sys.argv[1] if len(sys.argv)>1 else '--help'
 if mode not in {'--functional','--history','--integrity'}:raise SystemExit('Use --functional, --history or --integrity')
 with tempfile.TemporaryDirectory(prefix='pqm-production-documents-check-') as folder:
  env=os.environ.copy();env.update(PQM_SANDBOX='0',PQM_ENV='local',PQM_DATA_DIR=folder,PQM_DB_PATH=folder+'/synthetic.sqlite3',PQM_RELEASE_SCHEMA_ONLY='1',PQM_AUTH_ENABLED='0',PQM_USERS_JSON='',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0',PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_NAZK_WORKFLOW='0',PQM_TEST_NETWORK_ISOLATION='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONPATH=str(ROOT/'validation/test_runtime'))
  if mode=='--history':
   from validation.production_documents_history import baseline_root
   root=baseline_root(ROOT);env['PYTHONPATH']=str(root/'validation/test_runtime')
   names=['validation.local_release_20260911.test_production_memory_integrity','validation.local_release_20260911.test_production_experience_integrity','validation.local_release_20260911.test_production_memory_saved']
   subprocess.run([sys.executable,'-B',str(root/'validation/production_integrity_routes.py'),*names],cwd=root,env=env,check=True,timeout=240)
   for name in ['sandbox_supplier_ux.cjs','supplier_ux.cjs']:subprocess.run(['node','validation/'+name],cwd=root,env=env,check=True,timeout=60)
  else:
   modules=(['validation.local_release_20260911.test_production_documents_integrity'] if mode=='--integrity' else ['validation.local_release_20260911.test_production_documents','validation.test_mvs_parameter_statuses','validation.test_mvs_parameter_analysis','validation.test_document_partial_selection','validation.local_release_20260911.test_document_signature_verification','validation.local_release_20260911.test_production_memory_runtime','validation.local_release_20260911.test_production_memory_cache','validation.local_release_20260911.test_production_memory_concurrency','validation.local_release_20260911.test_production_experience_queue','validation.local_release_20260911.test_production_memory_ui'])
   subprocess.run([sys.executable,'-B','-m','unittest',*modules,'-v'],cwd=ROOT,env=env,check=True,timeout=240)
 print('PRODUCTION DOCUMENTS '+mode+' PASS',flush=True)
if __name__=='__main__':main()
