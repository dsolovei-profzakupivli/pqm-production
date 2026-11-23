"""Rollback compatibility on temporary DB; no UI/CSV/queue changes."""
import ast,copy,json,unittest
from pathlib import Path
import server
from validation.local_release_20260911 import test_production_memory_saved as fixture
class RollbackCompatibility(unittest.TestCase):
 setUp=fixture.ProductionSavedResults.setUp
 seed=fixture.ProductionSavedResults.seed
 def test_new_policy_reader_keeps_counters_details_dates_and_input(self):
  checks=[{'key':'signer','status':'ok'},{'key':'mvs_person','status':'ok'},{'key':'mvs_seal','status':'warning'},{'key':'contract_experience','status':'neutral','search_status':'none'}]
  data={'document_check_policy_version':2,'checks':checks,'counts':{'ok':2,'warning':0,'error':0,'neutral':0},'category_results':{'signature':{'checked_at':'signature-date','checks':[checks[0]],'status':'ok'},'mvs':{'checked_at':'mvs-date','checks':checks[1:3],'status':'warning'}}}
  old=copy.deepcopy(data);result=server.current_document_check_result(data);self.assertEqual(result['counts'],old['counts']);self.assertEqual(result['category_results'],old['category_results']);self.assertEqual(data,old)
 def test_legacy_reader_keeps_original_seal_and_experience_counts(self):
  data={'checks':[{'key':'signer','status':'ok'},{'key':'mvs_seal','status':'warning'},{'key':'contract_experience','status':'neutral'}]}
  result=server.current_document_check_result(data);self.assertEqual(result['counts'],{'ok':1,'warning':1,'error':0,'neutral':1})
 def test_each_legacy_partial_repeat_keeps_other_category(self):
  for category,other in [('signature','mvs'),('mvs','signature')]:
   self.seed(category)
   before=server._store_document_check_result(category,{'document_check_policy_version':2,'selected_categories':['signature','mvs','experience'],'checks':[{'key':'signer','status':'ok'},{'key':'mvs_person','status':'ok'},{'key':'contract_experience','status':'neutral','search_status':'none'}]},'new-version')
   result=server._store_document_check_result(category,{'selected_categories':[category],'checks':[{'key':'signer' if category=='signature' else 'mvs_person','status':'warning'}]},'rollback',require_editable=True)
   self.assertEqual(result['category_results'][other],before['category_results'][other]);self.assertEqual(result['category_results']['experience'],before['category_results']['experience']);self.assertEqual(result['document_check_policy_version'],2)
 def test_manifest_and_only_compatibility_server_changes(self):
  import hashlib,zipfile
  manifest=json.loads(Path('validation/production_documents_rollback_v1.json').read_text(encoding='utf8'))
  for name,pin in manifest['files'].items():self.assertEqual(hashlib.sha256(Path(name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),pin,name)
  with zipfile.ZipFile('validation/fixtures/production_documents_parent_98c7f8a.zip') as archive:old=archive.read('files/server.py').decode('utf8')
  def funcs(text):return {n.name:ast.dump(n) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
  a,b=funcs(old),funcs(Path('server.py').read_text(encoding='utf8'));allowed={'document_check_category_summaries','current_document_check_result','merge_document_check_results','_store_document_check_result'}
  self.assertEqual(set(b)-set(a),{'document_check_summary_checks'})
  for name in a:
   if name not in allowed:self.assertEqual(a[name],b[name],name)
if __name__=='__main__':unittest.main()
