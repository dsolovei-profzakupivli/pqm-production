"""Additive exact-content and mutation checks for EDR preview skip semantics."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST = Path("validation/local_release_20260911/sandbox_edr_preview_skipped_rows_v1.json")
MANIFEST_SHA256_LF = "6a724179a879bab054036e9e0a80bbe4041c553e5edf140cabecc9f3f309bb1e"
EXPECTED_BASELINE = "6c310970a1d912cf7f8cfaa3fa802ceaec9685a4"
HISTORICAL_CONTRACTS = {
    "validation/local_release_20260911/sandbox_edr_google_nazk_reconcile_v1.json":
        "4959074e4cd87f0b7158b45d2aaddc7c3c9d1e38ff04bb5c7246d040bf9659d5",
    "validation/local_release_20260911/sandbox_edr_google_nazk_contract_v2.json":
        "84b11fa0f453906aaa0138f1238f06c3843ac7105b4647f2504343e9b0e8ce10",
    "validation/local_release_20260911/test_sandbox_edr_google_nazk_reconcile_integrity.py":
        "26620f8906dc7bdd035e58ca8f099b5ea13f296e359fa019c57f9d113c66ea14",
    "validation/local_release_20260911/test_sandbox_edr_google_nazk_contract_v2_integrity.py":
        "318a44e6efca3a52cd629284b6fdc3c2821ae776019dca9c80a17e559583bd2e",
    "validation/local_release_20260911/google_edr_timezone_alias_v1.json":
        "b311cfe9f17eaebbd992b28222ec6e1612c45c055e476ba4caebaf99fbed99d7",
    "validation/local_release_20260911/test_google_edr_timezone_alias_integrity_v1.py":
        "28bfb64787206d8cdb80882c40e562fd3dbb39a58875f5c81d7f189176ec636a",
}


def canonical(path, data):
    return data if Path(path).suffix.lower() == ".zip" else data.replace(b"\r\n", b"\n")


def repo_root():
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "edr_sync_v2.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate EDR preview skip integrity root")


class EdrPreviewSkippedIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = repo_root()
        self.manifest_bytes = canonical(MANIFEST, (self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_is_exact_and_keeps_historical_contracts(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.assertEqual(self.manifest["baseline"], EXPECTED_BASELINE)
        self.assertEqual(self.manifest["contract"], "sandbox-edr-preview-skipped-rows")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest["files"]), {
            "app.js", "edr_sync_v2.py", "sandbox_edr_review.py", "server.py",
            "validation/local_release_20260911/test_edr_preview_skipped_rows.py",
            "validation/run_local_release.py",
            "validation/run_google_edr_timezone_alias_v1_integrity.py",
            "validation/run_messages_integrated_v1_history.py",
            "validation/fixtures/google_edr_timezone_alias_v1_baseline_6c310.zip",
            "validation/fixtures/messages_integrated_v1_appjs_baseline_6c310.zip",
        })
        self.assertEqual(self.manifest["historical_contracts"], HISTORICAL_CONTRACTS)
        for relative, expected in HISTORICAL_CONTRACTS.items():
            actual = canonical(relative, (self.root / relative).read_bytes())
            self.assertEqual(hashlib.sha256(actual).hexdigest(), expected, relative)

    def test_candidate_files_match_pins_and_only_line_endings_are_normalized(self):
        for relative, pin in self.manifest["files"].items():
            with self.subTest(path=relative):
                raw = (self.root / relative).read_bytes()
                normalized = canonical(relative, raw)
                key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), pin[key])
                if key == "sha256":
                    continue
                crlf = normalized.replace(b"\n", b"\r\n")
                self.assertEqual(hashlib.sha256(canonical(relative, crlf)).hexdigest(), pin[key])

    def test_content_mutations_of_each_candidate_file_are_rejected(self):
        for relative, pin in self.manifest["files"].items():
            original = canonical(relative, (self.root / relative).read_bytes())
            key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
            mutations = (
                bytes([original[0] ^ 1]) + original[1:],
                original + b"\x00",
                original[:-1],
            )
            for mutation in mutations:
                with self.subTest(path=relative, size=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), pin[key])

    def test_manifest_mutations_are_rejected(self):
        for mutation in (self.manifest_bytes + b" ", self.manifest_bytes[:-1],
                         self.manifest_bytes.replace(b'"version": 1', b'"version": 2')):
            self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), MANIFEST_SHA256_LF)


if __name__ == "__main__":
    unittest.main()
