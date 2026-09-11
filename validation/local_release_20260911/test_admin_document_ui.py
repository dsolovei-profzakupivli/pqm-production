import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class AdminDocumentUiTests(unittest.TestCase):
    def test_template_and_metadata_sections_have_generic_search_and_collapse(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="adminTemplatesSection" class="card admin-config-section is-collapsed"', html)
        self.assertIn('id="adminTemplatesContent" hidden', html)
        self.assertIn('id="adminMetadataContent"', html)
        self.assertNotIn('id="adminMetadataContent" hidden', html)
        for control in ("adminTemplateSearch", "adminTemplatesToggle",
                        "adminMetadataSearch", "adminMetadataToggle"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn("function filterAdminTemplates()", script)
        self.assertIn("function filterAdminMetadata()", script)
        self.assertIn("function setAdminConfigExpanded(", script)

    def test_metadata_items_are_data_driven_and_individually_collapsible(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('(data.items||[]).map(item=>', script)
        self.assertIn('<details class="admin-metadata-item ${item.active?', script)
        self.assertIn('" open data-document-type="${esc(item.document_type)}"', script)
        self.assertIn('item.description', script)
        self.assertIn('...(item.used_fields||[])', script)
        self.assertIn('field.description,field.group,field.key', script)
        for action in ("data-metadata-insert", "data-metadata-validate", "data-metadata-save"):
            self.assertIn(action, script)


if __name__ == "__main__":
    unittest.main()
