"""Partial document runs: synthetic results only, no server import or database."""
import ast,copy,unittest
from pathlib import Path
from datetime import datetime,timezone
source=ast.parse(Path('server.py').read_text(encoding='utf-8-sig'))
names={'merge_document_check_results','document_check_category','document_check_status','document_check_summary_checks'}
ns={'now_iso':lambda:'2026-11-23T12:00:00Z'}
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'server.py','exec'),ns)
class PartialResults(unittest.TestCase):
 def test_unselected_category_unchanged(self):
  for selected,other,key,detail in [('signature','mvs','mvs_person','mvs_extract'),('mvs','signature','signer','signature')]:
   with self.subTest(selected=selected):
    category={'checks':[{'key':key,'status':'ok'}],'counts':{'ok':1},'status':'ok','checked_at':'2026-11-20T10:00:00Z'}
    old={'category_results':{other:category},detail:{'original':'evidence'},'document_check_policy_version':2}
    before=copy.deepcopy(old)
    result=ns['merge_document_check_results'](old,{'selected_categories':[selected],'checks':[{'key':'signer' if selected=='signature' else 'mvs_person','status':'warning'}]})
    self.assertEqual(result['category_results'][other],category);self.assertEqual(result[detail],old[detail]);self.assertEqual(old,before)
 def test_legacy_date_preserved_without_rewriting_input(self):
  old={'checked_at':'2026-11-19T09:00:00Z','checks':[{'key':'mvs_person','status':'ok'}]};before=copy.deepcopy(old)
  result=ns['merge_document_check_results'](old,{'selected_categories':['signature'],'checks':[{'key':'signer','status':'ok'}]})
  self.assertEqual(result['category_results']['mvs']['checked_at'],old['checked_at']);self.assertEqual(old,before)
 def test_never_checked_category_not_synthesized_or_counted(self):
  result=ns['merge_document_check_results']({}, {'selected_categories':['signature'],'checks':[{'key':'signer','status':'ok'}]})
  self.assertNotIn('mvs',result['category_results']);self.assertEqual(result['counts'],{'ok':1,'warning':0,'error':0,'neutral':0})
if __name__=='__main__':unittest.main()
