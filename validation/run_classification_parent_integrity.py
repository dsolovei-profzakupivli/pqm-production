"""Unchanged parent integrity suite on its exact pinned 6b9830b tree."""
import hashlib,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
FIXTURE='validation/fixtures/supplier_classification_parent_integrity_6b9830b.zip'
SHA='8fc44d8ddcb9c0fd3e5f9a3b4999c89f4b4fdc0a498fa05144dbadf5176aad71'
EXPECTED=['app.js', 'edr_sync_v2.py', 'index.html', 'sandbox_edr_review.py', 'server.py', 'validation/fixtures/google_edr_timezone_alias_v1_baseline_6c310.zip', 'validation/fixtures/messages_integrated_v1_appjs_baseline_6c310.zip', 'validation/local_release_20260911/google_edr_timezone_alias_v1.json', 'validation/local_release_20260911/sandbox_edr_google_nazk_contract_v2.json', 'validation/local_release_20260911/sandbox_edr_google_nazk_reconcile_v1.json', 'validation/local_release_20260911/sandbox_edr_preview_skipped_rows_v1.json', 'validation/local_release_20260911/test_edr_preview_skipped_integrity.py', 'validation/local_release_20260911/test_edr_preview_skipped_rows.py', 'validation/local_release_20260911/test_google_edr_timezone_alias_integrity_v1.py', 'validation/local_release_20260911/test_sandbox_edr_google_nazk_contract_v2_integrity.py', 'validation/local_release_20260911/test_sandbox_edr_google_nazk_reconcile_integrity.py', 'validation/run_google_edr_timezone_alias_v1_integrity.py', 'validation/run_local_release.py', 'validation/run_messages_integrated_v1_history.py']
def main():
 root=Path(__file__).resolve().parents[1];raw=(root/FIXTURE).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=SHA:raise RuntimeError('Parent fixture hash changed')
 with tempfile.TemporaryDirectory(prefix='pqm-classification-parent-') as t:
  dest=Path(t).resolve()
  messages_v2='--messages-v2' in sys.argv
  if messages_v2:
   shutil.copytree(root,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','data','output','logs','evidence','__pycache__','.pytest_cache','*.log'))
  with zipfile.ZipFile(root/FIXTURE) as z:
   if set(z.namelist())!=set(EXPECTED):raise RuntimeError('Parent fixture scope changed')
   for member in z.infolist():
    if messages_v2 and member.filename!='index.html':continue
    p=(dest/member.filename).resolve()
    if not p.is_relative_to(dest):raise RuntimeError('Unsafe fixture path')
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(member))
  env=os.environ.copy();env['PQM_RELEASE_SOURCE_ROOT']=str(dest)
  if messages_v2:
   env.pop('PQM_RELEASE_SOURCE_ROOT',None)
   return subprocess.run([sys.executable,'-B',str(dest/'validation/run_messages_search_header_v2_integrity.py')],cwd=dest,env=env,check=False).returncode
  return subprocess.run([sys.executable,'-B','-m','unittest','validation.local_release_20260911.test_edr_preview_skipped_integrity','-v'],cwd=dest,env=env,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
