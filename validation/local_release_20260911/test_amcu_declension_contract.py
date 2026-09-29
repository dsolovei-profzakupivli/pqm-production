"""Template-driven AMKU declension checks without a PQM database fixture."""
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

import task_documents as td
import template_catalog
import template_runtime
from test_task_documents import fixture


class Unresolved:
    status = 'unresolved'
    source = 'missing'
    value = ''


class AmcuDeclensionContractTests(unittest.TestCase):
    def setUp(self):
        self.con, self.item = fixture()
        self.addCleanup(self.con.close)
        self.item.update(task_type='amcu_exclusion', status='ready_for_document',
                         amcu_decisions=[{'decision_no': '1', 'decision_date': '2026-09-28',
                                          'extract_url': 'https://example.test/decision'}])

    def assert_contract(self, keys):
        report = {'recognized': list(keys)}
        required = td.amcu_required_declension_keys(report)
        with patch.object(td, 'decline_name', return_value=Unresolved()), \
             patch.object(td, 'decline_short_name', return_value=Unresolved()):
            review = td.amcu_declension_review(self.con, self.item, required)
            with self.assertRaises(td.DeclensionRequired) as raised:
                td.resolve_amcu_protocol_context(self.con, self.item, {}, required)
            expected = [(entry['subject_label'], entry['grammatical_case']) for entry in review]
            generated = [(entry['subject_label'], entry['grammatical_case'])
                         for entry in raised.exception.unresolved]
            self.assertEqual(generated, expected)
            with patch.object(template_catalog, 'validate', return_value={}), \
                 patch.object(template_runtime, 'validate_template', return_value=report), \
                 patch.object(td, 'prepared_amcu', side_effect=raised.exception):
                readiness = td.amcu_readiness(self.con, self.item, {})
            self.assertEqual([(entry['subject_label'], entry['grammatical_case'])
                              for entry in readiness['declensions']], expected)
            self.assertEqual([(entry['subject_label'], entry['grammatical_case'])
                              for entry in readiness['unresolved']], expected)
            self.assertEqual(readiness['errors'], ['Потрібні перевірені відмінкові форми'])
        with patch.object(template_catalog, 'validate', return_value=[]), \
             patch.object(template_runtime, 'template_path', return_value=Path('templates/amcu_exclusion_protocol.docx')), \
             patch.object(template_runtime, 'validate_template', return_value=report), \
             patch.object(td, 'condition_keys', return_value=[]), \
             patch.object(td, 'resolve_amcu_protocol_context', return_value={}) as resolve, \
             patch.object(td.document_metadata, 'resolve_all', return_value={}):
            td.prepared_amcu(self.con, self.item, {})
        generator_keys = set(resolve.call_args.args[3])
        self.assertEqual(generator_keys & set(td.AMCU_SUPPLIER_DECLENSIONS), set(required))
        return required

    def test_full_name_genitive_and_accusative_only(self):
        required = self.assert_contract(('supplier.name_genitive', 'supplier.name_accusative'))
        self.assertEqual(required, ('supplier.name_genitive', 'supplier.name_accusative'))

    def test_short_name_genitive_is_required_only_when_used(self):
        required = self.assert_contract(('supplier.name_genitive', 'supplier.short_name_genitive'))
        self.assertEqual(required, ('supplier.name_genitive', 'supplier.short_name_genitive'))

    def test_full_name_dative_remains_required_if_template_uses_it(self):
        # A future approved field can enter the contract without a review-list edit.
        self.assertEqual(self.assert_contract(('supplier.name_dative',)), ('supplier.name_dative',))

    def test_active_source_template_has_four_forms_and_no_dative(self):
        document = Document('templates/amcu_exclusion_protocol.docx')
        text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
        keys = set(re.findall(r'\{\{\s*(supplier\.(?:name|short_name)_(?:genitive|dative|accusative))\s*\}\}', text))
        self.assertEqual(keys, {'supplier.name_genitive', 'supplier.name_accusative',
                                'supplier.short_name_genitive', 'supplier.short_name_accusative'})
        config = template_runtime.registered(td.AMCU_PROTOCOL_KEY)
        self.assertFalse(set(config['required_fields']) & set(td.AMCU_SUPPLIER_DECLENSIONS))
        self.assert_contract(keys)


if __name__ == '__main__':
    unittest.main()
