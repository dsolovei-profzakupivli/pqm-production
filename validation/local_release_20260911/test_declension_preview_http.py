"""Run the HTTP/DOCX fixture in its own process, without global suite side effects."""
from pathlib import Path
import os,subprocess,sys,unittest

class DeclensionPreviewHttpIntegration(unittest.TestCase):
 def test_preview_roles_saved_forms_and_new_docx(self):
  root=Path(__file__).resolve().parent
  if not (root/'app.js').exists():root=Path(__file__).resolve().parents[2]
  env={**os.environ,'PQM_TEST_NETWORK_ISOLATION':'1','PYTHONPATH':str(root/'validation/test_runtime')+os.pathsep+str(root)}
  result=subprocess.run([sys.executable,'-X','utf8','-B',str(root/'validation/declension_preview_http.py')],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  self.assertIn('Ran 9 tests',result.stderr);self.assertIn('\nOK\n',result.stderr)
  self.assertNotIn('Traceback (most recent call last)',result.stderr)
