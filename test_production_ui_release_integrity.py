"""Immutable Production behavior guard; no application imports or runtime DB."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
CONTRACT=json.loads((ROOT/'validation/production_ui_baseline_contract.json').read_text())
ACCOUNT_BASELINE=json.loads((ROOT/'validation/personal_theme_account_baseline.json').read_text())
VARIANT=CONTRACT.get('approved_product_variants',{}).get('protocols_and_seasonal_cat')


def nodes(source):
    found={}
    for node in ast.parse(source).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            found[node.name]=ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.ClassDef):
            for child in node.body:
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    if node.name=='Handler' and child.name=='_do_PATCH':
                        # The user approved only /api/account. Reconstruct its
                        # original branch before checking the old whole-handler
                        # digest; every other write branch remains protected.
                        original=ast.parse(ACCOUNT_BASELINE['original_account_patch']).body[0]
                        matches=[i for i,item in enumerate(child.body)
                                 if isinstance(item,ast.If) and
                                 ast.dump(item.test)==ast.dump(original.test)]
                        if len(matches)!=1:raise AssertionError('Expected one account PATCH branch')
                        child.body[matches[0]]=original
                    found[node.name+'.'+child.name]=ast.dump(child,include_attributes=False)
    return found


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def variant_matches(root, changed_paths, *, overrides=None):
    """Accept only the complete, exact product manifest for the pinned baseline."""
    if not VARIANT or VARIANT.get('baseline')!='b433bcb290ca9a205910db54f0c9b77af4f02cc7':
        return False
    expected=VARIANT.get('files',{})
    if set(changed_paths)!=set(expected) or set(expected)!=set(VARIANT.get('files',{})):
        return False
    binary=set(VARIANT.get('binary_files',[]))
    overrides=overrides or {}
    for name,expected_sha in expected.items():
        try:
            data=overrides[name] if name in overrides else (root/name).read_bytes()
        except OSError:
            return False
        if name not in binary:
            data=data.replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=expected_sha:
            return False
    return True


class ProductionUiReleaseIntegrityTests(unittest.TestCase):
    def test_account_exception_does_not_hide_other_patch_changes(self):
        text=(ROOT/'server.py').read_text(encoding='utf-8')
        marker='    def _do_PATCH(self):\n'
        self.assertEqual(text.count(marker),1)
        altered=text.replace(marker,marker+'        unexpected_write_handler_change = True\n',1)
        source=nodes(altered)
        if VARIANT and variant_matches(ROOT,VARIANT['files']):
            excluded=set(CONTRACT['server_excluded_functions'])|set(VARIANT['server_variant_excluded_functions'])
            self.assertNotEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                                VARIANT['server_protected_ast'])
            return
        self.assertNotEqual(digest({k:v for k,v in source.items()
                                   if k not in CONTRACT['server_excluded_functions']}),
                            CONTRACT['server_protected_ast'])

    def test_all_protected_server_functions_and_write_handlers_unchanged(self):
        source=nodes((ROOT/'server.py').read_text(encoding='utf-8'))
        baseline_digest=digest({k:v for k,v in source.items()
                                if k not in CONTRACT['server_excluded_functions']})
        if baseline_digest==CONTRACT['server_protected_ast']:
            return
        self.assertIsNotNone(VARIANT,'No exact Production integrity variant is registered')
        self.assertTrue(variant_matches(ROOT,VARIANT['files']),
                        'server.py differs from baseline without an exact approved product manifest')
        excluded=set(CONTRACT['server_excluded_functions'])|set(VARIANT['server_variant_excluded_functions'])
        self.assertEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                         VARIANT['server_protected_ast'])

    def test_production_variant_is_bound_to_baseline_and_exact_manifest(self):
        self.assertEqual(CONTRACT['baseline'],'f2aacf88713a63b2d915d16af137c4133a5f1fd8')
        self.assertEqual(VARIANT['baseline'],'b433bcb290ca9a205910db54f0c9b77af4f02cc7')
        self.assertEqual(set(VARIANT['files']),{
            'app.js','assets/pqm-cat-no-hat.png','halloween.css','halloween.js',
            'halloween_motion.js','metadata/template_legacy_tokens.v1.json',
            'protocol_supplier_names.py','server.py','styles.css','template_catalog.py',
            'templates/violation_protocols/decline_individual_review.docx',
            'violation_protocol_docx.py',
        })
        self.assertTrue(variant_matches(ROOT,VARIANT['files']))
        self.assertFalse(variant_matches(ROOT,list(VARIANT['files'])[:-1]))
        self.assertFalse(variant_matches(ROOT,[*VARIANT['files'],'unapproved.py']))

    def test_production_variant_rejects_single_byte_changes_to_every_manifest_file(self):
        self.assertTrue(variant_matches(ROOT,VARIANT['files']))
        for name in VARIANT['files']:
            with self.subTest(name=name):
                data=(ROOT/name).read_bytes()
                changed=bytes([data[0]^1])+data[1:]
                self.assertFalse(variant_matches(ROOT,VARIANT['files'],overrides={name:changed}))

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
