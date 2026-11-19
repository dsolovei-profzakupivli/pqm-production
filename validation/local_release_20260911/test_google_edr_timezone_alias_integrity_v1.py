"""Additive guard for the Google Sheets Europe/Kiev timezone alias."""
import hashlib
import json
import unittest
from pathlib import Path


MANIFEST = Path("validation/local_release_20260911/google_edr_timezone_alias_v1.json")
MANIFEST_SHA256_LF = "b311cfe9f17eaebbd992b28222ec6e1612c45c055e476ba4caebaf99fbed99d7"


def canonical(relative: str, data: bytes) -> bytes:
    return data if Path(relative).suffix.lower() == ".zip" else data.replace(b"\r\n", b"\n")


def repository_root() -> Path:
    configured = __import__("os").environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "server.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate Google EDR timezone-alias integrity root")


class GoogleEdrTimezoneAliasIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = repository_root()
        self.manifest_bytes = canonical(str(MANIFEST), (self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_identity_and_exact_scope(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.assertEqual(self.manifest["contract"], "sandbox-google-edr-timezone-alias")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "64f7fda1660c228cbe49c502c6a053fb10c19db1")
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest["files"]), {
            "server.py",
            "validation/local_release_20260911/test_sandbox_edr_review.py",
            "validation/local_release_20260911/test_sandbox_edr_google_nazk_contract_v2_integrity.py",
            "validation/run_local_release.py",
            "validation/fixtures/edr_google_nazk_contract_v2_baseline_64f7fda.zip",
        })
        self.assertEqual(self.manifest["behavior"], {
            "accepted_timezone_ids": ["Europe/Kyiv", "Europe/Kiev"],
            "rejected_timezone_ids": ["Etc/GMT", "UTC", "Europe/Moscow"],
            "verification_timestamp_logic_changed": False,
            "schema_or_database_changed": False,
        })

    def test_pinned_candidate_files_match(self):
        for relative, entry in self.manifest["files"].items():
            with self.subTest(path=relative):
                content = canonical(relative, (self.root / relative).read_bytes())
                key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry[key])

    def test_single_byte_append_delete_and_value_mutations_are_rejected(self):
        for relative, entry in self.manifest["files"].items():
            original = canonical(relative, (self.root / relative).read_bytes())
            key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
            pinned = entry[key]
            for mutation in (bytes([original[0] ^ 1]) + original[1:], original + b"\x00", original[:-1]):
                with self.subTest(path=relative, length=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), pinned)


if __name__ == "__main__":
    unittest.main()
