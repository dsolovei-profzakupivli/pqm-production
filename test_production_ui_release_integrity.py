"""Immutable Production behavior guard; no application imports or runtime DB."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
CONTRACT=json.loads((ROOT/'validation/production_ui_baseline_contract.json').read_text())


def nodes(source):
    found={}
    for node in ast.parse(source).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            found[node.name]=ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.ClassDef):
            for child in node.body:
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    found[node.name+'.'+child.name]=ast.dump(child,include_attributes=False)
    return found


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class ProductionUiReleaseIntegrityTests(unittest.TestCase):
    def test_all_protected_server_functions_and_write_handlers_unchanged(self):
        source=nodes((ROOT/'server.py').read_text(encoding='utf-8'))
        self.assertEqual(digest({k:v for k,v in source.items()
                                if k not in CONTRACT['server_excluded_functions']}),
                         CONTRACT['server_protected_ast'])

    def test_operational_lifecycle_and_write_algorithms_unchanged(self):
        source=nodes((ROOT/'operational_tasks.py').read_text(encoding='utf-8'))
        excluded={'_task','list_tasks','_basis_date','task_ui_summary','qualification_ui_summary','amcu_target_ui_rows'}
        self.assertEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                         CONTRACT['operational_protected_ast'])

    def test_protected_files_exact_content(self):
        for name,expected in CONTRACT['protected_file_hashes'].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),expected)

    def test_existing_automation_callbacks_and_api_calls_unchanged(self):
        text=(ROOT/'app.js').read_text(encoding='utf-8')
        section=text[text.index('const schedulerJobLabels='):text.index('const persistedLocalRole=')]
        self.assertEqual(hashlib.sha256(section.encode()).hexdigest(),CONTRACT['automation_ui_sha256'])

    def test_no_sandbox_only_or_filtered_export_ui(self):
        for name in ('app.js','index.html','ui_improvements_boot.js','ui_final.js','ui_tz2.js'):
            text=(ROOT/name).read_text(encoding='utf-8')
            for token in ('/google-writer/','/admin/scheduler-schedules','/admin/background-jobs','supplierRegistryExcel'):
                self.assertNotIn(token,text,(name,token))
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        self.assertIn('Google / ЄДР',html)
        self.assertIn('id="productionAutomationCards"',html)


if __name__=='__main__':unittest.main()
