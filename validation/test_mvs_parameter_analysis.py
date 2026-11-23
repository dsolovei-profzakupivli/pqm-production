"""Real document analysis with synthetic PDF text and disposable SQLite only."""
import json,os,unittest
from pathlib import Path
from unittest.mock import patch
import server
from validation.local_release_20260911 import test_document_signature_verification as original
class MvsAnalysis(unittest.TestCase):
 setUp=original.SignatureAnalysisTests.setUp
 tearDown=original.SignatureAnalysisTests.tearDown
 seed=original.SignatureAnalysisTests.seed
 def test_statuses_counts_and_source_values(self):
  self.seed(documents=[{'id':'pdf','title':'Витяг МВС.pdf','format':'application/pdf','url':'https://example.test/mvs.pdf'}])
  with server.db() as con:con.execute("UPDATE submissions SET date_published='2026-11-23T10:00:00Z' WHERE id='s'")
  labels=['ВІДОМОСТІ ПРО ПРИТЯГНЕННЯ ДО КРИМІНАЛЬНОЇ ВІДПОВІДАЛЬНОСТІ','ВІДОМОСТІ ПРО НАЯВНІСТЬ НЕЗНЯТОЇ ЧИ НЕПОГАШЕНОЇ СУДИМОСТІ','ВІДОМОСТІ ПРО РОЗШУК']
  cases={'green':('ПОВНИЙ','24.10.2026',['ВІДСУТНІ']*3,['ok']*5),'yellow':('','',['']*3,['warning']*5),'red':('СКОРОЧЕНИЙ','23.10.2026',['Наявні відомості']*3,['error']*5),'mixed':('ПОВНИЙ','23.10.2026',['ВІДСУТНІ','Наявні відомості',''],['ok','error','ok','error','warning'])}
  results={}
  for name,(kind,date,values,statuses) in cases.items():
   text=kind+'\nГРОМАДЯНИН(КА)\nІВАНЕНКО ІВАН ІВАНОВИЧ\n01.01.1980 РОКУ НАРОДЖЕННЯ\n'+('СТАНОМ НА '+date+'\n' if date else '')+'\n'.join(label+': '+value for label,value in zip(labels,values))
   with self.subTest(name=name),patch.object(server,'download_document',return_value=b'%PDF synthetic'),patch.object(server,'pdf_text',return_value=text),patch.object(server,'_needs_ukrainian_ocr',return_value=False),patch.object(server,'pdf_has_unreadable_pages',return_value=False),patch.object(server,'verify_prozorro_eds') as eds:
    result=server.analyze_application_documents('s',{'0':['mvs']});eds.assert_not_called()
    keys=['mvs_extract_type','mvs_age','mvs_criminal_liability','mvs_unspent_conviction','mvs_wanted_status']
    self.assertEqual([next(c['status'] for c in result['checks'] if c['key']==key) for key in keys],statuses)
    self.assertEqual(len(result['checks']),7);self.assertEqual(result['counts'],server.document_check_status(result['checks'])[0]);self.assertNotIn('mvs_seal',[c['key'] for c in result['checks']])
    for field,value in zip(['criminal_liability','unspent_conviction','wanted_status'],values):self.assertEqual(result['mvs_extract'][field]['value'],value)
    results[name]=result
  if os.environ.get('PQM_MVS_STATUS_EVIDENCE'):Path(os.environ['PQM_MVS_STATUS_EVIDENCE']).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
 def test_green_mvs_never_verifies_legacy_seal_and_counts_only_extract_checks(self):
  self.seed(documents=[{'id':'pdf','title':'Витяг МВС.pdf','format':'application/pdf','url':'https://example.test/mvs.pdf'},{'id':'seal','title':'Витяг МВС.pdf.p7s','url':'https://example.test/seal.p7s'}])
  absent={'found':True,'value':'ВІДСУТНІ','absent':True}
  extract={'type':'full','person_name':'ІВАНЕНКО ІВАН ІВАНОВИЧ','person_matches_manager':True,'age_days':5,'within_30_days':True,'issue_date':'2026-08-20','submitted_date':'2026-08-25','criminal_liability':absent,'unspent_conviction':absent,'wanted_status':absent}
  with patch.object(server,'download_document',return_value=b'%PDF synthetic') as download,patch.object(server,'pdf_text',return_value='readable'),patch.object(server,'_needs_ukrainian_ocr',return_value=False),patch.object(server,'pdf_has_unreadable_pages',return_value=False),patch.object(server,'analyze_mvs_extract',return_value=extract),patch.object(server,'verify_prozorro_eds') as verify:
   result=server.analyze_application_documents('s',{'0':['mvs'],'1':['mvs_signature']})
  verify.assert_not_called();self.assertEqual(download.call_count,1)
  self.assertEqual(result['selected_categories'],['mvs']);self.assertEqual(result['document_check_policy_version'],2)
  self.assertEqual(server.document_check_category_summaries(result),{'mvs':'ok'})
  self.assertEqual(result['counts'],{'ok':7,'warning':0,'error':0,'neutral':0});self.assertNotIn('mvs_seal',[c['key'] for c in result['checks']])
  self.assertEqual(result['mvs_seal']['technical_status'],'not_applicable')
 def test_legacy_seal_evidence_and_counters_are_preserved_but_new_policy_excludes_it(self):
  import copy
  legacy={'checks':[{'key':'mvs_extract','status':'ok'},{'key':'mvs_seal','status':'warning'}],'mvs_seal':{'technical_status':'unverified'},'checked_at':'2026-08-25T10:00:00Z'}
  before=copy.deepcopy(legacy);visible=server.current_document_check_result(legacy)
  self.assertEqual(legacy,before);self.assertEqual(visible['checks'],before['checks']);self.assertEqual(visible['mvs_seal'],before['mvs_seal']);self.assertEqual(visible['checked_at'],before['checked_at'])
  self.assertEqual(visible['counts'],{'ok':1,'warning':1,'error':0,'neutral':0});self.assertEqual(server.document_check_category_summaries(legacy),{'mvs':'warning'})
  modern=copy.deepcopy(legacy);modern['document_check_policy_version']=2
  self.assertEqual(server.current_document_check_result(modern)['counts'],{'ok':1,'warning':0,'error':0,'neutral':0});self.assertEqual(server.document_check_category_summaries(modern),{'mvs':'ok'})
if __name__=='__main__':unittest.main()
