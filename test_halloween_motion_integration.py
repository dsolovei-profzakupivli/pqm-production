"""Sandbox-only presentation integration and protected baseline invariants."""
import ast
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import sandbox_runtime

BASE='8fa52a62641f80bb322de177a76a98bf92ce3ecb'
def contract():
 data=json.loads(Path('test_halloween_motion_contract.json').read_text(encoding='utf-8'))
 assert data['baseline']==BASE
 return data
class HalloweenMotionIntegrationTests(unittest.TestCase):
 def test_inclusion_only_in_sandbox_and_after_existing_decorations(self):
  raw=Path('index.html').read_bytes()
  with patch.dict(os.environ,PQM_SANDBOX='1'):sandbox=sandbox_runtime.decorate_html(raw).decode()
  with patch.dict(os.environ,PQM_SANDBOX='0'):other=sandbox_runtime.decorate_html(raw).decode()
  for token in ['halloween_motion.js','halloween_motion.css']:
   self.assertEqual(sandbox.count(token),1);self.assertNotIn(token,other);self.assertNotIn(token,raw.decode())
  self.assertLess(sandbox.index('src="halloween.js"'),sandbox.index('src="halloween_motion.js"'))
  self.assertIn("if(root.dataset.pqmEnvironment!=='sandbox')return;",Path('halloween_motion.js').read_text())
 def test_original_artwork_themes_and_business_files_equal_live_baseline(self):
  for name,digest in contract()['files'].items():
   with self.subTest(file=name):
    actual=Path(name).read_bytes()
    if not name.endswith('.webp'):actual=actual.replace(b'\r\n',b'\n')
    self.assertEqual(hashlib.sha256(actual).hexdigest(),digest)
 def test_runtime_changes_are_limited_to_html_decorator(self):
  def protected(source):
   tree=ast.parse(source)
   for i,node in enumerate(tree.body):
    if isinstance(node,ast.FunctionDef) and node.name=='decorate_html':tree.body[i]=ast.Pass()
   return ast.dump(tree,include_attributes=False)
  actual=protected(Path('sandbox_runtime.py').read_text(encoding='utf-8'))
  self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),contract()['sandbox_runtime_outside_decorator_ast'])

if __name__=='__main__':unittest.main()
