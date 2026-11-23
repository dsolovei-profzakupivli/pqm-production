"""Additional document history routes; original tests/pins remain unchanged."""
import os,sys,tempfile,subprocess,unittest
from pathlib import Path
from validation.production_documents_history import baseline_root
LEGACY_METHOD='test_manual_repeat_replaces_prior_manual_categories_not_background_experience'
def route_suite(suite, source):
 nodes=[]
 def visit(item):
  if isinstance(item,unittest.TestSuite):
   for child in item:visit(child)
  else:nodes.append(item)
 visit(suite)
 selected=[n for n in nodes if n.__class__.__module__.rsplit('.',1)[-1] in {'test_production_memory_integrity','test_production_experience_integrity','test_production_integrity_routes'} or (n.__class__.__module__.rsplit('.',1)[-1]=='test_production_memory_saved' and n._testMethodName==LEGACY_METHOD)]
 if not selected:return
 root=baseline_root(source)
 for node in selected:
  short=node.__class__.__module__.rsplit('.',1)[-1]
  if short=='test_production_memory_integrity':
   from validation.production_experience_history import route_suite as prior
   prior(unittest.TestSuite([node]),root)
  elif short=='test_production_experience_integrity':sys.modules[node.__class__.__module__].ROOT=root
  elif short=='test_production_integrity_routes':
   # Rebuild Stage 1 history from the attested Production parent, including
   # its original container runner; never inherit the current candidate runner.
   from validation.production_memory_history import route_suite as memory_routes
   memory_routes(unittest.TestSuite([node]),root)
  elif not getattr(node,'_production_documents_routed',False):
   # Run the unchanged legacy assertion with its actual original server in a
   # child process. No __file__ spoofing or shared-module configuration leaks.
   def run(result=None,node=node):
    result=result or unittest.TestResult();result.startTest(node)
    try:
     with tempfile.TemporaryDirectory(prefix='pqm-old-doc-check-') as folder:
      env=os.environ.copy();env.update(PQM_SANDBOX='0',PQM_ENV='local',PQM_DATA_DIR=folder,PQM_DB_PATH=folder+'/synthetic.sqlite3',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_NAZK_WORKFLOW='0',PQM_TEST_NETWORK_ISOLATION='1',PYTHONPATH=str(root/'validation/test_runtime'))
      name='validation.local_release_20260911.test_production_memory_saved.LastCompletedResultTests.'+LEGACY_METHOD
      completed=subprocess.run([sys.executable,'-B','-m','unittest',name,'-v'],cwd=root,env=env,check=False,timeout=90)
      if completed.returncode:raise AssertionError('Historical manual-check assertion failed: '+str(completed.returncode))
     result.addSuccess(node)
    except Exception:result.addFailure(node,sys.exc_info())
    finally:result.stopTest(node)
    return result
   node.run=run;node._production_documents_routed=True
