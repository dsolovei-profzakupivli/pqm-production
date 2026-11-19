"""Additive v3 guard; historical v1/v2 classification contracts stay pinned."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parent
MANIFEST = ROOT / "supplier_classification_v3_contract.json"
PINNED_MANIFEST_SHA256 = "86a5bedaba128eb1e9871f8ad2ff4d0906ce92343ec92d9e3bcd2c91862170a6"
SELF_FILE = "test_supplier_classification_v3_integrity.py"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}
HISTORICAL_GIT_BLOBS = {
    "supplier_classification_contract_v1.json": "76e59bc647c2fed442a379a2023b66d67e86b969",
    "google_writer_supplier_types_integration_v1.json": "178fccec8a22c1a583bebef42bbe580fd80da878",
    "date_only_edr_status_integrated_v1.json": "8ef51780a0b582088a01d727cf483e367aa06fa9",
    "date_only_edr_status_integrated_v2.json": "2179aeb5a9c99e03c8005f732ddb0e2e3315e2da",
    "google_edr_date_only_midnight_v1.json": "0e54077c1ae0eda5279a56bfd1cf3a142cd3cd92",
    "test_google_writer_supplier_types_integrity.py": "12a09ed5101140ced7e45337dc4e5c5eeb747c21",
    "test_supplier_classification_integrity.py": "37f0890cd0e787e136205577cb915057d5a64336",
}


def canonical(relative, raw):
    if relative == SELF_FILE:
        raw = re.sub(rb'PINNED_MANIFEST_SHA256 = "[0-9a-f]{64}"',
                     b'PINNED_MANIFEST_SHA256 = "' + b"0" * 64 + b'"', raw)
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def sha(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


def git_text_bytes(relative, raw):
    """Reconstruct Git's LF text blob for explicitly pinned historical files."""
    if relative not in HISTORICAL_GIT_BLOBS:
        raise ValueError(f"Unpinned historical text path: {relative}")
    normalized = raw.replace(b"\r\n", b"\n")
    if b"\r" in normalized:
        raise ValueError(f"Unexpected lone CR in historical text file: {relative}")
    return normalized


def git_blob_sha(relative, raw):
    data = git_text_bytes(relative, raw)
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


class SupplierClassificationV3IntegrityTests(unittest.TestCase):
    def setUp(self):
        raw = canonical(MANIFEST.name, MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PINNED_MANIFEST_SHA256)
        self.manifest = json.loads(raw.decode("utf-8"))

    def test_exact_v3_tree_and_baseline(self):
        self.assertEqual(self.manifest["parent"], "12f5eadc63199342209af33c60a5de4f868ec566")
        actual = {relative: sha(relative, (ROOT / relative).read_bytes())
                  for relative in self.manifest["files"]}
        self.assertEqual(set(actual), set(self.manifest["files"]))
        self.assertEqual(actual, self.manifest["files"])

    def test_historical_manifests_are_byte_unchanged(self):
        self.assertEqual(set(self.manifest["historical_manifests"]), set(HISTORICAL_GIT_BLOBS))
        for relative, expected_sha256 in self.manifest["historical_manifests"].items():
            raw = (ROOT / relative).read_bytes()
            self.assertEqual(git_blob_sha(relative, raw), HISTORICAL_GIT_BLOBS[relative], relative)
            raw_sha256 = hashlib.sha256(raw).hexdigest()
            lf_sha256 = hashlib.sha256(git_text_bytes(relative, raw)).hexdigest()
            self.assertIn(raw_sha256, (expected_sha256, lf_sha256), relative)

    def test_historical_manifest_eol_checkout_is_portable_but_content_mutation_fails(self):
        relative = "supplier_classification_contract_v1.json"
        expected = HISTORICAL_GIT_BLOBS[relative]
        source = (ROOT / relative).read_bytes()
        lf = git_text_bytes(relative, source)
        crlf = lf.replace(b"\n", b"\r\n")
        self.assertEqual(git_blob_sha(relative, lf), expected)
        self.assertEqual(git_blob_sha(relative, crlf), expected)

        mutated = bytearray(lf)
        index = next(i for i, value in enumerate(mutated) if value not in (10, 13))
        mutated[index] ^= 1
        self.assertNotEqual(git_blob_sha(relative, bytes(mutated)), expected)

    def test_product_contract_versions_routing_and_write_ownership(self):
        classifier = (ROOT / "supplier_classification.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = 'subject-nature-20261031-v3'", classifier)
        for relative, needle in (
            ("scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs", "item.classification_version !== 'subject-nature-20261031-v3'"),
            ("scripts/pqm-google-writer/PqmGoogleWriter.gs", "x.classification_version !== 'subject-nature-20261031-v3'"),
            ("scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs", "x.classification_version !== 'subject-nature-20261031-v3'"),
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(needle, source)
            self.assertNotIn("subject-nature-20261030-v2'", source)
        deps = (ROOT / "scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs").read_text(encoding="utf-8")
        self.assertIn("var PQM_GOOGLE_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        self.assertIn("var PQM_GOOGLE_APPEND_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        matrix = (ROOT / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        self.assertIn("item.entity_type === 'individual_entrepreneur' ? 'ФОП'", matrix)
        self.assertIn("item.entity_type === 'legal_entity' ? 'ЮО'", matrix)

    def test_semantic_mutations_are_rejected(self):
        for relative in self.manifest["mutation_targets"]:
            data = (ROOT / relative).read_bytes()
            self.assertTrue(data)
            variants = (bytes([data[0] ^ 1]) + data[1:], data + b"X", data[:-1])
            expected = self.manifest["files"][relative]
            for altered in variants:
                with self.subTest(path=relative, size=len(altered)):
                    self.assertNotEqual(sha(relative, altered), expected)


if __name__ == "__main__":
    unittest.main()
