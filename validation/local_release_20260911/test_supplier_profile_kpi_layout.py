import unittest
from pathlib import Path


class SupplierProfileKpiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        if not (root / "app.js").is_file():
            root = Path(__file__).parents[2]
        cls.app = (root / "app.js").read_text(encoding="utf-8")
        cls.styles = (root / "styles.css").read_text(encoding="utf-8")

    def test_detached_kpis_size_to_content_and_can_wrap(self):
        selector = '#supplierProfileDialog[data-detail-window="floating"] #supplierProfileBody .supplier-profile-stats'
        self.assertIn(selector + '{display:flex;flex-wrap:wrap;align-items:stretch', self.styles)
        self.assertIn('flex:0 1 auto;width:max-content', self.styles)
        self.assertNotIn(selector + '{display:grid', self.styles)

    def test_qualification_status_is_a_chip_with_neutral_date(self):
        section = self.app.split('<h3>Кваліфікації за відборами</h3>', 1)[1].split('<h3>Звернення замовників', 1)[0]
        self.assertIn('<th>Кваліфікація</th>', section)
        self.assertNotIn('<th>Чинна кваліфікація</th>', section)
        self.assertIn('supplier-qualification-badge ${q.status===\'active\'?\'active\':\'inactive\'}', section)
        self.assertIn('supplier-qualification-badge.active{background:#dff5e9', self.styles)
        self.assertIn('supplier-qualification-badge.inactive{background:#edf0f3', self.styles)
        self.assertIn('q.event_date?`<small>${esc(displayDate(q.event_date))}</small>`', section)


if __name__ == "__main__":
    unittest.main()
