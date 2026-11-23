"""Current document/CSV/rollback acceptance. Temporary SQLite and loopback only."""
import ast,copy,csv,io,json,os,threading,unittest
from pathlib import Path
from unittest.mock import patch
import server
from validation.local_release_20260911 import test_production_memory_saved as fixture
class PartialStorage(unittest.TestCase):
 setUp=fixture.ProductionSavedResults.setUp
 seed=fixture.ProductionSavedResults.seed
 def test_each_partial_repeat_preserves_other_category_details_dates_and_retry(self):
  for selected,other in [('signature','mvs'),('mvs','signature')]:
   with self.subTest(selected=selected):
    sid=selected;self.seed(sid)
    old={'document_check_policy_version':2,'selected_categories':['signature','mvs','experience'],'checks':[{'key':'signer','status':'ok'},{'key':'mvs_person','status':'ok'},{'key':'contract_experience','status':'neutral','search_status':'none','background_retry':{'attempts':2,'epoch':'original'}}],'signature':{'signer':'Original signer'},'mvs_extract':{'person_name':'Original person'}}
    saved=server._store_document_check_result(sid,old,'fixture')
    current={'document_check_policy_version':2,'selected_categories':[selected],'checks':[{'key':'signer' if selected=='signature' else 'mvs_person','status':'warning'}],'signature':{},'mvs_extract':{}}
    result=server._store_document_check_result(sid,current,'fixture',require_editable=True)
    self.assertEqual(result['category_results'][other],saved['category_results'][other]);self.assertEqual(result['category_results']['experience'],saved['category_results']['experience'])
    self.assertEqual(result['signature' if other=='signature' else 'mvs_extract'],saved['signature' if other=='signature' else 'mvs_extract'])
    self.assertEqual(result['counts'],{'ok':1,'warning':1,'error':0,'neutral':0})
 def test_never_checked_category_not_created(self):
  self.seed();result=server._store_document_check_result('s',{'document_check_policy_version':2,'selected_categories':['signature'],'checks':[{'key':'signer','status':'ok'}]},'fixture',require_editable=True)
  self.assertNotIn('mvs',result['category_results']);self.assertEqual(result['counts']['ok'],1)
 def test_rollback_reader_and_writer_preserve_policy2_categories(self):
  import zipfile,hashlib
  root=os.environ.get('PQM_DOCUMENTS_ROLLBACK')
  if root:
   raw=(Path(root)/'server.py').read_bytes()
  else:
   with zipfile.ZipFile(Path(server.__file__).resolve().parent/'validation/fixtures/production_documents_rollback_v1.zip') as archive:
    raw=archive.read('server.py');index=json.loads(archive.read('INDEX.json'))
    self.assertEqual(hashlib.sha256(raw).hexdigest(),index['server_sha256']);self.assertEqual(index['baseline'],'98c7f8a50840b1fed81d80f23740563d233d3207')
  text=raw.decode('utf-8-sig')
  names={'document_check_category_summaries','document_check_summary_checks','current_document_check_result','merge_document_check_results','_store_document_check_result'}
  scope=dict(server.__dict__);exec(compile(ast.Module(body=[n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'rollback-compatibility','exec'),scope)
  self.seed();original=server._store_document_check_result('s',{'document_check_policy_version':2,'selected_categories':['signature','mvs','experience'],'checks':[{'key':'signer','status':'ok'},{'key':'mvs_person','status':'ok'},{'key':'mvs_seal','status':'warning'},{'key':'contract_experience','status':'neutral','search_status':'none'}]},'fixture')
  before=copy.deepcopy(original);visible=scope['current_document_check_result'](original);self.assertEqual(visible['counts'],original['counts']);self.assertEqual(original,before)
  for selected,other in [('signature','mvs'),('mvs','signature')]:
   current={'selected_categories':[selected],'checks':[{'key':'signer' if selected=='signature' else 'mvs_person','status':'ok'}]}
   result=scope['_store_document_check_result']('s',current,'rollback',require_editable=True)
   self.assertEqual(result['category_results'][other],original['category_results'][other]);self.assertEqual(result['document_check_policy_version'],2)
   original=result
 def test_concurrent_manual_and_background_writes_preserve_existing_mvs(self):
  self.seed();saved=server._store_document_check_result('s',{'document_check_policy_version':2,'selected_categories':['mvs'],'checks':[{'key':'mvs_person','status':'ok'}]},'fixture')
  barrier=threading.Barrier(3);errors=[]
  def save(category):
   try:
    barrier.wait(5);server._store_document_check_result('s',{'selected_categories':[category],'checks':[{'key':'signer' if category=='signature' else 'contract_experience','status':'ok' if category=='signature' else 'neutral','search_status':'found'}]},'fixture',require_editable=category=='signature')
   except Exception as exc:errors.append(str(exc))
  threads=[threading.Thread(target=save,args=(category,)) for category in ['signature','experience']]
  for thread in threads:thread.start()
  barrier.wait(5)
  for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
  self.assertEqual(errors,[])
  with server.db() as con:result=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
  self.assertEqual(set(result['category_results']),{'signature','mvs','experience'});self.assertEqual(result['category_results']['mvs'],saved['category_results']['mvs']);self.assertEqual(result['counts'],{'ok':2,'warning':0,'error':0,'neutral':0})
class CsvVersions(unittest.TestCase):
 setUp=fixture.ProductionSavedResults.setUp
 seed=fixture.ProductionSavedResults.seed
 def seed_csv(self):
  self.seed('s','active')
  with server.db() as con:
   con.execute("INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,raw_json,synced_at) VALUES ('r','f','q-s','12345678','active','{}','before')")
   con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,edr_status,manager_name,edr_checked_at,edr_officer,source_sheet,synced_at) VALUES ('12345678',?, 'Зареєстровано','Керівник','2026-11-20T14:35:12+02:00','Synthetic Officer','ЮО','before')",('Назва, \"цитата\"\nдругий рядок',))
 def baseline(self):
  scope=dict(server.__dict__);exec((Path(server.__file__).resolve().parent/'validation/fixtures/production_documents_98c7f8a_csv.py').read_text(encoding='utf8'),scope);return scope
 def test_default_csv_is_byte_identical_to_production(self):
  self.seed_csv();old=self.baseline();filters={'supplier_codes':{'12345678'},'selected_mode':True}
  before=old['supplier_edr_export_csv']('ALL',filters);current=server.supplier_edr_export_csv('ALL',filters)
  self.assertEqual(current,before);self.assertEqual(server.supplier_edr_export_csv('ALL',filters,csv_version='1'),before)
  rows=list(csv.reader(io.StringIO(current.decode('utf-8-sig'))));self.assertEqual(len(rows),2);self.assertTrue(all(len(row)==5 for row in rows));self.assertTrue(current.startswith(b'\xef\xbb\xbf'))
 def test_v2_is_explicit_and_preserves_population_first_four_and_classification(self):
  self.seed_csv();filters={'supplier_codes':{'12345678'},'selected_mode':True}
  old=list(csv.reader(io.StringIO(server.supplier_edr_export_csv('ALL',filters).decode('utf-8-sig'))));new=list(csv.reader(io.StringIO(server.supplier_edr_export_csv('ALL',filters,csv_version='2').decode('utf-8-sig'))))
  self.assertEqual(len(old),len(new));self.assertEqual(old[0],new[0][:5]);self.assertEqual(old[1][:4],new[1][:4]);self.assertEqual(len(new[0]),8)
  self.assertEqual(new[0][-3:],['Статус Prozorro','Дата останньої заявки','УО'])
 def test_monitoring_legacy_bytes_and_explicit_v2(self):
  row={'supplier_code':'00123456','supplier_name':'Назва, \"цитата\"','edr_status':'Зареєстровано','manager_name':'Керівник','verification_date':'2026-11-20','prozorro_status':'Активний','latest_application_date':'2026-11-21','verification_officer':'Officer'}
  with patch.object(server,'_edr_monitoring_rows',return_value=[row]):
   old=self.baseline();old['_edr_monitoring_rows']=server._edr_monitoring_rows
   self.assertEqual(server.edr_monitoring_export_csv({'00123456'}),old['edr_monitoring_export_csv']({'00123456'}))
   self.assertEqual(len(next(csv.reader(io.StringIO(server.edr_monitoring_export_csv({'00123456'},'2').decode('utf-8-sig'))))),8)
 def test_exports_do_not_change_database_or_call_external_services(self):
  self.seed_csv()
  with server.db() as con:before='\n'.join(con.iterdump())
  with patch.object(server,'api_get',side_effect=AssertionError('No external API')):
   for version in ['1','2']:server.supplier_edr_export_csv('ALL',{'supplier_codes':{'12345678'},'selected_mode':True},csv_version=version)
  with server.db() as con:self.assertEqual('\n'.join(con.iterdump()),before)
 def test_invalid_version_rejected(self):
  for value in ['3','v2','',False]:
   with self.subTest(value=value),self.assertRaises(ValueError):server.supplier_edr_export_csv('ALL',csv_version=value)
class DocumentHttp(unittest.TestCase):
 setUpClass=classmethod(fixture.SavedHistoryHTTPTests.setUpClass.__func__)
 def request(self,path,method='GET',body=None,role='admin'):
  import base64,http.client
  con=http.client.HTTPConnection('127.0.0.1',self.port,timeout=15);auth=base64.b64encode(('fixture-'+role+':'+self.web.PASSWORD).encode()).decode()
  headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'};con.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers);response=con.getresponse();data=response.read();status=response.status;con.close();return status,data
 def test_each_selection_reaches_worker_unchanged(self):
  import urllib.parse
  for selection in [{'0':['signature']},{'1':['mvs']},{'0':['signature'],'1':['mvs']}]:
   with patch.object(server,'launch_document_check_job',return_value=True) as launch:
    status,raw=self.request('/api/applications/pending/verify-documents/start?selection='+urllib.parse.quote(json.dumps(selection)));self.assertEqual(status,202,raw);self.assertEqual(launch.call_args.args[2],selection)
 def test_locked_rows_block_new_checks_but_saved_results_are_readable(self):
  with patch.object(server,'launch_document_check_job') as launch:
   for sid in ['admitted','rejected']:
    status,_=self.request('/api/applications/'+sid+'/verify-documents/start');self.assertEqual(status,409)
   launch.assert_not_called()
 def test_csv_get_post_explicit_and_legacy_versions(self):
  with patch.object(server,'supplier_edr_export_csv',return_value=b'fixture') as export:
   for suffix,expected in [('', '1'),('&csv_version=2','2')]:
    status,raw=self.request('/api/supplier-edr-export?type=ALL&mode=selected&codes=12345678'+suffix);self.assertEqual(status,200,raw);self.assertEqual(export.call_args.kwargs['csv_version'],expected)
   for version in [None,'2']:
    body={'supplier_codes':['12345678']}
    if version is not None:body['csv_version']=version
    status,raw=self.request('/api/supplier-edr-export','POST',body);self.assertEqual(status,200,raw);self.assertEqual(export.call_args.kwargs['csv_version'],version or '1')
   status,_=self.request('/api/supplier-edr-export?type=ALL&csv_version=3');self.assertEqual(status,400)
   status,_=self.request('/api/supplier-edr-export','POST',{'supplier_codes':['12345678'],'csv_version':'3'});self.assertEqual(status,400)
 def test_csv_preserves_production_viewer_read_access(self):
  status,_=self.request('/api/supplier-edr-export?type=ALL',role='viewer');self.assertEqual(status,200)
