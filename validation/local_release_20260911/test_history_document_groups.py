import json
import subprocess
import unittest
from pathlib import Path

import server


class HistoryDocumentGroupsTests(unittest.TestCase):
    def setUp(self):
        self.supplier = [{"id": "supplier-sign", "title": "sign.p7s", "url": "https://docs/supplier-sign"}]
        self.decision = [
            {"id": "decision-protocol", "title": "Протокол.pdf", "url": "https://docs/decision-protocol"},
            {"id": "decision-sign", "title": "sign.p7s", "url": "https://docs/decision-sign"},
        ]
        self.registry = [{"documents": [
            self.decision[0],
            {"id": "registry-protocol", "title": "Протокол виключення.pdf", "url": "https://docs/registry-protocol"},
        ]}]

    def grouped(self, qualification_status="active", registry_status="terminated"):
        return server.grouped_application_documents(
            json.dumps(self.supplier), json.dumps(self.decision), json.dumps(self.registry),
            qualification_status, registry_status,
        )

    def test_groups_by_resource_relation_and_deduplicates(self):
        groups = self.grouped()
        self.assertEqual(["supplier-sign"], [x["id"] for x in groups["supplier"]])
        self.assertEqual(["decision-protocol", "decision-sign"], [x["id"] for x in groups["decision"]])
        self.assertEqual(["registry-protocol"], [x["id"] for x in groups["registry"]])

    def test_supplier_sign_stays_with_supplier_documents(self):
        self.assertEqual("sign.p7s", self.grouped()["supplier"][0]["title"])

    def test_registry_documents_only_for_inactive_admitted_application(self):
        self.assertEqual([], self.grouped(registry_status="active")["registry"])
        self.assertEqual([], self.grouped(qualification_status="unsuccessful")["registry"])
        self.assertEqual([], self.grouped(registry_status="suspended")["registry"])

    def test_history_row_style_uses_factual_states(self):
        source = Path("history_columns.js").read_text(encoding="utf-8")
        self.assertIn("x.status==='active'&&x.registry_status==='terminated'", source)
        self.assertIn('title="Неактивна допущена заявка"', source)

    def test_history_modal_preserves_all_three_named_groups(self):
        source = Path("app.js").read_text(encoding="utf-8")
        for label in ("Документи постачальника", "Документи розгляду заявки", "Документи реєстру"):
            self.assertIn(label, source)

    def test_registry_modal_splits_supplier_and_decision_documents(self):
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("supplierDocuments,decisionDocuments", source)
        self.assertIn("PqmApplicationDocuments.groups(row)", source)
        script = "const ui=require('./application_documents_ui.js');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(ui.groups(JSON.parse(s)))));"
        run = subprocess.run(['node', '-e', script], input=json.dumps({
            'supplierDocuments': self.supplier + self.supplier,
            'decisionDocuments': self.supplier + self.decision,
        }), cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True, check=True)
        grouped = json.loads(run.stdout)
        self.assertEqual([entry['document'] for entry in grouped['supplier']], self.supplier)
        self.assertEqual([entry['document'] for entry in grouped['decision']], self.decision)
        self.assertEqual([entry['index'] for entry in grouped['supplier']], [0])
        self.assertEqual([entry['index'] for entry in grouped['decision']], [1, 2])
        self.assertIn("openDocs(row,row.registryDocuments,'Документи рішення у реєстрі')", source)


if __name__ == "__main__":
    unittest.main()
