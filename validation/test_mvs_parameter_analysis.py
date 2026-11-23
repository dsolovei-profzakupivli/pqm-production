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
if __name__=='__main__':unittest.main()
