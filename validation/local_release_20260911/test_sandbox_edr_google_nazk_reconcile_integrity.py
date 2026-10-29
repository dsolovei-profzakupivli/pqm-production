"""Additive exact-content contract for the Sandbox EDR → NAZK reconcile change."""
import hashlib
import json
import ast
import unittest
from pathlib import Path
import zipfile


BASELINE = "40da14517de6988f98dd5d49b1d9e1c21f928290"
MANIFEST_SHA256_LF = "4959074e4cd87f0b7158b45d2aaddc7c3c9d1e38ff04bb5c7246d040bf9659d5"
MANIFEST_RELATIVE = Path("validation/local_release_20260911/sandbox_edr_google_nazk_reconcile_v1.json")
BASELINE_FIXTURE = Path("validation/fixtures/edr_google_nazk_baseline_40da.zip")
BASELINE_FIXTURE_SHA256 = "3e4675426df956b2b7641352ea4d6b900108f5ba418deed7f389cc8deb75e790"
PERSONAL_THEME_FIXTURE = Path("validation/fixtures/edr_google_nazk_personal_theme_baseline_40da.zip")
PERSONAL_THEME_FIXTURE_SHA256 = "7685e8ee5d4b65d7ffc518850a9dacc24019d13bedbb0b3dfcbab2810fdaa69f"


def canonical_text_bytes(value: bytes) -> bytes:
    """Permit only the repository's CRLF/LF checkout difference."""
    return value.replace(b"\r\n", b"\n")


def canonical_file(relative: str, value: bytes) -> bytes:
    return value if Path(relative).suffix.lower() == ".zip" else canonical_text_bytes(value)


def repository_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "local_release_20260911":
        return here.parents[2]
    return here.parent


class SandboxEdrGoogleNazkIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = repository_root()
        cls.manifest_path = cls.root / MANIFEST_RELATIVE
        cls.manifest_bytes = canonical_text_bytes(cls.manifest_path.read_bytes())
        cls.manifest = json.loads(cls.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_is_pinned_to_exact_sandbox_candidate(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256_LF)
        self.assertEqual(self.manifest["baseline"], BASELINE)
        self.assertEqual(self.manifest["contract"], "sandbox-edr-google-nazk-reconcile")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(hashlib.sha256((self.root / PERSONAL_THEME_FIXTURE).read_bytes()).hexdigest(),
                         PERSONAL_THEME_FIXTURE_SHA256)

    def test_protected_product_and_regression_files_match_exact_hashes(self):
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertGreaterEqual(len(self.manifest["files"]), 10)
        for relative, expected in self.manifest["files"].items():
            with self.subTest(path=relative):
                content = canonical_file(relative, (self.root / relative).read_bytes())
                digest_key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
                self.assertEqual(hashlib.sha256(content).hexdigest(), expected[digest_key])

    def test_single_byte_append_and_delete_mutations_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            original = canonical_file(relative, (self.root / relative).read_bytes())
            self.assertTrue(original, relative)
            digest_key = "sha256" if Path(relative).suffix.lower() == ".zip" else "sha256_lf"
            mutations = {
                "single_byte": bytes([original[0] ^ 1]) + original[1:],
                "append": original + b"\x00",
                "delete": original[:-1],
            }
            for mutation_name, changed in mutations.items():
                with self.subTest(path=relative, mutation=mutation_name):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(),
                                        expected[digest_key])

    def test_product_changes_are_limited_to_approved_edr_and_nazk_functions(self):
        fixture = self.root / BASELINE_FIXTURE
        fixture_bytes = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(fixture_bytes).hexdigest(), BASELINE_FIXTURE_SHA256)

        def function_map(source):
            tree = ast.parse(source.decode("utf-8-sig"))
            result = {node.name: ast.dump(node, include_attributes=False)
                      for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            result[f"{node.name}.{method.name}"] = ast.dump(method, include_attributes=False)
            return result

        with zipfile.ZipFile(fixture) as archive:
            self.assertEqual({"edr_sync_v2.py", "server.py", "test_sandbox_messages_integrity.py"},
                             {item.filename for item in archive.infolist() if not item.is_dir()})
            for name, approved in {
                "server.py": {"reconcile_supplier_nazk_after_edr_manager_change", "supplier_edr_sync_worker"},
                "edr_sync_v2.py": {"build_preview", "effective_profile_fields", "apply"},
            }.items():
                with self.subTest(file=name):
                    baseline = function_map(archive.read(name))
                    current = function_map((self.root / name).read_bytes())
                    changed = {key for key in baseline.keys() | current.keys()
                               if baseline.get(key) != current.get(key)}
                    self.assertEqual(approved, changed)


if __name__ == "__main__":
    unittest.main()
