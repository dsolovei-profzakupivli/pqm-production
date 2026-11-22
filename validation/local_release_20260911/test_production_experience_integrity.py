"""Actual Production candidate v2: queue policy, mutations, original manifests."""
import ast,hashlib,json,copy
from pathlib import Path
import unittest
import zipfile

ROOT=Path.cwd()
PIN='1559501d8c79b6026d1491f570d053c87835ba1ad725111a3779ac86fd867d6b'
def sha(raw,name):
    if Path(name).suffix in {'.py','.js','.cjs','.json','.html','.css','.md','.yml'}:raw=raw.replace(b'\r\n',b'\n')
    return hashlib.sha256(raw).hexdigest()

class ProductionExperienceIntegrity(unittest.TestCase):
    def manifest(self):
        raw=(ROOT/'validation/production_memory_selective_v2.json').read_bytes()
        self.assertEqual(sha(raw,'manifest.json'),PIN)
        return json.loads(raw)

    def test_actual_files_and_exact_negative_mutations(self):
        for name,expected in self.manifest()['files'].items():
            with self.subTest(file=name):
                raw=(ROOT/name).read_bytes();self.assertEqual(sha(raw,name),expected)
                self.assertNotEqual(sha(raw+b'X',name),expected)
                self.assertNotEqual(sha(raw[:-1],name),expected)
                changed=bytearray(raw);changed[len(changed)//2]^=1
                self.assertNotEqual(sha(changed,name),expected)

    def test_historical_contracts_non_ui_files_and_production_processes_unchanged(self):
        manifest=self.manifest()
        for group in ['historical_manifests','unchanged_baseline_files']:
            for name,expected in manifest[group].items():
                self.assertEqual(sha((ROOT/name).read_bytes(),name),expected,name)
        source=(ROOT/'server.py').read_text(encoding='utf-8-sig')
        functions={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
                   for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        for name,expected in manifest['unchanged_server_functions'].items():
            self.assertEqual(functions.get(name),expected,name)
        source=(ROOT/'supplier_registry_integration.py').read_text(encoding='utf-8-sig')
        functions={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
                   for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        for name,expected in manifest['unchanged_registry_functions'].items():
            self.assertEqual(functions.get(name),expected,name)

    def test_search_worker_criteria_and_body_unchanged_except_ownership_release(self):
        with zipfile.ZipFile(ROOT/'validation/fixtures/production_memory_parent_a53234f.zip') as archive:
            baseline=ast.parse(archive.read('server.py').decode('utf-8-sig'))
        current=ast.parse((ROOT/'server.py').read_text(encoding='utf-8-sig'))
        def body(tree,name):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        old,new=body(baseline,'contract_experience_worker'),body(current,'contract_experience_worker')
        # Only two explicit process-budget annotations surround the unchanged
        # search/persistence criteria. Actual bytes are pinned above as well.
        removed=[]
        class WithoutRetryMetadata(ast.NodeTransformer):
            def visit_If(self,node):
                if ast.unparse(node.test)=='CONTRACT_EXPERIENCE_QUEUE is not None':
                    removed.append(node)
                    return None
                return self.generic_visit(node)
        new=WithoutRetryMetadata().visit(copy.deepcopy(new))
        self.assertEqual(len(removed),2)
        self.assertEqual(ast.dump(ast.Module(body=old.body[0].body,type_ignores=[]),include_attributes=False),
                         ast.dump(ast.Module(body=new.body[0].body,type_ignores=[]),include_attributes=False))
        self.assertEqual(ast.dump(body(baseline,'_stored_experience_is_fresh'),include_attributes=False),
                         ast.dump(body(current,'_stored_experience_is_fresh'),include_attributes=False))
        old_constants={n.targets[0].id:ast.dump(n.value,include_attributes=False) for n in baseline.body
                       if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
        new_constants={n.targets[0].id:ast.dump(n.value,include_attributes=False) for n in current.body
                       if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
        for name in ['CONTRACT_EXPERIENCE_REQUEST_INTERVAL','CONTRACT_EXPERIENCE_CACHE_TTL',
                     'CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL','CONTRACT_EXPERIENCE_ALGORITHM_VERSION',
                     'CONTRACT_EXPERIENCE_EXACT_PAGE_LIMIT','CONTRACT_EXPERIENCE_FALLBACK_PAGE_LIMIT',
                     'CONTRACT_EXPERIENCE_MAX_CANDIDATES','CONTRACT_EXPERIENCE_EXECUTOR',
                     'CONTRACT_EXPERIENCE_RETRY_DELAY','CONTRACT_EXPERIENCE_MAX_BACKGROUND_RETRIES']:
            self.assertEqual(old_constants[name],new_constants[name],name)
