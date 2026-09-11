import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent

class SupplierHistoryNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.history = (ROOT / "history_ui.js").read_text(encoding="utf-8")
        cls.navigation = (ROOT / "navigation.js").read_text(encoding="utf-8")

    def test_application_shortcut_uses_canonical_history_transition(self):
        self.assertIn('title="Всі заявки постачальника"', self.app)
        self.assertIn("openSupplierHistory(row.edrpou)", self.app)
        self.assertNotIn("tr.querySelector('.supplier-profile-open')", self.app)

    def test_supplier_card_requires_exact_explicit_code_scope(self):
        self.assertIn("function historySupplierCode()", self.history)
        self.assertIn("button.disabled=!code", self.history)
        self.assertIn("if(code)openSupplierProfile(code)", self.history)
        self.assertNotIn("historyItems[0]", self.history)

    def test_canonical_transition_normalizes_code(self):
        self.assertIn("String(code||'').trim()", self.history)
        self.assertIn("syncHistorySupplierCardButton();showModule('history')", self.history)

    def test_navigation_snapshot_keeps_current_application(self):
        self.assertIn("activeProfileId,activeRow,selected:[...selected]", self.navigation)
        self.assertIn("models.applications.set(clone(entry.model));render()", self.navigation)

if __name__ == "__main__":
    unittest.main()
