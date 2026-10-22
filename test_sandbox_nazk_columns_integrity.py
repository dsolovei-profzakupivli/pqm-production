"""Full manifest acceptance and adversarial mutations on disposable trees only."""
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = Path(__file__).resolve().parent


def paths(contract):
    return set().union(*(set(contract.get(s, {})) for s in ("product_files", "protected_files", "guarded_files")))


def materialize(contract, destination, historical=False):
    for relative in paths(contract):
        target = Path(destination) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(integrity.nazk_baseline_content(relative) if historical else (ROOT / relative).read_bytes())


class NazkIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.contracts = integrity.load_contracts()
        self.nazk = self.contracts[-1]
        self.cat = self.contracts[2]

    def test_exact_full_tree_and_pinned_manifest(self):
        self.assertEqual(self.nazk["variant_id"], integrity.NAZK_VARIANT_ID)
        self.assertEqual(self.nazk["baseline_sha"], integrity.NAZK_BASELINE)
        self.assertEqual(set(self.nazk["product_files"]), integrity.NAZK_PRODUCTS)
        self.assertEqual(hashlib.sha256(integrity.NAZK_CONTRACT.read_bytes()).hexdigest(), integrity.NAZK_CONTRACT_SHA256)
        self.assertTrue(integrity.manifest_tree_matches(self.nazk))
        self.assertTrue(integrity.exact_variant_tree_matches())
        for relative in paths(self.nazk):
            self.assertTrue(integrity.exact_variant_file_matches(relative, (ROOT / relative).read_bytes()), relative)

    def test_every_single_byte_product_and_guard_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            materialize(self.nazk, temp)
            self.assertTrue(integrity.manifest_tree_matches(self.nazk, temp))
            for relative in sorted(paths(self.nazk)):
                with self.subTest(file=relative):
                    file = Path(temp) / relative
                    original = file.read_bytes()
                    file.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                    self.assertFalse(integrity.manifest_tree_matches(self.nazk, temp))
                    file.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(self.nazk, temp))

    def test_missing_files_and_partial_tree_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            materialize(self.nazk, temp)
            for relative in sorted(paths(self.nazk)):
                with self.subTest(file=relative):
                    file = Path(temp) / relative
                    original = file.read_bytes()
                    file.unlink()
                    self.assertFalse(integrity.manifest_tree_matches(self.nazk, temp))
                    file.write_bytes(original)

    def test_unregistered_partial_and_arbitrary_manifests_are_rejected(self):
        mutations = []
        for section in ("product_files", "protected_files", "guarded_files"):
            value = copy.deepcopy(self.nazk)
            value[section].pop(next(iter(value[section])))
            mutations.append(value)
        for field in ("baseline_sha", "variant_id", "hash_format"):
            value = copy.deepcopy(self.nazk);value[field] = "unapproved";mutations.append(value)
        value = copy.deepcopy(self.nazk);value["product_files"]["app.js"]["sha256"] = "0" * 64;mutations.append(value)
        value = copy.deepcopy(self.nazk);value["product_files"]["unexpected.js"] = {"sha256": "0" * 64};mutations.append(value)
        mutations.extend([{}, {"product_files": {}}])
        for value in mutations:
            with self.subTest(value=value.get("variant_id")):
                self.assertFalse(integrity.manifest_tree_matches(value))

    def test_changed_manifest_cannot_supply_a_new_hash_or_scope(self):
        for field in ("product_files", "baseline_sha", "approved_scope"):
            changed = copy.deepcopy(self.nazk)
            if field == "product_files":changed[field]["app.js"]["sha256"] = "0" * 64
            else:changed[field] = "unapproved"
            with tempfile.TemporaryDirectory(dir=ROOT) as temp:
                file = Path(temp) / "manifest.json"
                file.write_text(json.dumps(changed), encoding="utf-8")
                with patch.object(integrity, "NAZK_CONTRACT", file):
                    with self.assertRaisesRegex(AssertionError, "pinned NAZK"):
                        integrity.load_contracts()

    def test_loader_checks_exact_scope_even_after_digest_check(self):
        for field in ("product_files", "guarded_files", "protected_files"):
            changed = copy.deepcopy(self.nazk);changed[field].pop(next(iter(changed[field])))
            raw = json.dumps(changed).encode()
            with tempfile.TemporaryDirectory(dir=ROOT) as temp:
                file = Path(temp) / "manifest.json";file.write_bytes(raw)
                with patch.object(integrity, "NAZK_CONTRACT", file), patch.object(integrity, "NAZK_CONTRACT_SHA256", hashlib.sha256(raw).hexdigest()):
                    with self.assertRaisesRegex(AssertionError, "exact approved scope"):
                        integrity.load_contracts()

    def test_baseline_and_old_contract_bytes_remain_accepted_and_unchanged(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            materialize(self.cat, temp, historical=True)
            self.assertTrue(integrity.manifest_tree_matches(self.cat, temp))
            self.assertFalse(integrity.manifest_tree_matches(self.nazk, temp))
        for relative in sorted(integrity.NAZK_EXTRA_GUARDS):
            self.assertEqual((ROOT / relative).read_bytes().replace(b"\r\n", b"\n"), integrity.nazk_baseline_content(relative).replace(b"\r\n", b"\n"))

    def test_fixture_is_exact_and_corruption_is_rejected(self):
        self.assertEqual(hashlib.sha256(integrity.NAZK_BASELINE_FIXTURE.read_bytes()).hexdigest(), integrity.NAZK_BASELINE_FIXTURE_SHA256)
        with zipfile.ZipFile(integrity.NAZK_BASELINE_FIXTURE) as archive:
            entries = archive.namelist()
            self.assertEqual(len(entries), len(set(entries)))
            self.assertEqual(set(entries), {integrity.NAZK_BASELINE + "/" + p for p in paths(self.nazk)} | {"approved_nazk.patch"})
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            file = Path(temp) / "corrupt.zip";file.write_bytes(b"not the baseline")
            with patch.object(integrity, "NAZK_BASELINE_FIXTURE", file):
                with self.assertRaisesRegex(AssertionError, "baseline fixture"):
                    integrity.nazk_baseline_content("app.js")

    def test_reverse_exact_approved_fragments_restores_baseline(self):
        # Strip only the appended cells/headers and read mapper additions by
        # reversing the same nine hunks, pinned as a dedicated review patch.
        with zipfile.ZipFile(integrity.NAZK_BASELINE_FIXTURE) as archive:
            patch_bytes = archive.read("approved_nazk.patch")
        self.assertEqual(hashlib.sha256(patch_bytes).hexdigest(), "cc7323cd3a15a943a5e761ac485c4a98246dd03f17e509fa05a8cb50f27d3463")
        hunks = {};name = None;old = [];new = []
        def flush():
            if old or new:hunks.setdefault(name, []).append(("".join(old), "".join(new)))
        for line in patch_bytes.decode("utf-8").replace("\r\n", "\n").splitlines(keepends=True):
            if line.startswith("--- a/"):
                flush();old = [];new = [];name = line[6:].strip()
            elif line.startswith("+++ b/"):continue
            elif line.startswith("@@"):
                flush();old = [];new = []
            elif line.startswith(" "):old.append(line[1:]);new.append(line[1:])
            elif line.startswith("-"):old.append(line[1:])
            elif line.startswith("+"):new.append(line[1:])
        flush()
        self.assertEqual(sum(map(len, hunks.values())), 9)
        self.assertEqual(set(hunks), integrity.NAZK_PRODUCTS)
        for relative in integrity.NAZK_PRODUCTS:
            content = (ROOT / relative).read_text(encoding="utf-8")
            for old, new in reversed(hunks[relative]):
                self.assertEqual(content.count(new), 1)
                content = content.replace(new, old, 1)
            self.assertEqual(content, integrity.nazk_baseline_content(relative).decode("utf-8").replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
