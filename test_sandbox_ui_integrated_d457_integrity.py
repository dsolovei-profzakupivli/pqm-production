"""Exact integrated UI/Admin integrity contract and one-byte rejection tests."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity


ROOT = integrity.ROOT


class IntegratedSandboxUiIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.contract = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        self.paths = set().union(*(set(self.contract[name]) for name in
                                   ("product_files", "protected_files", "guarded_files")))

    def test_exact_candidate_matches_and_historical_admin_contract_is_not_rewritten(self):
        self.assertEqual(self.contract["variant_id"], integrity.STABILIZATION_VARIANT_ID)
        self.assertEqual(self.contract["baseline_sha"], integrity.APPEALS_API_BASELINE)
        raw = integrity.UI_CANDIDATE_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), integrity.UI_CANDIDATE_DELTA_SHA256)
        v5_raw = integrity.UI_CANDIDATE_V5_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v5_raw).hexdigest(), integrity.UI_CANDIDATE_V5_DELTA_SHA256)
        v6_raw = integrity.UI_CANDIDATE_V6_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v6_raw).hexdigest(), integrity.UI_CANDIDATE_V6_DELTA_SHA256)
        v7_raw = integrity.UI_CANDIDATE_V7_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v7_raw).hexdigest(), integrity.UI_CANDIDATE_V7_DELTA_SHA256)
        v8_raw = integrity.UI_CANDIDATE_V8_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v8_raw).hexdigest(), integrity.UI_CANDIDATE_V8_DELTA_SHA256)
        v9_raw = integrity.UI_CANDIDATE_V9_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v9_raw).hexdigest(), integrity.UI_CANDIDATE_V9_DELTA_SHA256)
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.UI_CANDIDATE_V9_ID)))
        v10_raw = integrity.UI_CANDIDATE_V10_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v10_raw).hexdigest(), integrity.UI_CANDIDATE_V10_DELTA_SHA256)
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.UI_CANDIDATE_V10_ID)))
        v11_raw = integrity.UI_CANDIDATE_V11_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v11_raw).hexdigest(), integrity.UI_CANDIDATE_V11_DELTA_SHA256)
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.UI_CANDIDATE_V11_ID)))
        v12_raw = integrity.UI_CANDIDATE_V12_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v12_raw).hexdigest(), integrity.UI_CANDIDATE_V12_DELTA_SHA256)
        preview_raw = integrity.PREVIEW_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(preview_raw).hexdigest(), integrity.PREVIEW_CONTRACT_SHA256)
        integrated_raw = integrity.INTEGRATED_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(integrated_raw).hexdigest(), integrity.INTEGRATED_CONTRACT_SHA256)
        appeals_api_raw = integrity.APPEALS_API_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(appeals_api_raw).hexdigest(), integrity.APPEALS_API_CONTRACT_SHA256)
        scroll_raw = integrity.SCROLL_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(scroll_raw).hexdigest(), integrity.SCROLL_CONTRACT_SHA256)
        stabilization_raw = integrity.STABILIZATION_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(stabilization_raw).hexdigest(), integrity.STABILIZATION_CONTRACT_SHA256)
        integrated = next(c for c in integrity.load_contracts()
                          if c["variant_id"] == integrity.INTEGRATED_VARIANT_ID)
        self.assertFalse(integrity.manifest_tree_matches(integrated))
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.UI_CANDIDATE_V12_ID)))
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.PREVIEW_VARIANT_ID)))
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.SCROLL_VARIANT_ID)))
        self.assertFalse(integrity.manifest_tree_matches(next(c for c in integrity.load_contracts()
                                                               if c["variant_id"] == integrity.APPEALS_API_VARIANT_ID)))
        self.assertTrue(integrity.manifest_tree_matches(self.contract))
        self.assertTrue(integrity.exact_variant_tree_matches())
        previous_v2 = next(c for c in integrity.load_contracts()
                           if c["variant_id"] == integrity.UI_CANDIDATE_V2_ID)
        v2_raw = integrity.UI_CANDIDATE_V2_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(v2_raw).hexdigest(), integrity.UI_CANDIDATE_V2_DELTA_SHA256)
        self.assertEqual("f15ba9d14a52f131e7a2b1d9e84ea920667dfeefe4143ef27266d7d4c4795521",
                         previous_v2["product_files"]["validation/sandbox_editable_smoke.py"]["sha256"])
        self.assertFalse(integrity.manifest_tree_matches(previous_v2))
        previous = next(c for c in integrity.load_contracts()
                        if c["variant_id"] == "sandbox-admin-officer-link-v3")
        self.assertFalse(integrity.manifest_tree_matches(previous))
        historical_v1 = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.UI_CANDIDATE_ID)
        self.assertEqual(historical_v1["baseline_sha"], "d457aae211bc0b88cdc66414b9e5765ac7ba350d")
        self.assertNotEqual(historical_v1["baseline_sha"], self.contract["baseline_sha"])
        self.assertFalse(integrity.manifest_tree_matches(historical_v1))
        historical_v4 = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.UI_CANDIDATE_V4_ID)
        self.assertFalse(integrity.manifest_tree_matches(historical_v4))
        historical_v5 = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.UI_CANDIDATE_V5_ID)
        self.assertFalse(integrity.manifest_tree_matches(historical_v5))
        historical_v6 = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.UI_CANDIDATE_V6_ID)
        self.assertFalse(integrity.manifest_tree_matches(historical_v6))
        for path in self.paths:
            self.assertTrue(integrity.exact_variant_file_matches(path, (ROOT / path).read_bytes()), path)

    def test_every_single_byte_product_guard_and_protected_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temp:
            tree = Path(temp)
            for path in self.paths:
                target = tree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(self.contract, tree))
            for path in sorted(self.paths):
                with self.subTest(path=path):
                    target = tree / path
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if changed:
                        changed[0] ^= 1
                    else:
                        changed.extend(b"!")
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(self.contract, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(self.contract, tree))

    def test_candidate_scope_is_exact_and_historical_manifests_are_untouched(self):
        expected = (integrity.UI_CANDIDATE_PRODUCTS | integrity.UI_CANDIDATE_V2_PRODUCT_ADDITIONS |
                    integrity.UI_CANDIDATE_V2_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V3_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V4_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V5_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V6_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V7_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V8_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V9_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V10_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V11_PRODUCT_OVERRIDES |
                    integrity.UI_CANDIDATE_V12_PRODUCT_OVERRIDES | integrity.PREVIEW_PRODUCTS |
                    integrity.APPEALS_API_PRODUCT_OVERRIDES | integrity.APPEALS_API_PRODUCT_ADDITIONS |
                    integrity.SCROLL_PRODUCTS | integrity.STABILIZATION_PRODUCT_OVERRIDES |
                    integrity.STABILIZATION_PRODUCT_ADDITIONS |
                    integrity.STABILIZATION_V2_PRODUCT_ADDITIONS |
                    integrity.STABILIZATION_V3_PRODUCT_ADDITIONS |
                    integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                    integrity.STABILIZATION_V4_PRODUCT_ADDITIONS |
                    integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                    integrity.STABILIZATION_V5_PRODUCT_ADDITIONS |
                    {"validation/fixtures/appeals_scenario_v11_tail.zip"})
        self.assertEqual(set(self.contract["product_files"]), expected)
        self.assertEqual(set(self.contract["approved_scope"]) - set(
            next(c for c in integrity.load_contracts()
                 if c["variant_id"] == "sandbox-admin-officer-link-v3")["approved_scope"]),
            integrity.UI_CANDIDATE_SCOPE | integrity.UI_CANDIDATE_V2_SCOPE |
            integrity.UI_CANDIDATE_V3_SCOPE | integrity.UI_CANDIDATE_V4_SCOPE |
            integrity.UI_CANDIDATE_V5_SCOPE | integrity.UI_CANDIDATE_V6_SCOPE |
            integrity.UI_CANDIDATE_V7_SCOPE | integrity.UI_CANDIDATE_V8_SCOPE |
            integrity.UI_CANDIDATE_V9_SCOPE | integrity.UI_CANDIDATE_V10_SCOPE |
            integrity.UI_CANDIDATE_V11_SCOPE | integrity.UI_CANDIDATE_V12_SCOPE |
            integrity.PREVIEW_SCOPE | integrity.INTEGRATED_SCOPE | integrity.APPEALS_API_SCOPE |
            integrity.SCROLL_SCOPE | integrity.STABILIZATION_SCOPE | integrity.STABILIZATION_V2_SCOPE |
            integrity.STABILIZATION_V3_SCOPE | integrity.STABILIZATION_V4_SCOPE |
            integrity.STABILIZATION_V5_SCOPE)
        for path in (integrity.ADMIN_HISTORY_CONTRACT, integrity.ADMIN_CONTRACT,
                     integrity.ADMIN_V3_DELTA):
            self.assertTrue(path.is_file())

    def test_appeals_browser_regressions_run_required_on_recorded_ci_checkout(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        docker_gate = (ROOT / "validation/docker_release_gate.py").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("playwright@1.62.1", workflow)
        self.assertIn("playwright\" install --with-deps chromium", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$(cat ci-evidence/tested-sha.txt)"', workflow)
        self.assertIn("ROOT/'.github/workflows/release-checks.yml'", local_runner)
        scripts = (
            "appeals_justification_browser.cjs",
            "appeals_declension_card_browser.cjs",
            "protocol_names_card_browser.cjs",
        )
        for script in scripts:
            with self.subTest(script=script):
                source = (ROOT / "validation" / script).read_text(encoding="utf-8")
                self.assertIn("require('playwright')", source)
                self.assertNotIn("C:/Users/", source)
                self.assertIn(f"node validation/{script}", workflow)
                self.assertNotIn(script, docker_gate)
        supplier_ux = (ROOT / "validation/sandbox_supplier_ux.cjs").read_text(encoding="utf-8")
        self.assertIn("currentMe:null", supplier_ux)
        self.assertIn("the real application initializes currentMe to null before authentication", supplier_ux)
        self.assertIn("[['admin',true],['officer',true],['viewer',false]]", supplier_ux)
        self.assertIn("save visibility follows declension.manage", supplier_ux)

    def test_declension_save_fixture_models_read_only_state_and_permission_gate(self):
        vm_test = (ROOT / "validation/appeals_declension_ui.cjs").read_text(encoding="utf-8")
        self.assertIn("declensionEditorReadOnly:false", vm_test)
        self.assertIn("declensionEditorReadOnly=true", vm_test)
        self.assertIn("read-only editor must not send a save request", vm_test)
        browser_test = (ROOT / "validation/appeals_declension_card_browser.cjs").read_text(encoding="utf-8")
        self.assertIn("async function setRole(role,canManage=role!=='viewer')", browser_test)
        self.assertIn("await setRole(role,false)", browser_test)
        self.assertIn("direct save call is blocked without declension.manage", browser_test)


if __name__ == "__main__":
    unittest.main()
