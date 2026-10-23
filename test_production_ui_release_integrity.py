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
FAILSAFE_VARIANT=CONTRACT.get('approved_product_variants',{}).get('protocols_and_seasonal_cat_css_failsafe')
UI_VARIANT=CONTRACT.get('approved_product_variants',{}).get('sandbox_ui_transfer_from_bddd5f6')
VARIANTS=[value for value in (VARIANT,FAILSAFE_VARIANT,UI_VARIANT) if value]


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


def variant_matches(root, changed_paths, *, overrides=None, variant=None):
    """Accept only the complete, exact product manifest for the pinned baseline."""
    variant=variant or VARIANT
    if not variant or variant.get('baseline') not in {
        'b433bcb290ca9a205910db54f0c9b77af4f02cc7',
        'f8cd1ded13864587e71f8904ee0bcfe24ec5d471',
    }:
        return False
    expected=variant.get('files',{})
    if set(changed_paths)!=set(expected) or set(expected)!=set(variant.get('files',{})):
        return False
    binary=set(variant.get('binary_files',[]))
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


def matching_variant(root):
    return next((variant for variant in VARIANTS
                 if variant_matches(root,variant.get('files',{}),variant=variant)),None)


class ProductionUiReleaseIntegrityTests(unittest.TestCase):
    def test_account_exception_does_not_hide_other_patch_changes(self):
        text=(ROOT/'server.py').read_text(encoding='utf-8')
        marker='    def _do_PATCH(self):\n'
        self.assertEqual(text.count(marker),1)
        altered=text.replace(marker,marker+'        unexpected_write_handler_change = True\n',1)
        source=nodes(altered)
        matched=matching_variant(ROOT)
        if matched:
            excluded=set(CONTRACT['server_excluded_functions'])|set(matched['server_variant_excluded_functions'])
            altered_sha=hashlib.sha256(altered.encode('utf-8').replace(b'\r\n',b'\n')).hexdigest()
            self.assertNotEqual(altered_sha,matched['files']['server.py'],
                                'Exact server.py manifest must reject edits inside variant-scoped handlers')
            if 'Handler._do_PATCH' in matched['server_variant_excluded_functions']:
                return
            self.assertNotEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                                matched['server_protected_ast'])
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
        matched=matching_variant(ROOT)
        self.assertIsNotNone(matched,'No exact Production integrity variant is registered')
        self.assertTrue(variant_matches(ROOT,matched['files'],variant=matched),
                        'server.py differs from baseline without an exact approved product manifest')
        excluded=set(CONTRACT['server_excluded_functions'])|set(matched['server_variant_excluded_functions'])
        self.assertEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                         matched['server_protected_ast'])

    def test_production_variant_is_bound_to_baseline_and_exact_manifest(self):
        self.assertEqual(CONTRACT['baseline'],'f2aacf88713a63b2d915d16af137c4133a5f1fd8')
        self.assertEqual(set(CONTRACT['approved_product_variants']),{
            'protocols_and_seasonal_cat','protocols_and_seasonal_cat_css_failsafe',
            'sandbox_ui_transfer_from_bddd5f6',
        })
        self.assertEqual(VARIANT['baseline'],'b433bcb290ca9a205910db54f0c9b77af4f02cc7')
        expected_files={
            'app.js','assets/pqm-cat-no-hat.png','halloween.css','halloween.js',
            'halloween_motion.js','metadata/template_legacy_tokens.v1.json',
            'protocol_supplier_names.py','server.py','styles.css','template_catalog.py',
            'templates/violation_protocols/decline_individual_review.docx',
            'violation_protocol_docx.py',
        }
        self.assertEqual(set(VARIANT['files']),expected_files)
        self.assertEqual(set(FAILSAFE_VARIANT['files']),expected_files)
        self.assertEqual(FAILSAFE_VARIANT['baseline'],VARIANT['baseline'])
        self.assertEqual(FAILSAFE_VARIANT['server_protected_ast'],VARIANT['server_protected_ast'])
        self.assertEqual(FAILSAFE_VARIANT['server_variant_excluded_functions'],VARIANT['server_variant_excluded_functions'])
        self.assertEqual(FAILSAFE_VARIANT['binary_files'],VARIANT['binary_files'])
        self.assertEqual(FAILSAFE_VARIANT['files'],{
            **VARIANT['files'],
            'halloween_motion.js':'1d552ed58cc480f79f8d10c8f1a05af3bb1da3a8e69aaf98ad0c3a748b75071c',
        })
        self.assertEqual(UI_VARIANT['baseline'],'f8cd1ded13864587e71f8904ee0bcfe24ec5d471')
        self.assertEqual(set(UI_VARIANT['files']),{
            'app.js','edr_sync_v2.py','history_columns.js','index.html','reference_directories.py','server.py',
            'styles.css','table_widths.py','table_widths_ui.js',
        })
        self.assertEqual(VARIANT['files']['halloween_motion.js'],'d3a4fcb7dc21beaf7f9a6c229533d2884419259eb74636962d85402170fa94d3')
        self.assertEqual(FAILSAFE_VARIANT['files']['halloween_motion.js'],'1d552ed58cc480f79f8d10c8f1a05af3bb1da3a8e69aaf98ad0c3a748b75071c')
        self.assertEqual(FAILSAFE_VARIANT['files'].keys(),VARIANT['files'].keys())

    def test_production_variant_rejects_single_byte_changes_to_every_manifest_file(self):
        self.assertTrue(variant_matches(ROOT,UI_VARIANT['files'],variant=UI_VARIANT))
        self.assertFalse(variant_matches(ROOT,list(UI_VARIANT['files'])[:-1],variant=UI_VARIANT))
        self.assertFalse(variant_matches(ROOT,[*UI_VARIANT['files'],'unapproved.py'],variant=UI_VARIANT))
        for name in UI_VARIANT['files']:
            with self.subTest(name=name):
                data=(ROOT/name).read_bytes()
                changed=bytes([data[0]^1])+data[1:]
                self.assertFalse(variant_matches(ROOT,UI_VARIANT['files'],
                                                 overrides={name:changed},variant=UI_VARIANT))

    def test_operational_lifecycle_and_write_algorithms_unchanged(self):
        source=nodes((ROOT/'operational_tasks.py').read_text(encoding='utf-8'))
        excluded={'_task','list_tasks','_basis_date','task_ui_summary','qualification_ui_summary','amcu_target_ui_rows'}
        self.assertEqual(digest({k:v for k,v in source.items() if k not in excluded}),
                         CONTRACT['operational_protected_ast'])

    def test_protected_files_exact_content(self):
        matched=matching_variant(ROOT)
        for name,expected in CONTRACT['protected_file_hashes'].items():
            with self.subTest(name=name):
                actual=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                approved=matched['files'].get(name) if matched else None
                self.assertEqual(actual,approved or expected)

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
