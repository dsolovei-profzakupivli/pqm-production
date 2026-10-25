import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity


ROOT = integrity.ROOT
CONTRACT_FILE = ROOT / 'test_sandbox_admin_officer_link_integrity_v2.json'


class AdminOfficerLinkIntegrityTests(unittest.TestCase):
    def test_historical_admin_contract_is_unchanged_and_new_variant_uses_live_baseline(self):
        contracts = integrity.load_contracts()
        historical_ids = [
            'sandbox-admin-officer-link-v1', 'sandbox-admin-officer-link-v2',
            'sandbox-admin-officer-link-v3', 'sandbox-ui-integrated-d457-v1',
            'sandbox-ui-integrated-d457-v2', 'sandbox-ui-integrated-d457-v3',
            'sandbox-ui-integrated-d457-v4',
        ]
        self.assertEqual(historical_ids, [contract['variant_id'] for contract in contracts[4:11]])
        self.assertEqual('de774010d99e3786eb6ff8308bba78aa5c9a6f13', contracts[4]['baseline_sha'])
        self.assertEqual('4625498cdb938f704cb8dc125c77bf58b2c2a7da', contracts[5]['baseline_sha'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[5]))
        self.assertEqual('4625498cdb938f704cb8dc125c77bf58b2c2a7da', contracts[6]['baseline_sha'])
        self.assertIn('reference_directories.py', contracts[6]['product_files'])
        self.assertNotIn('reference_directories.py', contracts[6]['guarded_files'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[6]))
        for historical in contracts[7:11]:
            self.assertEqual('d457aae211bc0b88cdc66414b9e5765ac7ba350d', historical['baseline_sha'])
            self.assertFalse(integrity.manifest_tree_matches(historical))
        self.assertEqual(integrity.UI_CANDIDATE_V4_DELTA_SHA256,
                         integrity.sha256(integrity.UI_CANDIDATE_V4_DELTA.read_bytes().replace(b'\r\n', b'\n')))
        expected_tail = ['sandbox-ui-integrated-d457-v5', 'sandbox-ui-integrated-d457-v6',
                         integrity.UI_CANDIDATE_V7_ID, integrity.UI_CANDIDATE_V8_ID,
                         integrity.UI_CANDIDATE_V9_ID, integrity.UI_CANDIDATE_V10_ID,
                         integrity.UI_CANDIDATE_V11_ID, integrity.UI_CANDIDATE_V12_ID,
                         integrity.PREVIEW_VARIANT_ID, integrity.INTEGRATED_VARIANT_ID]
        recognized = set(expected_tail)
        self.assertEqual(expected_tail, [contract['variant_id'] for contract in contracts
                                         if contract['variant_id'] in recognized])
        integrated = contracts[-1]
        self.assertEqual(integrity.INTEGRATED_VARIANT_ID, integrated['variant_id'])
        self.assertEqual(integrity.PREVIEW_BASELINE, integrated['baseline_sha'])

    def test_exact_admin_variant_rejects_single_byte_mutations_in_product_and_guards(self):
        contract = integrity.load_contracts()[-1]
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            tree = Path(temporary)
            paths = set(contract['product_files']) | set(contract['guarded_files']) | set(contract['protected_files'])
            for relative in paths:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(contract, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if not changed:
                        changed.extend(b'!')
                    else:
                        changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(contract, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(contract, tree))

    def test_manifest_mutation_cannot_authorize_arbitrary_product_hash(self):
        changed = json.loads(CONTRACT_FILE.read_text(encoding='utf-8'))
        changed['product_files']['app.js']['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            path = Path(temporary) / 'modified.json'
            path.write_text(json.dumps(changed), encoding='utf-8')
            with patch.object(integrity, 'ADMIN_CONTRACT', path):
                with self.assertRaisesRegex(AssertionError, 'закріплений integrity-маніфест'):
                    integrity.load_contracts()


if __name__ == '__main__':
    unittest.main()
