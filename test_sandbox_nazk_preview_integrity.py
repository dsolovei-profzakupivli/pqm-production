"""Exact additive preview manifest; no relaxed matching or rewritten history."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT=integrity.ROOT


class NazkPreviewIntegrityTests(unittest.TestCase):
    def test_exact_additive_variant(self):
        contracts=integrity.load_contracts()
        current=next(c for c in contracts if c['variant_id']==integrity.STABILIZATION_VARIANT_ID)
        integrated=next(c for c in contracts if c['variant_id']==integrity.INTEGRATED_VARIANT_ID)
        scroll=next(c for c in contracts if c['variant_id']==integrity.SCROLL_VARIANT_ID)
        appeals=next(c for c in contracts if c['variant_id']==integrity.APPEALS_API_VARIANT_ID)
        previous=next(c for c in contracts if c['variant_id']==integrity.UI_CANDIDATE_V11_ID)
        preview=next(c for c in contracts if c['variant_id']==integrity.PREVIEW_VARIANT_ID)
        scenario=next(c for c in contracts if c['variant_id']==integrity.UI_CANDIDATE_V12_ID)
        self.assertEqual(len(contracts),24)
        self.assertEqual(current['variant_id'],integrity.STABILIZATION_VARIANT_ID)
        self.assertEqual(current['baseline_sha'],integrity.SCROLL_BASELINE)
        self.assertEqual(current['baseline_sha'],integrity.APPEALS_API_BASELINE)
        self.assertEqual(set(integrated['product_files']),set(previous['product_files'])|
                         integrity.PREVIEW_PRODUCTS|integrity.UI_CANDIDATE_V12_PRODUCT_OVERRIDES|
                         {"validation/fixtures/appeals_scenario_v11_tail.zip"})
        self.assertEqual(set(scroll['product_files']),set(integrated['product_files'])|
                         integrity.SCROLL_PRODUCTS)
        self.assertEqual(set(appeals['product_files']),set(integrated['product_files'])|
                         integrity.APPEALS_API_PRODUCT_OVERRIDES|integrity.APPEALS_API_PRODUCT_ADDITIONS)
        self.assertEqual(set(current['product_files']),set(integrated['product_files'])|
                         integrity.SCROLL_PRODUCTS|integrity.APPEALS_API_PRODUCT_OVERRIDES|
                         integrity.APPEALS_API_PRODUCT_ADDITIONS|integrity.STABILIZATION_PRODUCT_OVERRIDES|
                         integrity.STABILIZATION_PRODUCT_ADDITIONS)
        self.assertEqual(preview['variant_id'],integrity.PREVIEW_VARIANT_ID)
        self.assertEqual(scenario['variant_id'],integrity.UI_CANDIDATE_V12_ID)
        self.assertFalse(integrity.manifest_tree_matches(preview))
        self.assertFalse(integrity.manifest_tree_matches(scenario))
        self.assertFalse(integrity.manifest_tree_matches(integrated))
        self.assertFalse(integrity.manifest_tree_matches(scroll))
        self.assertFalse(integrity.manifest_tree_matches(appeals))
        self.assertTrue(integrity.manifest_tree_matches(current))
        self.assertTrue(integrity.exact_variant_tree_matches())

    def test_historical_manifests_byte_exact(self):
        with zipfile.ZipFile(ROOT/'validation/fixtures/nazk_preview_baseline_f394d4c.zip') as archive:
            hashes=json.loads(archive.read('historical_manifest_sha256.json'))
        self.assertGreater(len(hashes),10)
        for relative,expected in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),expected,relative)

    def test_prior_v11_still_accepts_its_exact_historical_tree(self):
        contracts=integrity.load_contracts()
        previous=next(c for c in contracts if c['variant_id']==integrity.UI_CANDIDATE_V11_ID)
        integrated=next(c for c in contracts if c['variant_id']==integrity.INTEGRATED_VARIANT_ID)
        paths=set().union(*(set(previous[k]) for k in ('product_files','protected_files','guarded_files')))
        with tempfile.TemporaryDirectory() as directory,\
             zipfile.ZipFile(ROOT/'validation/fixtures/nazk_preview_baseline_f394d4c.zip') as archive,\
             zipfile.ZipFile(ROOT/'validation/fixtures/appeals_scenario_v11_tail.zip') as scenario_archive,\
             zipfile.ZipFile(ROOT/'validation/fixtures/appeals_scenario_v11_api_tail.zip') as api_archive:
            tree=Path(directory)
            for relative in paths:
                target=tree/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if relative in archive.namelist():content=archive.read(relative)
                elif relative in scenario_archive.namelist():content=scenario_archive.read(relative)
                elif relative in api_archive.namelist():content=api_archive.read(relative)
                else:content=(ROOT/relative).read_bytes()
                target.write_bytes(content)
            self.assertTrue(integrity.manifest_tree_matches(previous,tree))
            self.assertFalse(integrity.manifest_tree_matches(integrated,tree))
            self.assertFalse(integrity.manifest_tree_matches(contracts[-1],tree))

    def test_unchanged_guards_remain_pinned(self):
        contracts=integrity.load_contracts()
        previous=next(c for c in contracts if c['variant_id']==integrity.UI_CANDIDATE_V11_ID)
        current=contracts[-1]
        changed_paths=(integrity.INTEGRATED_PRODUCTS|integrity.INTEGRATED_GUARDS|
                       integrity.INTEGRATED_PROTECTED|integrity.SCROLL_PRODUCTS|
                       integrity.APPEALS_API_PRODUCT_OVERRIDES|
                       integrity.APPEALS_API_PRODUCT_ADDITIONS|integrity.APPEALS_API_GUARD_OVERRIDES)
        changed_paths |= (integrity.STABILIZATION_PRODUCT_OVERRIDES|
                          integrity.STABILIZATION_PRODUCT_ADDITIONS)
        for section in ('product_files','protected_files','guarded_files'):
            for relative,expected in previous[section].items():
                if relative not in changed_paths:
                    self.assertEqual(current[section][relative],expected,relative)
        for relative in ['app.js','table_widths_ui.js','operational_tasks.py','nazk_workflow.py',
                         'scheduler_runtime.py','halloween.js','registry_popovers.js']:
            self.assertTrue(integrity.exact_variant_file_matches(relative,(ROOT/relative).read_bytes()),relative)

    def test_partial_and_arbitrary_hash_manifests_rejected(self):
        current=integrity.load_contracts()[-1]
        partial=copy.deepcopy(current);partial['product_files']={'nazk_preview.py':current['product_files']['nazk_preview.py']}
        self.assertFalse(integrity.manifest_tree_matches(partial))
        forged=copy.deepcopy(current);forged['product_files']['server.py']['sha256']='0'*64
        self.assertFalse(integrity.manifest_tree_matches(forged))

    def test_one_byte_mutations_of_all_new_products_rejected(self):
        current=integrity.load_contracts()[-1]
        paths=set().union(*(set(current[k]) for k in ('product_files','protected_files','guarded_files')))
        with tempfile.TemporaryDirectory() as directory:
            tree=Path(directory)
            for relative in paths:
                target=tree/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/relative).read_bytes())
            for relative in sorted(integrity.INTEGRATED_PRODUCTS|integrity.SCROLL_PRODUCTS|
                               integrity.APPEALS_API_PRODUCT_OVERRIDES|
                               integrity.APPEALS_API_PRODUCT_ADDITIONS|
                               integrity.STABILIZATION_PRODUCT_OVERRIDES|
                               integrity.STABILIZATION_PRODUCT_ADDITIONS):
                file=tree/relative;original=file.read_bytes();changed=bytearray(original);changed[0]^=1
                file.write_bytes(changed)
                self.assertFalse(integrity.manifest_tree_matches(current,tree),relative)
                file.write_bytes(original)
            self.assertTrue(integrity.manifest_tree_matches(current,tree))


if __name__=='__main__':unittest.main()
