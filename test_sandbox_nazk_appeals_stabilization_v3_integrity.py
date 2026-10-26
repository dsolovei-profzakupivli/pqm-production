"""Immutable v3 history and additive v4 integrity checks."""
import json
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.ROOT


class ScenarioContextSnapshotIntegrityTests(unittest.TestCase):
    def test_v3_adds_scenario_cache_without_rewriting_v1_v2_or_table_preferences(self):
        contracts = integrity.load_contracts()
        v2 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V2_VARIANT_ID)
        v3 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V3_VARIANT_ID)
        v4 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V4_VARIANT_ID)
        current = next(item for item in contracts
                       if item["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        self.assertEqual(v2["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(v3["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(set(v3["approved_scope"]) - set(v2["approved_scope"]),
                         integrity.STABILIZATION_V3_SCOPE)
        self.assertFalse(integrity.manifest_tree_matches(v3))
        self.assertFalse(integrity.manifest_tree_matches(v4))
        self.assertTrue(integrity.manifest_tree_matches(current))
        self.assertFalse(integrity.manifest_tree_matches(v2))
        self.assertTrue(integrity.exact_variant_tree_matches())
        self.assertEqual((ROOT / "test_sandbox_nazk_appeals_stabilization_v2.json").read_bytes(),
                         integrity.STABILIZATION_V2_CONTRACT.read_bytes())
        self.assertEqual(integrity.sha256(
            integrity.STABILIZATION_V3_CONTRACT.read_bytes().replace(b"\r\n", b"\n")),
            integrity.STABILIZATION_V3_CONTRACT_SHA256)
        widths = v2["product_files"].get("table_widths_ui.js") or \
            v2["guarded_files"].get("table_widths_ui.js") or \
            v2["protected_files"].get("table_widths_ui.js")
        self.assertIsNotNone(widths)
        self.assertEqual(integrity.sha256(integrity.canonical_content(
            "table_widths_ui.js", (ROOT / "table_widths_ui.js").read_bytes())), widths["sha256"])

    def test_scenario_cache_is_separate_minimal_local_and_not_backfilled(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS violation_scenario_context_snapshots", source)
        table_start = source.index("CREATE TABLE IF NOT EXISTS violation_scenario_context_snapshots")
        table_end = source.index("CREATE TABLE IF NOT EXISTS violation_report_document_reviews", table_start)
        table = source[table_start:table_end]
        self.assertIn("context_json TEXT NOT NULL", table)
        self.assertNotIn("summary", table.lower())
        self.assertNotIn("decision_context_snapshot", table)
        list_start = source.index("def list_violation_reports(")
        list_end = source.index("\nVIOLATION_REVIEW_FIELDS =", list_start)
        list_api = source[list_start:list_end]
        self.assertIn("_validated_scenario_context_snapshot(", list_api)
        self.assertNotIn("api_get(", list_api)
        self.assertNotIn("save_violation_report_with_retry(", list_api)
        self.assertNotIn("table_widths_ui.js", integrity.STABILIZATION_V3_PRODUCT_OVERRIDES)
        self.assertNotIn("table_widths_ui.js", integrity.STABILIZATION_V3_PRODUCT_ADDITIONS)

    def test_single_byte_mutation_of_every_v5_file_is_rejected(self):
        v4 = next(item for item in integrity.load_contracts()
                  if item["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        paths = integrity.STABILIZATION_V5_PRODUCT_OVERRIDES | integrity.STABILIZATION_V5_PRODUCT_ADDITIONS
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in set(v4["product_files"]) | set(v4["guarded_files"]) | set(v4["protected_files"]):
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(v4, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if changed:
                        changed[0] ^= 1
                    else:
                        changed.extend(b"!")
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(v4, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(v4, tree))


if __name__ == "__main__":
    unittest.main()
