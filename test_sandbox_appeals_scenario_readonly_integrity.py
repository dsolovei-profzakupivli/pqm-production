"""Additive integrity contract for projecting complete saved scenarios on editable reports."""
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.ROOT


class AppealsScenarioReadonlyIntegrityTests(unittest.TestCase):
    def test_v2_and_v3_history_remain_exact_before_additive_v4(self):
        contracts = integrity.load_contracts()
        previous = next(c for c in contracts
                        if c["variant_id"] == integrity.STABILIZATION_V1_VARIANT_ID)
        v2 = next(c for c in contracts
                  if c["variant_id"] == integrity.STABILIZATION_V2_VARIANT_ID)
        v3 = next(c for c in contracts
                  if c["variant_id"] == integrity.STABILIZATION_V3_VARIANT_ID)
        current = next(c for c in contracts
                       if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        raw = integrity.STABILIZATION_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(integrity.sha256(raw), integrity.STABILIZATION_CONTRACT_SHA256)
        raw_v2 = integrity.STABILIZATION_V2_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(integrity.sha256(raw_v2), integrity.STABILIZATION_V2_CONTRACT_SHA256)
        self.assertEqual(previous["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(v2["variant_id"], "sandbox-nazk-appeals-stabilization-v2")
        self.assertEqual(current["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(v3["variant_id"], integrity.STABILIZATION_V3_VARIANT_ID)
        self.assertEqual(current["variant_id"], "sandbox-nazk-appeals-stabilization-v4")
        self.assertEqual(set(v2["approved_scope"]) - set(previous["approved_scope"]),
                         integrity.STABILIZATION_V2_SCOPE)
        self.assertEqual(set(v3["approved_scope"]) - set(v2["approved_scope"]),
                         integrity.STABILIZATION_V3_SCOPE)
        self.assertEqual(set(current["approved_scope"]) - set(v3["approved_scope"]),
                         integrity.STABILIZATION_V4_SCOPE)
        self.assertEqual(set(v3["product_files"]),
                         set(v2["product_files"]) |
                         integrity.STABILIZATION_V3_PRODUCT_OVERRIDES |
                         integrity.STABILIZATION_V3_PRODUCT_ADDITIONS)
        self.assertEqual(set(current["product_files"]), set(v3["product_files"]) |
                         integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                         integrity.STABILIZATION_V4_PRODUCT_ADDITIONS)
        self.assertEqual(set(v3["guarded_files"]),
                         (set(v2["guarded_files"]) - {"server.py"}) |
                         (integrity.STABILIZATION_V3_PRODUCT_OVERRIDES - {"server.py"}) |
                         integrity.STABILIZATION_V3_PRODUCT_ADDITIONS)
        self.assertEqual(set(current["guarded_files"]), set(v3["guarded_files"]) |
                         integrity.STABILIZATION_V4_PRODUCT_OVERRIDES.intersection(v3["guarded_files"]) |
                         integrity.STABILIZATION_V4_PRODUCT_ADDITIONS)
        self.assertEqual(current["protected_files"]["server.py"]["sha256"],
                         current["product_files"]["server.py"]["sha256"])
        self.assertFalse(integrity.manifest_tree_matches(previous))
        self.assertFalse(integrity.manifest_tree_matches(v2))
        self.assertFalse(integrity.manifest_tree_matches(v3))
        self.assertTrue(integrity.manifest_tree_matches(current))
        self.assertTrue(integrity.exact_variant_tree_matches())

    def test_scenario_prefix_is_ui_only_and_scope_is_pinned(self):
        self.assertIn("strip-leading-scenario-label-in-table-only", integrity.STABILIZATION_V2_SCOPE)
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        start = app.index("function requestScenarioCell(")
        end = app.index("\nfunction showSavedRequestJustification(", start)
        cell = app[start:end]
        self.assertIn("replace(/^Сценарій:\\s*/i,'')", cell)
        self.assertIn("item.scenario_summary", cell)
        self.assertIn("esc(item.scenario_summary)", app)
        self.assertEqual(app.count("replace(/^Сценарій:"), 1)

    def test_eye_viewer_visibility_depends_only_on_nonblank_saved_justification(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        start = app.index("function requestScenarioCell(")
        end = app.index("\nfunction showSavedRequestJustification(", start)
        cell = app[start:end]
        self.assertIn("Boolean(String(item.decision_justification||'').trim())", cell)
        self.assertIn("${hasSavedJustification?`<button", cell)
        self.assertIn("data-view-justification=\"${index}\"", cell)
        self.assertNotIn("item.status", cell)
        self.assertNotIn("item.scenario_summary?", cell)
        self.assertIn("function showSavedRequestJustification(index)", app)
        self.assertIn("body.textContent=text||'Обґрунтування для цього звернення ще не сформовано.'", app)

    def test_single_byte_mutation_of_each_v4_override_or_addition_is_rejected(self):
        current = next(c for c in integrity.load_contracts()
                       if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        paths = set(current["product_files"]) | set(current["protected_files"]) | set(current["guarded_files"])
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in paths:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(current, tree))
            changed_paths = (integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_V4_PRODUCT_ADDITIONS)
            for relative in sorted(changed_paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if changed:
                        changed[0] ^= 1
                    else:
                        changed.extend(b"!")
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(current, tree))


if __name__ == "__main__":
    unittest.main()
