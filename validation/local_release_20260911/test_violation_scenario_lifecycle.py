"""Projection lifecycle regression: disposable synthetic DB, canonical summary unchanged."""
import copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import server
import test_violation_scenario_context_cache as cache_tests
class ScenarioProjectionLifecycleTests(unittest.TestCase):
 setUp=cache_tests.ViolationScenarioContextCacheTests.setUp
 tearDown=cache_tests.ViolationScenarioContextCacheTests.tearDown
 _stored_inputs=cache_tests.ViolationScenarioContextCacheTests._stored_inputs
 def _context(self, modified=None, observed=None):
  value=cache_tests.ViolationScenarioContextCacheTests._context(self,modified,observed)
  value['contract_deadline']='2026-10-01'
  value['contract_deadline_expired']=server._deadline_passed(value['contract_deadline'])
  return value
 def listing(self):return next(x for x in server.list_violation_reports({'page':['1'],'size':['10']})['items'] if x['id']==self.report['id'])
 def detail(self):
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())):
   return server.violation_report_detail(self.report['id'],refresh=False)
 def state(self):
  with server.db() as c:return {t:[tuple(x) for x in c.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ['violation_reports','violation_report_reviews','violation_report_review_events','violation_scenario_context_snapshots','violation_winner_decision_snapshots','violation_scenario_basis']}
 def test_01_new_report_sync_populates_list_without_card(self):
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())),patch.object(server,'violation_report_detail',side_effect=AssertionError('must not warm cards')):
   result=server._refresh_violation_scenario_projections()
  self.assertEqual(result,{'attempted':1,'refreshed':1});self.assertTrue(self.listing()['scenario_summary'])
 def test_detail_only_adds_cache_and_basis(self):
  self.assertEqual(self.listing()['scenario_summary'],'');before=self.state();detail=self.detail();after=self.state()
  self.assertTrue(detail['scenario_summary']);self.assertEqual(self.listing()['scenario_summary'],detail['scenario_summary'])
  self.assertNotEqual(before['violation_scenario_context_snapshots'],after['violation_scenario_context_snapshots'])
  for t in before:
   if t not in {'violation_scenario_context_snapshots','violation_scenario_basis'}:self.assertEqual(before[t],after[t],t)
 def test_02_save_review_refreshes_cache_with_no_need_to_reopen(self):
  self.detail()
  with patch.object(server,'_fresh_violation_report',return_value=self.report),patch.object(server,'require_local_violation_report_owned'),patch.object(server,'require_owned_violation_report'),patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())):
   data=server.save_violation_review(self.report['id'],{'internal_decision':'decline','contract_deadline_extended':True},'Synthetic officer')
  self.assertTrue(data['scenario_summary']);self.assertEqual(self.listing()['scenario_summary'],data['scenario_summary'])
 def test_03_sync_refreshes_invalidated_projection_without_card(self):
  self.detail();before=self.listing()['scenario_summary'];updated=copy.deepcopy(self.report);updated['dateModified']='2026-10-21T10:00:00+03:00'
  with patch.object(server,'_resolve_violation_tender',return_value=('UA-TEST','')):server.save_violation_report(updated)
  self.assertTrue(before);self.assertEqual(self.listing()['scenario_summary'],'')
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())):server._refresh_violation_scenario_projections()
  self.assertTrue(self.listing()['scenario_summary'])
 def test_04_expired_cache_uses_verified_facts_without_writes(self):
  self.detail();real_time_ns=server.time.time_ns
  with patch.object(server.time,'time_ns',return_value=real_time_ns()+25*3600*1_000_000_000):
   before=self.state();row=self.listing();self.assertTrue(row['scenario_summary']);self.assertEqual(row['scenario_context_source'],'saved_facts');self.assertEqual(self.state(),before)
  self.assertTrue(self.detail()['scenario_summary']);self.assertTrue(self.listing()['scenario_summary'])
 def test_05_completion_atomically_projects_final_inputs(self):
  self.detail()
  with patch.object(server,'_fresh_violation_report',return_value=self.report),patch.object(server,'require_local_violation_report_owned'),patch.object(server,'require_owned_violation_report'),patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())),patch.object(server,'merged_review_requires_discrepancy',return_value=False),patch.object(server,'violation_deadline_control',return_value={'supplier_ready':True}):
   server.complete_violation_review(self.report['id'],'Synthetic officer',{'internal_decision':'decline','contract_deadline_extended':True})
  self.assertTrue(self.listing()['scenario_summary'])
  before=self.state();self.assertTrue(self.detail()['scenario_summary']);after=self.state()
  self.assertEqual(before['violation_report_reviews'],after['violation_report_reviews']);self.assertEqual(before['violation_report_review_events'],after['violation_report_review_events'])
 def test_06_list_is_readonly_even_when_cache_missing(self):
  before=self.state();self.listing();self.assertEqual(self.state(),before)
 def test_07_protocol_fields_do_not_invalidate_scenario_fingerprint(self):
  report,review=self._stored_inputs();base=server._scenario_report_fingerprint(report,server._review_dict(review));changed={**review,'generated_protocol_filename':'synthetic.docx','protocol_number':'810','protocol_date':'2026-10-27','review_status':'reviewed','completed_at':'2026-10-27T10:00:00Z'};self.assertEqual(base,server._scenario_report_fingerprint(report,server._review_dict(changed)))
 def test_08_generate_and_sync_preserve_protocol_and_refresh_scenario(self):
  with server.db() as con:con.execute("UPDATE violation_report_reviews SET internal_decision='warning',customer_verified_short_name='Синтетичний замовник',assigned_officer='Синтетична УО' WHERE report_id=?",(self.report['id'],))
  folder=Path(self.temp.name)/'protocols'
  def renderer(_kind,path,*args,**kwargs):path.write_bytes(b'synthetic-document-unchanged')
  with patch.object(server,'_fresh_violation_report',return_value=self.report),patch.object(server,'require_local_violation_report_owned'),patch.object(server,'require_owned_violation_report'),patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:{**copy.deepcopy(self._context()),'tender_date_published':'2026-10-01','winner_selected_at':'2026-10-02'}),patch.object(server,'PROTOCOLS_DIR',folder),patch.object(server,'build_violation_protocol_docx',side_effect=renderer),patch.object(server,'violation_protocol_readiness',return_value={'ready':True,'protocol_number':'810','protocol_date':'2026-10-27','protocol_type':'warning'}):
   generated=server.generate_violation_protocol(self.report['id'],{'protocol_number':'810','protocol_date':'2026-10-27'})
   name=folder/generated['filename'];before=name.read_bytes();row=self.listing();self.assertTrue(row['scenario_summary']);self.assertTrue(row['protocol_summary'])
   updated=copy.deepcopy(self.report);updated['dateModified']='2026-10-21T10:00:00+03:00'
   with patch.object(server,'_resolve_violation_tender',return_value=('UA-TEST','')):server.save_violation_report(updated)
   row=self.listing();self.assertTrue(row['protocol_summary']);self.assertEqual(row['scenario_summary'],'');self.assertEqual(name.read_bytes(),before)
   server._refresh_violation_scenario_projections();row=self.listing();self.assertTrue(row['protocol_summary']);self.assertTrue(row['scenario_summary']);self.assertEqual(name.read_bytes(),before)
 def test_cleared_cache_recovers_without_network_or_write(self):
  self.detail()
  with server.db() as con:con.execute('DELETE FROM violation_scenario_context_snapshots')
  before=self.state()
  with patch.object(server,'api_get',side_effect=AssertionError('list must never fetch')):
   self.assertTrue(self.listing()['scenario_summary'])
  self.assertEqual(before,self.state())
 def test_corrupt_or_wrong_revision_basis_is_rejected(self):
  self.detail()
  with server.db() as con:
   con.execute('DELETE FROM violation_scenario_context_snapshots')
   con.execute("UPDATE violation_scenario_basis SET calendar_deadline='2026-12-31'")
  self.assertEqual(self.listing()['scenario_summary'],'')
 def test_old_context_cannot_replace_basis_or_cache(self):
  self.detail();before=self.state();report,review=self._stored_inputs()
  older=self._context((datetime.now(timezone.utc)-timedelta(hours=3)).isoformat())
  server._save_violation_scenario_context_snapshot(report,review,older)
  self.assertEqual(before,self.state())
 def test_no_context_never_fabricates_scenario(self):
  with patch.object(server,'build_procurement_context',return_value={'available':False}):
   result=server._refresh_violation_scenario_projections()
  self.assertEqual(result,{'attempted':1,'refreshed':0});self.assertEqual(self.listing()['scenario_summary'],'')
 def test_completion_failure_rolls_back_review_and_history(self):
  fixed_context=copy.deepcopy(self._context())
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(fixed_context)):
   server.violation_report_detail(self.report['id'],refresh=False)
  before=self.state();report,review=self._stored_inputs()
  fingerprint=server._scenario_report_fingerprint(report,server._review_dict(review));failures=[]
  def fail_after_merge(con,candidate,context):
   if candidate['input_fingerprint']==fingerprint:return
   self.assertEqual(con.execute('SELECT contract_deadline_extended FROM violation_report_reviews WHERE report_id=?',(self.report['id'],)).fetchone()[0],1)
   self.assertGreater(con.execute('SELECT COUNT(*) FROM violation_report_review_events').fetchone()[0],len(before['violation_report_review_events']))
   failures.append(True)
   raise RuntimeError('synthetic post-merge write failure')
  with patch.object(server,'_fresh_violation_report',return_value=self.report),patch.object(server,'require_local_violation_report_owned'),patch.object(server,'require_owned_violation_report'),patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(fixed_context)),patch.object(server,'merged_review_requires_discrepancy',return_value=False),patch.object(server,'violation_deadline_control',return_value={'supplier_ready':True}),patch.object(server,'_save_scenario_basis',side_effect=fail_after_merge):
   with self.assertRaisesRegex(RuntimeError,'synthetic post-merge write failure'):
    server.complete_violation_review(self.report['id'],'Synthetic officer',{'internal_decision':'decline','contract_deadline_extended':True})
  self.assertEqual(failures,[True]);self.assertEqual(before,self.state())
 def test_refresh_is_bounded_and_ignores_foreign_reports(self):
  with patch.object(server,'_resolve_violation_tender',return_value=('UA-TEST','')):
   for i in range(4):
    row=copy.deepcopy(self.report);row['id']='new-'+str(i);row['violationReportID']='UA-D-2026-10-26-00000'+str(i+2);server.save_violation_report(row)
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())) as build:
   result=server._refresh_violation_scenario_projections(limit=2,preferred_ids=['new-3'])
  self.assertEqual(result,{'attempted':2,'refreshed':2});self.assertEqual(build.call_count,2);self.assertEqual(build.call_args_list[0].args[0]['id'],'new-3')
  with patch.object(server,'violation_report_owned_by_pqm',return_value=False),patch.object(server,'build_procurement_context',side_effect=AssertionError('foreign')):
   self.assertEqual(server._refresh_violation_scenario_projections(),{'attempted':0,'refreshed':0})
 def test_calendar_expiry_reuses_canonical_deadline_helper(self):
  self.detail()
  with patch.object(server,'_deadline_passed',return_value=False) as deadline:
   self.assertIn('ще не сплив',self.listing()['scenario_summary']);deadline.assert_called_once_with('2026-10-01')

 def test_full_sync_new_report_and_supplier_statement_without_detail(self):
  updated=copy.deepcopy(self.report);updated['dateModified']='2026-10-27T09:00:00+02:00'
  updated['defendantStatements']=[]
  for is_new in [True,False]:
   if is_new:
    updated['id']='new-unopened-report';updated['violationReportID']='UA-D-2026-10-27-000009'
   else:
    updated['defendantStatements']=[{'id':'statement-one','description':'Оновлене пояснення'}]
    updated['dateModified']='2026-10-27T10:00:00+02:00'
   with patch.object(server,'paginated_pages',return_value=[[updated]]),patch.object(server,'api_get',return_value={'data':updated}),patch.object(server,'_resolve_violation_tender',return_value=('UA-SYNTHETIC','')),patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())),patch.object(server,'violation_report_detail',side_effect=AssertionError('No card warming')),patch.object(server,'rebuild_operational_tasks'):
    server.sync_violation_reports_worker(claimed=True)
   rows=server.list_violation_reports({'page':['1'],'size':['10']})['items'];row=next(x for x in rows if x['id']=='new-unopened-report')
   self.assertEqual(len(row['defendant_statements']),0 if is_new else 1)
   self.assertIn('пояснення постачальника — '+('відсутні' if is_new else 'надані'),row['scenario_summary'])
 def test_explanation_period_expiry_keeps_scenario_available_without_detail(self):
  period_end=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
  with server.db() as con:con.execute("UPDATE violation_reports SET defendant_period_end=? WHERE id=?",(period_end,self.report['id']))
  with patch.object(server,'build_procurement_context',side_effect=lambda *a,**k:copy.deepcopy(self._context())),patch.object(server,'violation_report_detail',side_effect=AssertionError('No card warming')):
   server._refresh_violation_scenario_projections()
  first=self.listing();self.assertTrue(first['scenario_summary']);self.assertFalse(server.violation_deadline_control(first)['supplier_ready'])
  real_datetime=server.datetime
  class AfterDeadline(real_datetime):
   @classmethod
   def now(cls,tz=None):
    value=real_datetime.now(timezone.utc)+timedelta(days=3)
    return value.astimezone(tz) if tz else value.replace(tzinfo=None)
  real_time=server.time.time_ns
  with patch.object(server,'datetime',AfterDeadline),patch.object(server.time,'time_ns',return_value=real_time()+3*24*3600*1_000_000_000),patch.object(server,'api_get',side_effect=AssertionError('GET list network')):
   later=self.listing();self.assertTrue(later['scenario_summary']);self.assertEqual(later['defendant_statements'],[]);self.assertTrue(server.violation_deadline_control(later)['supplier_ready'])
  self.assertEqual(first['scenario_summary'],later['scenario_summary'])
 def test_list_sqlite_query_only_and_no_internal_basis_exposed(self):
  from contextlib import contextmanager
  self.detail();original=server.db
  @contextmanager
  def readonly_db():
   with original() as con:
    con.execute('PRAGMA query_only=ON')
    yield con
  with patch.object(server,'db',readonly_db),patch.object(server,'api_get',side_effect=AssertionError('GET list network')):
   row=self.listing()
  self.assertTrue(row['scenario_summary'])
  for field in ['raw_json','basis_hash','snapshot_json','context_json']:
   self.assertNotIn(field,row)
 def test_ui_scenario_and_supplier_statement_regression(self):
  import subprocess
  subprocess.run(['node','validation/scenario_projection_ui.cjs'],check=True,timeout=30)
