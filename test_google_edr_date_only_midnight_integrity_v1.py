"""Additive exact-content and mutation contract for date-only EDR comparison."""
import hashlib
import json
import unittest
from pathlib import Path

from google_verification_contract import (
    google_verification_instant,
    google_verification_timestamp,
    incoming_verification_gate,
)

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "google_edr_date_only_midnight_v1.json"
PINNED_MANIFEST_SHA256 = "b487feaf21182b2a445dd1967d2a2ce70ae7f0cf90c14ea90050679acb560a91"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}
HISTORICAL_CONTRACTS = {
    "validation/local_release_20260911/google_edr_timezone_alias_v1.json":
        "b311cfe9f17eaebbd992b28222ec6e1612c45c055e476ba4caebaf99fbed99d7",
    "validation/local_release_20260911/sandbox_edr_google_nazk_reconcile_v1.json":
        "4959074e4cd87f0b7158b45d2aaddc7c3c9d1e38ff04bb5c7246d040bf9659d5",
    "validation/local_release_20260911/sandbox_edr_google_nazk_contract_v2.json":
        "84b11fa0f453906aaa0138f1238f06c3843ac7105b4647f2504343e9b0e8ce10",
    "validation/local_release_20260911/test_google_edr_timezone_alias_integrity_v1.py":
        "28bfb64787206d8cdb80882c40e562fd3dbb39a58875f5c81d7f189176ec636a",
    "validation/local_release_20260911/test_sandbox_edr_google_nazk_reconcile_integrity.py":
        "26620f8906dc7bdd035e58ca8f099b5ea13f296e359fa019c57f9d113c66ea14",
    "validation/local_release_20260911/test_sandbox_edr_google_nazk_contract_v2_integrity.py":
        "318a44e6efca3a52cd629284b6fdc3c2821ae776019dca9c80a17e559583bd2e",
}


def canonical(relative, raw):
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


class GoogleEdrDateOnlyMidnightIntegrity(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = canonical(MANIFEST.name, MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), PINNED_MANIFEST_SHA256)
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_pins_only_this_change_and_keeps_history(self):
        self.assertEqual(self.manifest["baseline"], "97788b2549f08a7a15738bdeecc508ee3cf545ad")
        self.assertEqual(self.manifest["contract"], "google-edr-date-only-midnight-v1")
        self.assertEqual(self.manifest["historical_contracts"], HISTORICAL_CONTRACTS)
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["mutation_targets"]))
        for relative, expected in HISTORICAL_CONTRACTS.items():
            actual = hashlib.sha256(canonical(relative, (ROOT / relative).read_bytes())).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_candidate_file_pins_and_negative_mutations(self):
        for relative, expected in self.manifest["files"].items():
            original = canonical(relative, (ROOT / relative).read_bytes())
            self.assertEqual(hashlib.sha256(original).hexdigest(), expected, relative)
            mutations = (bytes([original[0] ^ 1]) + original[1:], original + b"X", original[:-1])
            for mutation in mutations:
                with self.subTest(path=relative, length=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(canonical(relative, mutation)).hexdigest(), expected)

    def test_date_only_is_kyiv_midnight_for_ordering_but_stays_date_only_in_storage(self):
        parsed = google_verification_instant("29.10.2026")
        self.assertEqual(parsed["kind"], "datetime")
        self.assertEqual(parsed["value"].isoformat(), "2026-10-28T22:00:00+00:00")
        self.assertEqual(google_verification_timestamp("29.10.2026"), "2026-10-29")
        vectors = (
            ("30.10.2026", "29.10.2026 16:50:00", "newer"),
            ("29.10.2026", "30.10.2026 09:00:00", "older"),
            ("29.10.2026 17:00:00", "29.10.2026 16:50:00", "newer"),
            ("29.10.2026", "29.10.2026 16:50:00", "older"),
            ("29.10.2026 16:50:00", "29.10.2026", "newer"),
            ("29.10.2026", "29.10.2026", "equal"),
        )
        for incoming, current, reason in vectors:
            with self.subTest(incoming=incoming, current=current):
                result = incoming_verification_gate(incoming, current, require_time=True)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["accepted"], reason == "newer")

    def test_equal_second_precision_and_kyiv_alias_remain_exact(self):
        self.assertEqual(incoming_verification_gate(
            "29.10.2026 16:50:41", "2026-10-29T14:50:41Z", require_time=True)["reason"], "equal")
        self.assertEqual(incoming_verification_gate(
            "29.10.2026 16:50:42", "2026-10-29T14:50:41Z", require_time=True)["reason"], "newer")


if __name__ == "__main__":
    unittest.main()
