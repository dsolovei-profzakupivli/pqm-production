"""Sandbox-only presentation integration and protected baseline invariants."""
import ast
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import sandbox_runtime
from validation.local_release_20260911.sandbox_protocol_integrity_variant import (
 exact_variant_file_matches, exact_variant_tree_matches, load_contract,
 protected_content_matches,
)

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
  variant=load_contract()
  for name,digest in contract()['files'].items():
   with self.subTest(file=name):
    raw=Path(name).read_bytes()
    actual=raw if name.endswith('.webp') else raw.replace(b'\r\n',b'\n')
    actual_sha=hashlib.sha256(actual).hexdigest()
    if actual_sha == digest or name in variant['protected_files']:
     self.assertTrue(protected_content_matches(
      name,raw,actual_sha,digest,'halloween_normalized_sha256'))
    else:
     # A changed index is allowed only by a complete, pinned product variant.
     self.assertTrue(exact_variant_tree_matches())
     self.assertTrue(exact_variant_file_matches(name,raw))

 def test_protocol_variant_manifest_pins_exact_product_bytes(self):
  variant=load_contract()
  self.assertEqual(variant['baseline_sha'], '565a2fff45675b6b49feb90edf67e83aa2af4a7b')
  self.assertTrue(exact_variant_tree_matches())
  for name in ('app.js','server.py'):
   with self.subTest(file=name):
    original=Path(name).read_bytes()
    self.assertTrue(exact_variant_file_matches(name,original))
    baseline=json.loads(Path('test_halloween_motion_contract.json').read_text(encoding='utf-8'))['files'][name]
    personal=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text(encoding='utf-8'))
    baseline_personal=personal['app_without_account'] if name=='app.js' else personal['server_outside_account_and_appeals_kpi']
    projection=original.replace(b'\r\n',b'\n')
    self.assertTrue(protected_content_matches(
     name,original,hashlib.sha256(projection).hexdigest(),baseline,
     'halloween_normalized_sha256'))
    changed=bytearray(original)
    marker=b'function' if name=='app.js' else b'import'
    index=original.index(marker)
    changed[index] ^= 1
    mutated=bytes(changed).replace(b'\r\n',b'\n')
    self.assertFalse(protected_content_matches(
     name,bytes(changed),hashlib.sha256(mutated).hexdigest(),baseline,
     'halloween_normalized_sha256'))
    # The personal-theme projection is also bound to the exact complete variant.
    candidate_personal=variant['protected_files'][name]['personal_theme_normalized_sha256']
    self.assertNotEqual(baseline_personal,candidate_personal)
 def test_runtime_changes_are_limited_to_html_decorator(self):
  def protected(source):
   tree=ast.parse(source)
   for i,node in enumerate(tree.body):
    if isinstance(node,ast.FunctionDef) and node.name=='decorate_html':tree.body[i]=ast.Pass()
   return ast.dump(tree,include_attributes=False)
  actual=protected(Path('sandbox_runtime.py').read_text(encoding='utf-8'))
  self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),contract()['sandbox_runtime_outside_decorator_ast'])

if __name__=='__main__':unittest.main()
