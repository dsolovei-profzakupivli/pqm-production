"""Current equivalent of the historical green-MVS acceptance: no seal checks."""
import unittest
from pathlib import Path
from validation.local_release_20260911 import test_contract_experience_search as original
import server


class CurrentMvsAcceptance(unittest.TestCase):
    setUp = original.OnDemandDocumentCheckTests.setUp
    tearDown = original.OnDemandDocumentCheckTests.tearDown
    mvs_extract = staticmethod(original.OnDemandDocumentCheckTests.mvs_extract)
    analyze_mvs = original.OnDemandDocumentCheckTests.analyze_mvs

    def test_valid_mvs_is_green_without_seal(self):
        result = self.analyze_mvs()
        self.assertEqual(server.document_check_category_summaries(result)['mvs'], 'ok')
        self.assertEqual(result['document_check_policy_version'], 2)
        self.assertEqual(len(result['checks']), 7)
        self.assertNotIn('mvs_seal', [item['key'] for item in result['checks']])
        self.assertEqual(result['counts'], {'ok': 7, 'warning': 0, 'error': 0, 'neutral': 0})

    def test_short_mvs_is_still_red(self):
        result = self.analyze_mvs('short')
        self.assertEqual(server.document_check_category_summaries(result)['mvs'], 'error')
        item = next(item for item in result['checks'] if item['key'] == 'mvs_extract_type')
        self.assertEqual(item['status'], 'error')

    def test_experience_uses_current_component_and_contract_links_not_ocr(self):
        app = Path('app.js').read_text(encoding='utf8')
        component = Path('document_check_ui.js').read_text(encoding='utf8')
        self.assertNotIn("['experience','Досвід']", app)
        self.assertIn("item.key==='contract_experience'", component)
        self.assertIn('PqmDocumentCheck.render(data,{esc,renderBusinessRows})', app)
        for text in ['row.url', 'contract-experience-marker', "found?'+':'−'",
                     "const labels={signature:'КЕП',mvs:'МВС'}", ' · не перевірено']:
            self.assertIn(text, app)
        self.assertNotIn("КЕП',mvs:'МВС',experience:'Договори", app)
