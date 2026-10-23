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
        self.assertEqual(10, len(contracts))
        self.assertEqual('sandbox-admin-officer-link-v1', contracts[4]['variant_id'])
        self.assertEqual('de774010d99e3786eb6ff8308bba78aa5c9a6f13', contracts[4]['baseline_sha'])
        self.assertEqual('sandbox-admin-officer-link-v2', contracts[5]['variant_id'])
        self.assertEqual('4625498cdb938f704cb8dc125c77bf58b2c2a7da', contracts[5]['baseline_sha'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[5]))
        self.assertEqual('sandbox-admin-officer-link-v3', contracts[6]['variant_id'])
        self.assertEqual('4625498cdb938f704cb8dc125c77bf58b2c2a7da', contracts[6]['baseline_sha'])
        self.assertIn('reference_directories.py', contracts[6]['product_files'])
        self.assertNotIn('reference_directories.py', contracts[6]['guarded_files'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[6]))
        self.assertEqual('sandbox-ui-integrated-d457-v1', contracts[7]['variant_id'])
        self.assertEqual('d457aae211bc0b88cdc66414b9e5765ac7ba350d', contracts[7]['baseline_sha'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[7]))
        self.assertEqual('sandbox-ui-integrated-d457-v2', contracts[8]['variant_id'])
        self.assertEqual('d457aae211bc0b88cdc66414b9e5765ac7ba350d', contracts[8]['baseline_sha'])
        self.assertFalse(integrity.manifest_tree_matches(contracts[8]))
        self.assertEqual('sandbox-ui-integrated-d457-v3', contracts[9]['variant_id'])
        self.assertEqual('d457aae211bc0b88cdc66414b9e5765ac7ba350d', contracts[9]['baseline_sha'])
        self.assertTrue(integrity.manifest_tree_matches(contracts[9]))

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
