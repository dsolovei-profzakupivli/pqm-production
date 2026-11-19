from pathlib import Path
import unittest


class RequestAuthorityWrapperTests(unittest.TestCase):
    def test_override_targets_only_requests_wrapper_not_cards(self):
        css=Path('sandbox_theme.css').read_text(encoding='utf-8')
        rule='html[data-pqm-environment="sandbox"] #requestsView #requestAuthorityCards {background-color:transparent!important}'
        self.assertIn(rule,css)
        self.assertNotIn('button',rule)
        self.assertNotIn('halloween',rule)

    def test_existing_layout_and_card_styles_retained(self):
        css=Path('styles.css').read_text(encoding='utf-8')
        self.assertIn('.request-heading-actions .request-authority-cards{justify-content:flex-end;flex:1 1 auto',css)
        self.assertIn('.request-authority-card.active{background:',Path('modules.css').read_text(encoding='utf-8'))
        html=Path('index.html').read_text(encoding='utf-8')
        self.assertIn('id="requestAuthorityCards" class="request-authority-cards"',html)
