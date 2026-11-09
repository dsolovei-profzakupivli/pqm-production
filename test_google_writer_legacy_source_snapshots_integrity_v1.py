"""Additive verification that historical Google Writer contracts stay immutable."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261109/google_writer_legacy_source_snapshots_v1.json')
MANIFEST_SHA256 = "df3d3dd8487d76b94d068051120ae0e9901b9087c8a726825251c1d4cc6aeac0"
TEST_FILE = 'test_google_writer_legacy_source_snapshots_integrity_v1.py'


def canonical(raw):
    return raw.replace(b'\r\n', b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(raw))


def root_path():
    configured = os.environ.get('PQM_RELEASE_SOURCE_ROOT')
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for root in (here.parent, *here.parents):
        if (root / MANIFEST).is_file() and (root / 'validation/run_local_release.py').is_file():
            return root
    raise RuntimeError('Cannot locate immutable Google Writer snapshot overlay root')


class GoogleWriterLegacySourceSnapshotsIntegrityTests(unittest.TestCase):
    def test_additive_snapshot_overlay_pins_archives_and_preserves_historical_manifests(self):
        root = root_path()
        manifest_bytes = canonical((root / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-immutable-exact-source-overlays')
        self.assertEqual(manifest['version'], 1)
        self.assertEqual(set(manifest['files']), set(manifest['scope']))
        for relative, expected in manifest['files'].items():
            raw = (root / relative).read_bytes()
            normalized = canonical_self(raw) if relative == TEST_FILE else canonical(raw)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((root / relative).read_bytes())).hexdigest(), expected)

    def test_runner_uses_immutable_snapshots_for_each_historical_exact_tree(self):
        root = root_path()
        runner = canonical((root / 'validation/run_local_release.py').read_bytes()).decode('utf-8')
        for module in ('test_legacy_append_reconciliation_integrity_v3',
                       'validation.local_release_20260911.test_legacy_sheet_read_bounds_integrity_v1'):
            with self.subTest(module=module):
                self.assertIn(repr(module), runner)
        self.assertIn('run_immutable_google_writer_source_overlays.py', runner)
        self.assertIn('immutable_google_writer_source_overlays.returncode==0', runner)
        self.assertIn('google_writer_legacy_reconciliation_v3_immutable.zip', runner)
        self.assertIn('google_writer_legacy_sheet_bounds_v1_immutable.zip', runner)
        exact = runner[runner.index('EXACT_TREE_OVERLAY_MODULES='):runner.index('\ndef selected_suite')]
        self.assertIn("'test_legacy_append_reconciliation_integrity_v3'", exact)
        self.assertIn("'validation.local_release_20260911.test_legacy_sheet_read_bounds_integrity_v1'", exact)


if __name__ == '__main__':
    unittest.main()
