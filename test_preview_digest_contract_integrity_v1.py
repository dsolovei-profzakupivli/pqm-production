"""Additive integrity contract for the canonical Preview digest wire format."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20260911/preview_digest_contract_v1.json")
MANIFEST_SHA256 = "5f55d204acd1f22d2550dd23160c00877f3a7f28292658147179e464e0e07a32"
TEST_FILE = "test_preview_digest_contract_integrity_v1.py"
RUNTIME_FIXTURE = "sandbox_runtime_messages_integrated_v1_86ea864.py"


def canonical_text(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(rb'MANIFEST_SHA256 = "[0-9a-f]{64}"',
                  b'MANIFEST_SHA256 = "<pinned-manifest-sha256>"',
                  canonical_text(data))


def repository_root():
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "server.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate Preview digest integrity root")


class PreviewDigestIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical_text((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_identity_scope_and_history(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-preview-digest")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "95037e3d0255d592695661a5c7626e2bc64d9881")
        self.assertEqual(self.manifest["wire_format"], {
            "algorithm": "SHA-256", "encoding": "canonical unpadded Base64url",
            "encoded_characters": 43, "decoded_bytes": 32,
        })
        self.assertEqual(hashlib.sha256(canonical_self((self.root / TEST_FILE).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])
        self.assertEqual(set(self.manifest["files"]), {
            "execution_digest.py",
            "google_writer_execution.py",
            "sandbox_runtime.py",
            "test_google_writer_execution.py",
            "test_sandbox_execution_transport.py",
            "test_preview_digest_contract_integrity_v1.py",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxControlledApply.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs",
            "scripts/pqm-google-writer/sandbox-full-apply.test.cjs",
            "validation/run_messages_integrated_v1_history.py",
            RUNTIME_FIXTURE,
        })
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(historical_manifest=relative):
                data = canonical_text((self.root / relative).read_bytes())
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)

    def test_candidate_sources_match_the_additive_contract(self):
        for relative, expected in self.manifest["files"].items():
            with self.subTest(path=relative):
                data = (self.root / relative).read_bytes()
                if relative == TEST_FILE:
                    data = canonical_self(data)
                else:
                    data = canonical_text(data)
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)

    def test_historical_runtime_fixture_is_exact_and_not_live_source(self):
        fixture = (self.root / RUNTIME_FIXTURE).read_bytes()
        self.assertEqual(hashlib.sha256(canonical_text(fixture)).hexdigest(),
                         "7ce145ff533c134440ad138651660e0c0434a1a7028ba4a7fd8698daf9407499")
        self.assertNotEqual(canonical_text(fixture),
                            canonical_text((self.root / "sandbox_runtime.py").read_bytes()))

    def test_single_byte_append_and_truncation_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            original = (self.root / relative).read_bytes()
            canonical = canonical_self(original) if relative == TEST_FILE else canonical_text(original)
            mutations = (bytes([canonical[0] ^ 1]) + canonical[1:], canonical + b"\x00", canonical[:-1])
            for mutation in mutations:
                with self.subTest(path=relative, mutation_length=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
