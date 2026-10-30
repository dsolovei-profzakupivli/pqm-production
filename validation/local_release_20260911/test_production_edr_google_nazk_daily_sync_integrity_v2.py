"""Additive integrity contract for daily-sync timestamp regression fixtures."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path.cwd()
MANIFEST = Path('validation/fixtures/production_edr_google_nazk_daily_sync_ea3079_v2.json')
MANIFEST_SHA256 = '87d6a0e36389e63093bffd8a8dde165e9727f582a3da9f8feb0db7232f0d89ad'
HISTORICAL_MANIFEST = Path('validation/fixtures/production_edr_google_nazk_ea3079_v1.json')
HISTORICAL_MANIFEST_SHA256 = 'ffbd92ff26994d2e1e278ea64b16126aeb1159164178377632467bd609ded3e3'
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.css', '.html', '.json', '.md', '.txt', '.yaml', '.yml'}


def normalized(content, relative):
    return content.replace(b'\r\n', b'\n') if Path(relative).suffix.lower() in TEXT_SUFFIXES else content


def digest(content, relative):
    return hashlib.sha256(normalized(content, relative)).hexdigest()


def load_manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise AssertionError('Daily-sync additive manifest hash mismatch')
    payload = json.loads(raw)
    if payload.get('contract_id') != 'pqm_production_edr_google_nazk_daily_sync_ea3079_v2':
        raise AssertionError('Unexpected daily-sync integrity contract')
    if payload.get('parent_sha') != 'f0eb3cb28f233d2a24d1f10e9ab2c8ee36ece0f4':
        raise AssertionError('Unexpected candidate parent')
    historical = normalized(HISTORICAL_MANIFEST.read_bytes(), HISTORICAL_MANIFEST)
    if hashlib.sha256(historical).hexdigest() != HISTORICAL_MANIFEST_SHA256:
        raise AssertionError('Historical EDR/NAZK manifest changed')
    return payload


class ProductionEdrGoogleNazkDailySyncIntegrityV2Tests(unittest.TestCase):
    def test_additive_contract_is_scoped_to_regression_fixtures(self):
        manifest = load_manifest()
        self.assertEqual(set(manifest['regression_sha256']), {
            'scripts/pqm-google-writer/sandbox-append-daily-cycle.test.cjs',
            'scripts/pqm-google-writer/sandbox-full-apply.test.cjs',
        })
        self.assertEqual(set(manifest['protected_sha256']), {
            'google_verification_contract.py',
            'edr_sync_v2.py',
            'validation/local_release_20260911/daily_cycle_evening_fixture.py',
        })
        historical = json.loads(HISTORICAL_MANIFEST.read_text(encoding='utf-8'))
        self.assertEqual(manifest['protected_sha256']['google_verification_contract.py'],
                         historical['product_sha256']['google_verification_contract.py'])
        self.assertEqual(manifest['protected_sha256']['edr_sync_v2.py'],
                         historical['product_sha256']['edr_sync_v2.py'])

    def test_pinned_files_match_and_content_mutations_are_rejected(self):
        manifest = load_manifest()
        for relative, expected in {**manifest['regression_sha256'],
                                   **manifest['protected_sha256']}.items():
            with self.subTest(path=relative):
                content = (ROOT / relative).read_bytes()
                self.assertEqual(digest(content, relative), expected)
                self.assertNotEqual(digest(content + b'X', relative), expected)
                self.assertNotEqual(digest(content[:-1], relative), expected)
                changed = bytearray(content)
                changed[len(changed) // 2] ^= 1
                self.assertNotEqual(digest(bytes(changed), relative), expected)


if __name__ == '__main__':
    unittest.main()
