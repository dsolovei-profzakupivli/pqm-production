"""Additive current policy pins; all prior contracts remain immutable."""
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from validation.sandbox_integrity_routes import digest
ROOT=Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
MANIFEST_SHA256='9938e1c5186c3e33fea327ae1b39097d1f2c43f8dcd81ae3986eaf085ca5d828'

class ExperienceIntegrityTests(unittest.TestCase):
    def manifest(self):
        raw=(ROOT/'validation/sandbox_experience_policy_v1.json').read_bytes()
        self.assertEqual(digest(raw,'manifest.json'),MANIFEST_SHA256);return json.loads(raw)
    def test_exact_current_pins_and_negative_mutations(self):
        for name,expected in self.manifest()['current_files'].items():
            raw=(ROOT/name).read_bytes();self.assertEqual(digest(raw,name),expected,name)
            for changed in (raw+b'X',raw[:-1],bytes([raw[0]^1])+raw[1:]):self.assertNotEqual(digest(changed,name),expected,name)
    def test_all_historical_and_unrelated_inputs_unchanged(self):
        manifest=self.manifest()
        for name,expected in manifest['unchanged_files'].items():self.assertEqual(digest((ROOT/name).read_bytes(),name),expected,name)
        for name in ['app.js','runtime_memory.py','supplier_registry_integration.py','scheduler_runtime.py','sandbox_eds.py','sandbox_runtime.py','google_writer_execution.py','validation/sandbox_functionality_repair_v1.json','validation/sandbox_functionality_repair_v2.json']:
            self.assertIn(name,manifest['unchanged_files'])
    def test_exact_prior_snapshot_and_unchanged_independent_server_functions(self):
        from validation import sandbox_experience_history as history
        previous,index=history.previous_root(ROOT)
        self.assertEqual(index['parent'],'f0cd9008e821e8edd3ae18783e649925f4ecf610');self.assertFalse((previous/'.git').exists())
        def functions(path):return {n.name:ast.dump(n) for n in ast.parse(path.read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        old,new=functions(previous/'server.py'),functions(ROOT/'server.py')
        allowed={'_store_document_check_result','_schedule_contract_experience_retry','contract_experience_worker','_sandbox_experience_scope_worker','enqueue_contract_experience_search','main'}
        self.assertEqual({name for name in old if old[name]!=new[name]},allowed)
        before,after=functions(previous/'background_jobs.py'),functions(ROOT/'background_jobs.py')
        for name,value in before.items():self.assertEqual(value,after[name],name)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/history.ARCHIVE;file.parent.mkdir(parents=True);raw=bytearray((ROOT/history.ARCHIVE).read_bytes());raw[-1]^=1;file.write_bytes(raw)
            with self.assertRaisesRegex(AssertionError,'archive changed'):history.previous_root(tmp)

if __name__=='__main__':unittest.main()
