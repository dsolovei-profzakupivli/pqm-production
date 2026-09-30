import unittest
from pathlib import Path


class DeclensionNavigationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = Path(__file__).parent
        if not (cls.assets / "app.js").is_file():
            cls.assets = Path(__file__).parents[2]
        cls.app = (cls.assets / "app.js").read_text(encoding="utf-8")

    def test_blocker_offers_named_module_action_and_disables_generation(self):
        self.assertIn("Відкрити модуль відмінювання", self.app)
        self.assertIn("!ready.ready||unresolved.length?'disabled'", self.app)

    def test_late_declension_blocker_has_a_render_target(self):
        self.assertIn('id="violationProtocolReasons" hidden', self.app)
        self.assertIn("if(reasons){reasons.hidden=false", self.app)

    def test_validation_navigation_prefills_and_returns_to_same_report(self):
        self.assertIn("const entries=context.entries||[item]", self.app)
        self.assertIn("const pending=remainingDeclensionItems(entries)", self.app)
        self.assertIn("openDeclensionEditor(existing||{entity_type:target?.entity_type", self.app)
        self.assertIn("cases=matching.map(entry=>entry.grammatical_case)", self.app)
        self.assertIn("cases.includes(label.dataset.declensionCase)", self.app)
        self.assertIn("await openViolationReportById(context.reportId)", self.app)
        self.assertIn("unresolvedDeclensionsByReport.delete(String(context.reportId))", self.app)

    def test_customer_and_supplier_context_is_visible_in_editor(self):
        self.assertIn("requestContext?.subject_label", self.app)
        self.assertIn("requestContext?.entity_identifier", self.app)

    def test_shared_action_and_appeal_side_actions_keep_their_distinct_contracts(self):
        self.assertIn("Перевірити відмінювання",self.app)
        self.assertIn("data-amcu-declension",self.app)
        self.assertIn("data-nazk-declension",self.app)
        self.assertIn('data-check-declension-side="customer"',self.app)
        self.assertIn('data-check-declension-side="supplier"',self.app)
        self.assertIn("entry.status!=='resolved'",self.app)
        self.assertIn("originType:'operational_task'",self.app)

    def test_task_toolbar_reuses_module_and_returns_to_list(self):
        self.assertIn("originType:'operational_task_list'",self.app)
        self.assertIn("if(context.originType==='operational_task_list'){showModule('operationalTasks');return}",self.app)
        self.assertIn("taskDeclension.disabled=!(me.permissions?.['tasks.read']??admin)",self.app)
        html=(self.assets/'index.html').read_text(encoding='utf-8')
        self.assertIn('id="operationalTaskDeclension"',html)

    def test_appeals_toolbar_always_opens_persisted_declensions(self):
        html=(self.assets/'index.html').read_text(encoding='utf-8')
        self.assertLess(html.index('id="requestsDeclension"'),html.index('id="requestsTemplates"'))
        self.assertIn("$('#requestsDeclension').onclick=async()=>",self.app)
        self.assertIn("declensionReturnContext={originType:'violation_report_list'}",self.app)
        self.assertIn("await loadDeclensionOverrides()",self.app)
        self.assertIn("if(context.originType==='violation_report_list'){showModule('requests');return}",self.app)
        self.assertIn("declensionItems=data.items||[]",self.app)
        self.assertIn("$('#declensionGenitive').value=item?.genitive||''",self.app)
        self.assertIn("$('#declensionAccusative').value=item?.accusative||''",self.app)
        self.assertIn("data-declension-edit",self.app)
        self.assertIn("return html+violationDeclensionActions(declensions)+controls}",self.app)

    def test_appeals_status_uses_only_kpi_buttons_and_reason_is_preserved(self):
        html=(self.assets/'index.html').read_text(encoding='utf-8')
        self.assertIn('id="requestsStatus" hidden',html)
        self.assertIn('id="requestsReason"',html)
        self.assertIn("$('#requestQuickFilters').onclick=e=>",self.app)
        self.assertIn("status:$('#requestsStatus').value",self.app)
        self.assertIn("reason:$('#requestsReason').value",self.app)
        self.assertIn("populateRequestSelect('#requestsReason'",self.app)


if __name__ == "__main__":
    unittest.main()
