"""Additive current-tree and historical-resolver regression; no application import."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import production_integrity_overlay as overlay

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).parent.name == 'local_release_20260911' else Path(__file__).resolve().parent
MANIFEST_SHA256 = '70d49a0f6efb28c4f666ca6f3354c0711fd43c7b20b88976dfd18bf3294d6436'

def sha(data, name):
    if Path(name).suffix in {'.py', '.js', '.json', '.cjs'}:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()

class GateResolverTests(unittest.TestCase):
    def test_additive_current_files_and_negative_mutations(self):
        raw = (ROOT / 'validation/memory_stage1_gate_resolver_v1.json').read_bytes()
        self.assertEqual(sha(raw, 'manifest.json'), MANIFEST_SHA256)
        manifest = json.loads(raw)
        for name, expected in manifest['files'].items():
            with self.subTest(file=name):
                data = (ROOT / name).read_bytes()
                self.assertEqual(sha(data, name), expected)
                self.assertNotEqual(sha(data + b'X', name), expected)
                self.assertNotEqual(sha(data[:-1], name), expected)
                changed = bytearray(data); changed[len(changed)//2] ^= 1
                self.assertNotEqual(sha(changed, name), expected)
        for name, expected in manifest['unchanged_files'].items():
            self.assertEqual(sha((ROOT / name).read_bytes(), name), expected, name)

    def test_shared_resolver_preserves_current_functional_fixture(self):
        source = ROOT / overlay.NAZK_TEST_MEMBER
        before = source.read_bytes()
        self.assertEqual(sha(before, source.name), '393239139ff27638538fe951509a705a89b3f4d30178cdfaa65327d3eb34a8e5')
        historical = overlay.historical_integrity_root(ROOT)
        self.assertNotEqual(historical, ROOT)
        self.assertEqual(sha((historical / overlay.NAZK_TEST_MEMBER).read_bytes(), source.name), overlay.NAZK_TEST_SHA256)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(overlay.historical_integrity_root(ROOT), historical)
        self.assertEqual(overlay.historical_integrity_root(historical), historical)

    def test_missing_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                overlay._historical_nazk_test(Path(folder))

    def test_changed_archive_is_rejected(self):
        data = bytearray((ROOT / overlay.NAZK_TEST_ARCHIVE).read_bytes())
        data[-1] ^= 1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / overlay.NAZK_TEST_ARCHIVE
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            with self.assertRaisesRegex(AssertionError, 'archive changed'):
                overlay._historical_nazk_test(Path(folder))

    def test_corrupted_marked_history_is_rejected_not_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sentinel = root / 'validation/fixtures/production_nazk_messages_integrated_f9eb8ed_v1.json'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('{}')
            (root / '.pqm_historical_integrity_overlay').write_text('synthetic')
            target = root / overlay.NAZK_TEST_MEMBER
            target.parent.mkdir(parents=True, exist_ok=True)
            original = overlay._historical_nazk_test(ROOT)
            changed = bytes([original[0] ^ 1]) + original[1:]
            target.write_bytes(changed)
            with self.assertRaisesRegex(AssertionError, 'no longer matches'):
                overlay.historical_integrity_root(root)
            self.assertEqual(target.read_bytes(), changed)

    def test_both_entrypoints_keep_original_contract_assertions(self):
        runner = (ROOT / 'validation/run_local_release.py').read_text()
        smoke = (ROOT / 'validation/nazk_scheduler_failure_smoke.py').read_text()
        contract = (ROOT / 'test_production_ui_release_integrity.py').read_text()
        self.assertIn('historical_root = historical_integrity_root(root)', runner)
        self.assertIn('"test_production_ui_release_integrity"', smoke)
        self.assertIn('ROOT=historical_integrity_root(Path(__file__).resolve().parent)', contract)
        self.assertIn('self.assertEqual(hashlib.sha256(data).hexdigest(),NAZK_FULL_VARIANT[key])', contract)
        self.assertEqual(overlay.NAZK_TEST_SHA256, '829db6538fa96ac4cd4a3fc67c61c12d484d259a739e6b820ccf8760885c01fe')

if __name__ == '__main__': unittest.main()
