"""DOCX download names: presentation-only quotes, Windows safety, actual delivery."""
import copy,io,json,re,tempfile,unittest,urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from docx import Document
import server
from test_violation_reports import report_payload

class ViolationFilenameQuotesTests(unittest.TestCase):
 def item(self):
  return {'id':'report-internal','tender_id':'synthetic-tender','tender_pretty_id':'UA-2026-10-01-000001','authority_code':'40996564','report_id':'UA-D-2026-10-21-000001','author_name':'КНП "ОКОЦ КОР"','author_code':'11111111','defendant_code':'00447853','defendant_name':'ПРАТ "ЮРІЯ"','supplier_verified':{'full_name':'ПРАТ "ЮРІЯ"','short_name':'ПРАТ "ЮРІЯ"'},'review':{'customer_verified_short_name':'КНП "ОКОЦ КОР"','internal_decision':'warning','assigned_officer':'Тестова УО','decision_justification':'Незмінний текст','protocol_number':'810','protocol_date':'2026-10-21'},'deadline_control':{'supplier_ready':True},'procurement_context':{'available':True,'tender_date_published':'2026-10-01','winner_selected_at':'2026-10-02'},'reason':'contractBreach','defendant_statements':[],'evidence_documents':[]}
 def gate(self):return {'ready':True,'protocol_number':'810','protocol_date':'2026-10-21','protocol_type':'warning'}
 def test_paired_quotes_in_customer_and_supplier_exact_docx_name(self):
  item=self.item();original=copy.deepcopy(item)
  self.assertEqual(server._violation_protocol_filename(item,self.gate()),'UA-D-2026-10-21-000001_810_П_КНП «ОКОЦ КОР» (на ПРАТ «ЮРІЯ»; 00447853).docx');self.assertEqual(item,original)
 def test_already_normalized_quotes_and_apostrophes_preserved(self):
  item=self.item();item['review']['customer_verified_short_name']='КНП «ОКОЦ КОР»';item['supplier_verified']['short_name']='ТОВ «М’ЯТА»'
  name=server._violation_protocol_filename(item,self.gate());self.assertIn('КНП «ОКОЦ КОР» (на ТОВ «М’ЯТА»;',name)
 def test_unpaired_or_ambiguous_quotes_are_not_invented(self):
  for value in ['КНП "ОКОЦ','КНП ОКОЦ"','КНП "A" "B','КНП "A" і "B"']:
   with self.subTest(value=value):
    item=self.item();item['review']['customer_verified_short_name']=value;name=server._violation_protocol_filename(item,self.gate());customer=name.split('_П_',1)[1].split(' (на ',1)[0];self.assertNotIn('"',customer);self.assertNotIn('«',customer);self.assertNotIn('»',customer)
 def test_windows_forbidden_symbols_are_still_sanitized(self):
  item=self.item();item['review']['customer_verified_short_name']='../КНП "A<>:/\\|?*\x00\x1f\x7f"  '
  name=server._violation_protocol_filename(item,self.gate());self.assertNotRegex(name,r'[<>:"/\\|?*\x00-\x1f\x7f]');self.assertEqual(Path(name).name,name);self.assertIn('«A',name)
 def test_only_entity_names_are_normalized_not_codes_or_protocol_number(self):
  item=self.item();item['report_id']='ID"A"';item['defendant_code']='00"44"';gate={**self.gate(),'protocol_number':'810"B"'}
  name=server._violation_protocol_filename(item,gate);self.assertTrue(name.startswith('ID-A-_810-B-_П_'));self.assertIn('; 00-44-).docx',name);self.assertNotIn('«B»',name)
 def test_limit_and_required_requisites_remain_unchanged(self):
  item=self.item();item['review']['customer_verified_short_name']='А'*250
  with self.assertRaisesRegex(ValueError,'240'):server._violation_protocol_filename(item,self.gate())
  with self.assertRaisesRegex(ValueError,'номер протоколу'):server._violation_protocol_filename(self.item(),{**self.gate(),'protocol_number':''})
 def test_real_generation_metadata_response_and_http_download(self):
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
   root=Path(folder);database=root/'synthetic.sqlite3';protocols=root/'protocols';item=self.item();before=copy.deepcopy(item)
   source=io.BytesIO();doc=Document();doc.add_paragraph('Незмінний текст документа «ОКОЦ КОР»');doc.save(source);expected_bytes=source.getvalue()
   def renderer(_kind,target,*_args,**_kwargs):target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(expected_bytes)
   with patch.object(server,'DB_PATH',database),patch.object(server,'PROTOCOLS_DIR',protocols):
    server.init_db();server.save_violation_report(report_payload())
    with patch.object(server,'violation_report_detail',return_value=item),patch.object(server,'violation_protocol_readiness',return_value=self.gate()),patch.object(server,'build_violation_protocol_docx',side_effect=renderer):
     result=server.generate_violation_protocol('report-internal',{'protocol_number':'810','protocol_date':'2026-10-21'})
    human='UA-D-2026-10-21-000001_810_П_КНП «ОКОЦ КОР» (на ПРАТ «ЮРІЯ»; 00447853).docx'
    self.assertEqual(result['download_filename'],human);self.assertRegex(result['filename'],r'^violation-[a-f0-9]+\.docx$');self.assertEqual(result['metadata']['protocol_download']['filename'],human)
    self.assertEqual(server._violation_protocol_download_filename(result['filename']),human)
    headers={};body=io.BytesIO();request=SimpleNamespace(path=result['download_url'],send_response=lambda code:self.assertEqual(code,200),send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None,wfile=body)
    server.Handler._do_GET(request)
    self.assertEqual(urllib.parse.unquote(headers['Content-Disposition'].split("filename*=UTF-8''",1)[1]),human)
    self.assertEqual(body.getvalue(),expected_bytes);self.assertEqual((protocols/result['filename']).read_bytes(),expected_bytes);self.assertEqual(item,before)
 def test_historical_download_name_is_not_rewritten(self):
  import sqlite3
  con=sqlite3.connect(':memory:')
  try:
   con.execute('CREATE TABLE violation_report_reviews(generated_protocol_filename TEXT,generated_protocol_metadata_json TEXT)');old='OLD_КНП -ОКОЦ КОР-.docx';con.execute('INSERT INTO violation_report_reviews VALUES (?,?)',('stored.docx',json.dumps({'protocol_download':{'filename':old}})))
   with patch.object(server,'db',return_value=con):self.assertEqual(server._violation_protocol_download_filename('stored.docx'),old)
  finally:con.close()

if __name__=='__main__':unittest.main(verbosity=2)
