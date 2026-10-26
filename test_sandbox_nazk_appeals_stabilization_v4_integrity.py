"""Additive integrity contract for complete Appeals scenario display."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.ROOT


class FullAppealsScenarioDisplayIntegrityTests(unittest.TestCase):
    def test_v4_is_additive_and_preserves_all_historical_stabilization_manifests(self):
        contracts = integrity.load_contracts()
        v2 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V2_VARIANT_ID)
        v3 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V3_VARIANT_ID)
        current = next(item for item in contracts
                       if item["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        for manifest, expected in (
            (integrity.STABILIZATION_CONTRACT, integrity.STABILIZATION_CONTRACT_SHA256),
            (integrity.STABILIZATION_V2_CONTRACT, integrity.STABILIZATION_V2_CONTRACT_SHA256),
            (integrity.STABILIZATION_V3_CONTRACT, integrity.STABILIZATION_V3_CONTRACT_SHA256),
        ):
            raw = manifest.read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected, manifest.name)
        self.assertEqual(current["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(set(current["approved_scope"]) - set(v3["approved_scope"]),
                         integrity.STABILIZATION_V4_SCOPE)
        self.assertEqual(set(current["product_files"]), set(v3["product_files"]) |
                         integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                         integrity.STABILIZATION_V4_PRODUCT_ADDITIONS)
        self.assertTrue(integrity.manifest_tree_matches(current))
        self.assertFalse(integrity.manifest_tree_matches(v3))
        self.assertFalse(integrity.manifest_tree_matches(v2))
        self.assertTrue(integrity.exact_variant_tree_matches())
        self.assertNotIn("table_widths_ui.js", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        self.assertNotIn("server.py", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        self.assertIn("app.js", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        self.assertIn("app.js", current["protected_files"])
        self.assertIn("app.js", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        self.assertIn("validation/run_local_release.py", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        rule = css.split(".request-scenario-summary{", 1)[1].split("}", 1)[0]
        for forbidden in ("-webkit-line-clamp", "max-height", "text-overflow"):
            self.assertNotIn(forbidden, rule)
        self.assertIn("overflow-wrap:anywhere", rule)
        self.assertIn(".violation-thresholds{display:inline-block;float:none;margin-left:14px;color:#0868d8;font-size:.9em;white-space:nowrap}", css)
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("declinedNoViolation:'Відхилено'", app)
        self.assertIn("function requestStatusClass(value){return value==='declinedNoViolation'?'declined':value}", app)
        self.assertIn("function zakupivliComplaintLink(item)", app)
        self.assertIn("/cabinet/ecatalog/gov/complaints/${id}", app)
        self.assertIn("!/^[a-f0-9]{24}$/i.test(id)", app)
        self.assertIn("class=\"violation-platform-heading\"", app)
        self.assertIn("requestLabel(c.contract_status,requestStatusLabels)", app)
        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("'table_widths_v11_tail.zip'", runner)
        self.assertNotIn("table_widths_ui.js", integrity.STABILIZATION_V4_PRODUCT_OVERRIDES)
        old = next(item for item in integrity.load_contracts()
                   if item["variant_id"] == integrity.STABILIZATION_V2_VARIANT_ID)
        old_widths = old["product_files"].get("table_widths_ui.js") or \
            old["guarded_files"].get("table_widths_ui.js") or old["protected_files"].get("table_widths_ui.js")
        self.assertIsNotNone(old_widths)
        self.assertEqual(integrity.sha256(integrity.canonical_content(
            "table_widths_ui.js", (ROOT / "table_widths_ui.js").read_bytes())),
                         old_widths["sha256"])

    def test_single_byte_mutation_of_each_v4_override_and_addition_is_rejected(self):
        current = next(item for item in integrity.load_contracts()
                       if item["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        paths = set(current["product_files"]) | set(current["guarded_files"]) | set(current["protected_files"])
        changed_paths = integrity.STABILIZATION_V4_PRODUCT_OVERRIDES | integrity.STABILIZATION_V4_PRODUCT_ADDITIONS
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in paths:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(current, tree))
            for relative in sorted(changed_paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(current, tree))


if __name__ == "__main__":
    unittest.main()
