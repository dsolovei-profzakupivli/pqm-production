"""Actual Production documents package; immutable memory/history and narrow scope."""
import ast,hashlib,json,os,re,subprocess,unittest,zipfile,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from validation import production_documents_history as history
ROOT=Path(os.environ.get('PQM_PRODUCTION_DOCUMENTS_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
PIN='da90815f4f843bf8da88d60d92553501ea708fd13a8c4905b67c0934f5ab0883'
def digest(raw):
 if b'\0' not in raw:
  try:raw.decode('utf8');raw=raw.replace(b'\r\n',b'\n')
  except UnicodeDecodeError:pass
 return hashlib.sha256(raw).hexdigest()
def functions(text):return {n.name:n for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
class ProductionDocumentsIntegrity(unittest.TestCase):
 def manifest(self):
  raw=(ROOT/'validation/production_documents_release_v1.json').read_bytes();self.assertEqual(digest(raw),PIN);return json.loads(raw)
 def baseline(self,name):
  with zipfile.ZipFile(ROOT/history.ARCHIVE) as archive:return archive.read('files/'+name).decode('utf-8-sig').replace('\r\n','\n')
 def test_candidate_files_and_historical_hashes(self):
  manifest=self.manifest()
  for name,pin in {**manifest['files'],**manifest['protected']}.items():
   with self.subTest(file=name):
    raw=(ROOT/name).read_bytes();self.assertEqual(digest(raw),pin);self.assertNotEqual(digest(raw+b'X'),pin)
 def test_delivered_runtime_matches_current_contract(self):
  import server
  root=Path(server.__file__).resolve().parent;manifest=self.manifest()
  for name in manifest['runtime']:
   self.assertEqual(digest((root/name).read_bytes()),manifest['files'][name],name)
 def test_server_changes_are_limited_and_memory_functions_unchanged(self):
  old=self.baseline('server.py');current=(ROOT/'server.py').read_text(encoding='utf8');before=functions(old);after=functions(current)
  allowed=set(self.manifest()['allowed_server_functions'])
  self.assertEqual(set(before)-set(after),set())
  for name in before:
   if name not in allowed:self.assertEqual(ast.dump(before[name]),ast.dump(after[name]),name)
  self.assertEqual(set(after)-set(before),{'document_check_summary_checks','_clarity_export_timestamp','_clarity_prozorro_status','_clarity_csv_version'})
  # Restoring the single approved category-base change reproduces all original
  # transaction, lock, retry and write behavior of the Production store.
  class StoreBase(ast.NodeTransformer):
   def visit_If(self,node):
    if isinstance(node.test,ast.Name) and node.test.id=='require_editable' and any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='base' for t in n.targets) for n in node.body):return ast.Assign(targets=[ast.Name(id='base',ctx=ast.Store())],value=ast.Name(id='existing',ctx=ast.Load()))
    return self.generic_visit(node)
  self.assertEqual(ast.dump(StoreBase().visit(before['_store_document_check_result'])),ast.dump(after['_store_document_check_result']))
 def test_app_changes_only_document_helpers_counter_and_explicit_csv(self):
  old=self.baseline('app.js');new=(ROOT/'app.js').read_text(encoding='utf8')
  names=['saveDocumentSelection','openDocs','openHistoryDocuments','renderBusinessRows','renderDocumentCheck','openSavedDocumentCheck','verifyDocuments','edrMonitoringExportUrl','exportSelectedEdrMonitoring']
  script="const {extractFunction}=require('./validation/function_test_source.cjs');const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));const result={old:{},current:{}};for(const n of input.names){result.old[n]=extractFunction(input.old,n);result.current[n]=extractFunction(input.current,n)}for(const n of ['documentDownloadLink','documentCheckSubtitle'])result.current[n]=extractFunction(input.current,n);process.stdout.write(JSON.stringify(result));"
  extracted=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps({'old':old,'current':new,'names':names}).encode(),cwd=ROOT))
  for name in names:
   old=old.replace(extracted['old'][name],'/* approved '+name+' */');new=new.replace(extracted['current'][name],'/* approved '+name+' */')
  for name in ['documentDownloadLink','documentCheckSubtitle']:new=new.replace(extracted['current'][name],'')
  new=new.replace("$('#edrMonitoringCsvVersion').onchange=()=>updateEdrMonitoringSelection();",'')
  new=new.replace('${PqmApplicationDocuments.groups(row).supplier.length}','${row.documents.length}')
  normalize=lambda text:'\n'.join(line.strip() for line in text.splitlines() if line.strip())
  self.assertEqual(normalize(old),normalize(new))
 def test_only_csv_handlers_change_and_schema_auth_scheduler_are_preserved(self):
  old=ast.parse(self.baseline('server.py'));new=ast.parse((ROOT/'server.py').read_text(encoding='utf8'))
  original=next(n for n in old.body if isinstance(n,ast.ClassDef) and n.name=='Handler');candidate=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
  def csv_branch(node):return isinstance(node,ast.If) and isinstance(node.test,ast.Compare) and any(isinstance(c,ast.Constant) and c.value=='/api/supplier-edr-export' for c in node.test.comparators)
  old_branches=[n for n in ast.walk(original) if csv_branch(n)];self.assertEqual(len(old_branches),2)
  iterator=iter(old_branches)
  class Restore(ast.NodeTransformer):
   def visit_If(self,node):return next(iterator) if csv_branch(node) else self.generic_visit(node)
  self.assertEqual(ast.dump(original),ast.dump(Restore().visit(candidate)))
 def test_rollback_runtime_is_baseline_plus_compatibility_only(self):
  with zipfile.ZipFile(ROOT/'validation/fixtures/production_documents_rollback_v1.zip') as archive:
   raw=archive.read('server.py');index=json.loads(archive.read('INDEX.json'));self.assertEqual(hashlib.sha256(raw).hexdigest(),index['server_sha256'])
  before=functions(self.baseline('server.py'));after=functions(raw.decode('utf8'))
  allowed={'document_check_category_summaries','current_document_check_result','merge_document_check_results','_store_document_check_result'}
  self.assertEqual(set(after)-set(before),{'document_check_summary_checks'})
  for name in before:
   if name not in allowed:self.assertEqual(ast.dump(before[name]),ast.dump(after[name]),name)
 def test_html_changes_only_documents_and_explicit_csv_control(self):
  old=self.baseline('index.html');new=(ROOT/'index.html').read_text(encoding='utf8')
  for id in ['docsDialog','documentCheckDialog']:
   pattern=r'<dialog\b(?=[^>]*\bid="'+id+r'")[^>]*>[\s\S]*?</dialog>'
   new=re.sub(pattern,lambda match:re.search(pattern,old).group(),new)
  new=re.sub(r'^  <(?:link rel="stylesheet" href="(?:application_documents_ui|document_check_ui).css"|script src="(?:application_documents_ui|document_check_ui).js"></script)>?\n','',new,flags=re.M)
  new=re.sub(r'^      <label>Формат CSV .*?</label>\n','',new,flags=re.M)
  self.assertEqual(old.strip(),new.strip())
 def test_legacy_assertion_route_runs_unchanged_and_failure_is_not_hidden(self):
  from validation import production_documents_routes as routes
  from validation.local_release_20260911 import test_production_memory_saved as original
  for code in [0,7]:
   case=original.LastCompletedResultTests(routes.LEGACY_METHOD);suite=unittest.TestSuite([case]);routes.route_suite(suite,ROOT)
   with patch.object(routes.subprocess,'run',return_value=SimpleNamespace(returncode=code)) as run:
    result=unittest.TestResult();suite.run(result);self.assertEqual(result.wasSuccessful(),code==0);self.assertEqual(run.call_args.kwargs['cwd'],history.baseline_root(ROOT))
    self.assertTrue(run.call_args.args[0][-2].endswith(routes.LEGACY_METHOD))
 def test_history_archive_is_pinned_and_wrong_transport_fails(self):
  self.assertEqual(hashlib.sha256((ROOT/history.ARCHIVE).read_bytes()).hexdigest(),history.PIN)
  root=history.baseline_root(ROOT);self.assertFalse((root/'.git').exists());self.assertEqual((root/'server.py').read_text(encoding='utf8'),self.baseline('server.py'))
 def test_runtime_file_allowlist(self):
  manifest=self.manifest();self.assertEqual(set(manifest['runtime']),{'app.js','index.html','server.py','application_documents_ui.js','application_documents_ui.css','document_check_ui.js','document_check_ui.css'})
