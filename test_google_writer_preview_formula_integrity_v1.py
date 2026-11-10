"""Additive integrity overlay for formula-only Preview display masking."""
import hashlib
import re
from pathlib import Path
import unittest


SELF_SHA256 = "c1a9b177228e6d1b4feda6ea659474ca1d0d5e1c87cb3f1da51019871165f20c"
SOURCE_SHA256 = {
    "google_writer_ui.js": "6fd12bf949a8d0877a2e777e732247c20ba7700ffeb051c6590bed340e3116ae",
    "scripts/pqm-google-writer/mirror-alignment/preview-formula-display.test.cjs": "2f033b4275e65ef0540affce2cbc6c4709e18f7fc9f65c3482d8d7795dccd534",
    "validation/legacy_snapshots/google_writer_ui_admin_close_v1.js": "49864f96fbab0ea7119bd18c6df291b8ed3efa560ce128ac8db0b2ed92b30e7a",
}
PRESERVED_SHA256 = {
    "validation/sandbox_preview_append_only_v1.json": "a6b8a92df5f267ff0846e099a7190424644fa65273b07fcc9177ee292e9b65fd",
    "validation/local_release_20261109/google_writer_all_scope_receipt_recovery_v1.json": "72c63161435081aec44f98a4605338bd9263afc9064614bce931caa3e43a0fa6",
    "supplier_classification_contract_v1.json": "dd8e2d375b0ea0c6d7fb46715d33170f55eaa842c74535d12d2f00fe39da46d2",
    "test_sandbox_messages_integrity_v1.json": "1bb3bdbe99b3f041b6bc6dbdfaf4768a5b21f75c84d7f4a6a61351726a731143",
    "test_sandbox_messages_crlf_integrity_v2.json": "15d9706e4282c8ef799c468e93b855e27b657310fe1cb17a874fd27b13a05996",
}


def canonical(raw):
    return raw.replace(b"\r\n", b"\n")


def self_digest(raw):
    normalized = re.sub(rb'(?m)^SELF_SHA256 = "(?:<self-sha256>|[0-9a-f]{64})"$',
                        b'SELF_SHA256 = "<self-sha256>"', canonical(raw))
    return hashlib.sha256(normalized).hexdigest()


class GoogleWriterPreviewFormulaIntegrityTests(unittest.TestCase):
    def test_new_overlay_pins_current_ui_and_ui_mock_test(self):
        root = Path(__file__).resolve().parent
        self.assertEqual(self_digest(Path(__file__).read_bytes()), SELF_SHA256)
        for relative, expected in SOURCE_SHA256.items():
            with self.subTest(source=relative):
                self.assertEqual(hashlib.sha256(canonical((root / relative).read_bytes())).hexdigest(), expected)

    def test_historical_integrity_ledgers_remain_unchanged(self):
        root = Path(__file__).resolve().parent
        for relative, expected in PRESERVED_SHA256.items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((root / relative).read_bytes())).hexdigest(), expected)

    def test_formula_masking_is_limited_to_cell_value_display(self):
        source = (Path(__file__).resolve().parent / "google_writer_ui.js").read_text(encoding="utf-8")
        self.assertIn("function googleWriterPreviewHasFormula(value)", source)
        self.assertIn("return esc('Формула')", source)
        self.assertIn("googleWriterPreviewCellValueHtml(cell.old_value)", source)
        self.assertIn("googleWriterPreviewCellValueHtml(cell.new_value)", source)
        self.assertIn("googleWriterPreviewValueHtml(item.name)", source)
        self.assertIn("esc(item.code||'')", source)


if __name__ == "__main__":
    unittest.main()
