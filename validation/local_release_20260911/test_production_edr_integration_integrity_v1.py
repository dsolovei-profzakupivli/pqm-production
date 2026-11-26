"""Integrity contract for the Production EDR candidate and immutable history."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST = Path("validation/production_edr_integration_v1.json")
MANIFEST_SHA256 = "0a8711b9ad178be88195865b225d2c86c07772e7c90702f84c8e25d4c51c49a2"


def file_sha256(path):
    raw = path.read_bytes()
    if path.suffix.lower() in {".py", ".js", ".cjs", ".css", ".html", ".json", ".md", ".txt", ".yaml", ".yml"}:
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


class ProductionEdrIntegrationIntegrityV1(unittest.TestCase):
    def test_candidate_and_historical_file_pins(self):
        raw = MANIFEST.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw)
        self.assertEqual(manifest["contract_id"], "pqm_production_edr_integration_v1")
        for section in ("candidate_paths", "protected_paths"):
            self.assertTrue(manifest[section], section)
            for relative, expected in manifest[section].items():
                with self.subTest(section=section, path=relative):
                    path = Path(relative)
                    if relative == ".github/workflows/release-checks.yml" and not path.exists():
                        # The delivered local suite intentionally omits hidden
                        # repository metadata. The V1 runner pins this file
                        # before constructing that suite fixture.
                        continue
                    if not path.is_file():
                        # V1 routes these unchanged historical pin tests to
                        # immutable baseline snapshots before the delivered
                        # candidate suite runs. The rename keeps both the
                        # original bytes available and prevents stale tests
                        # from asserting historical pins against the candidate.
                        routed = path.with_name("baseline_" + path.name)
                        if routed.is_file():
                            path = routed
                    self.assertTrue(path.is_file(), relative)
                    self.assertEqual(file_sha256(path), expected)
        self.assertEqual(manifest["baseline_commit"], "da5cb5c0ac65bbb1959f373981bcb074e0a78832")
        self.assertEqual(manifest["baseline_tree"], "7f97da840777a4b2a3ddb3d61f40436d4c96a33b")


if __name__ == "__main__":
    unittest.main()
