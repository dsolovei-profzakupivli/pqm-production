"""Narrow scenario projection child; exact files and immutable parent contracts."""
import ast,copy,hashlib,json,unittest
from pathlib import Path
import test_production_ui_release_integrity as guard
ROOT=Path(__file__).resolve().parent
MANIFEST_SHA='fe87e329ff5b92d062dfa1bfa1ca77f671d0ddefd1e58742b2be4aaf391b07c1'
class ScenarioProjectionIntegrityTests(unittest.TestCase):
 def test_exact_child_and_unchanged_historical_contracts(self):
  c=guard.SCENARIO_VARIANT;parent=guard.scenario_parent_root()
  self.assertEqual(c['baseline'],'7af6ed16861b87fa87fc5c5243d1ce86ae71bb29')
  self.assertEqual(guard.matching_variant(ROOT),c)
  self.assertEqual(guard.matching_variant(parent),guard.PREVIEW_GATE_VARIANT)
  self.assertEqual(hashlib.sha256((ROOT/'validation/production_scenario_projection_integrity_v1.json').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),MANIFEST_SHA)
  for name in ['production_ui_baseline_contract.json','production_dst_hotfix_integrity_v1.json','production_dst_hotfix_integrity_v2.json','production_declension_preview_integrity_v1.json','production_declension_preview_integrity_v2.json']:
   self.assertEqual((ROOT/'validation'/name).read_bytes().replace(b'\r\n',b'\n'),(parent/'validation'/name).read_bytes().replace(b'\r\n',b'\n'),name)
  for name in ['test_production_ui_release_integrity.py','test_production_declension_preview_integrity.py']:
   def classes(p):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text(encoding='utf-8-sig')).body if isinstance(n,ast.ClassDef)}
   self.assertEqual(classes(ROOT/name),classes(parent/name),name)
 def test_all_mutations_partial_extra_and_forged_contracts_rejected(self):
  c=guard.SCENARIO_VARIANT
  for name in c['files']:
   data=(ROOT/name).read_bytes()
   with self.subTest(file=name):self.assertFalse(guard.variant_matches(ROOT,c['files'],variant=c,overrides={name:bytes([data[0]^1])+data[1:]}))
  for files in [set(c['files'])-{'app.js'},set(c['files'])|{'unexpected.py'}]:self.assertFalse(guard.variant_matches(ROOT,files,variant=c))
  for field,value in [('name','arbitrary'),('baseline',guard.PREVIEW_GATE_VARIANT['baseline'])]:
   forged=copy.deepcopy(c);forged[field]=value;self.assertFalse(guard.variant_matches(ROOT,forged['files'],variant=forged))
  forged=copy.deepcopy(c);forged['files']['server.py']='0'*64;self.assertFalse(guard.variant_matches(ROOT,forged['files'],variant=forged))
 def test_legal_rules_and_other_components_exactly_unchanged(self):
  parent=guard.scenario_parent_root();old=guard.nodes((parent/'server.py').read_text(encoding='utf-8'));new=guard.nodes((ROOT/'server.py').read_text(encoding='utf-8'))
  changed={k for k in set(old)|set(new) if old.get(k)!=new.get(k)}
  self.assertEqual(changed,set(guard.SCENARIO_VARIANT['approved_changed_server_functions']))
  for name in ['violation_rules_engine','violation_scenario_summary','violation_decision_template_key','build_violation_decision_justification','build_procurement_context','generate_violation_protocol','save_violation_review','_scenario_report_fingerprint','_minimal_scenario_context','_scenario_context_from_card','_deadline_passed']:
   self.assertEqual(old[name],new[name],name)
  for name in ['declension.py','declension_overrides.py','violation_protocol_docx.py','protocol_docx.py','scheduler_runtime.py','nazk_workflow.py','operational_tasks.py','supplier_registry_integration.py','edr_sync_v2.py','sandbox_runtime.py','styles.css','index.html','table_widths_ui.js','theme.css','modules.css']:
   self.assertEqual((ROOT/name).read_bytes().replace(b'\r\n',b'\n'),(parent/name).read_bytes().replace(b'\r\n',b'\n'),name)
