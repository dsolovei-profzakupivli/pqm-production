import unittest
from pathlib import Path


class DeclensionNavigationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (Path(__file__).with_name("app.js")).read_text(encoding="utf-8")

    def test_blocker_offers_named_module_action_and_disables_generation(self):
        self.assertIn("Відкрити модуль відмінювання", self.app)
        self.assertIn("!ready.ready||unresolved.length?'disabled'", self.app)

    def test_late_declension_blocker_has_a_render_target(self):
        self.assertIn('id="violationProtocolReasons" hidden', self.app)
        self.assertIn("if(reasons){reasons.hidden=false", self.app)

    def test_validation_navigation_prefills_and_returns_to_same_report(self):
        self.assertIn("openDeclensionEditor(existing||{entity_type:item?.entity_type", self.app)
        self.assertIn("item?.grammatical_case||'',item", self.app)
        self.assertIn("await openViolationReportById(context.reportId)", self.app)
        self.assertIn("remainingDeclensionItems(context.unresolved)", self.app)

    def test_customer_and_supplier_context_is_visible_in_editor(self):
        self.assertIn("requestContext?.subject_label", self.app)
        self.assertIn("requestContext?.entity_identifier", self.app)


if __name__ == "__main__":
    unittest.main()
