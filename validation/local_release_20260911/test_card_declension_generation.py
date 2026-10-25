import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import declension
import server
from declension import OverrideStore
from declension_overrides import save_override


class CardDeclensionGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_db = server.DB_PATH
        self.old_db_function = server.db
        self.connections = []
        server.DB_PATH = self.root / 'synthetic.sqlite3'
        def tracked_db():
            connection = self.old_db_function()
            self.connections.append(connection)
            return connection
        server.db = tracked_db
        server.init_db()
        server.save_violation_report({
            'id': 'card-declension-internal', 'violationReportID': 'UA-D-CARD-DECLENSION',
            'status': 'pending', 'datePublished': '2026-10-01T10:00:00+03:00',
            'tender_id': 'tender-card',
            'author': {'identifier': {'id': '11111111'}, 'name': 'Замовник'},
            'defendants': [{'identifier': {'id': '2222222222'}, 'name': 'Постачальник'}],
            'authority': {'identifier': {'id': '40996564'}, 'name': 'Орган'},
            'details': {'reason': 'contractBreach'}, 'decisions': [],
        })

    def tearDown(self):
        server.db = self.old_db_function
        for connection in self.connections:
            connection.close()
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_saved_card_forms_flow_into_new_docx_and_its_pdf_source(self):
        override_path = self.root / 'declension_overrides.csv'
        rows = [
            {'entity_type': 'legal_entity', 'original': 'ТОВАРИСТВО «КАРТКА»',
             'genitive': 'ВИПРАВЛЕНА НАЗВА ЗАМОВНИКА', 'dative': '', 'accusative': '', 'comment': 'test'},
            {'entity_type': 'fop', 'original': 'ФОП ПЕТРЕНКО ОЛЕНА ІВАНІВНА',
             'genitive': 'ВИПРАВЛЕНА НАЗВА ПОСТАЧАЛЬНИКА', 'dative': 'ДОПОМІЖНА ФОРМА',
             'accusative': 'ЗНАХІДНА ФОРМА', 'comment': 'test'},
        ]
        for row in rows:
            save_override(row, path=override_path)
        store = OverrideStore(override_path)
        item = {
            'id': 'card-declension-internal', 'report_id': 'UA-D-CARD-DECLENSION',
            'reason': 'contractBreach', 'date_published': '2026-10-01T10:00:00+03:00',
            'author_name': rows[0]['original'], 'author_code': '11111111',
            'defendant_name': rows[1]['original'], 'defendant_code': '2222222222',
            'supplier_verified': None, 'protocol_supplier_names': None,
            'review': {'customer_verified_full_name': rows[0]['original'], 'internal_decision': 'warning',
                       'assigned_officer': 'Тестова УО', 'decision_justification': 'Синтетичний текст'},
            'procurement_context': {'available': True}, 'deadline_control': {},
            'evidence_documents': [], 'defendant_statements': [], 'description': 'Синтетичне звернення',
        }
        gate = {'ready': True, 'reasons': [], 'protocol_type': 'warning',
                'protocol_number': 'SYN-CARD', 'protocol_date': '2026-10-25'}
        captured = {}

        def render_docx(_kind, path, values, *_args):
            captured.update(values)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic-docx-from-saved-declensions')
            return path

        protocols = self.root / 'protocols'
        with patch.object(declension, 'DEFAULT_OVERRIDE_STORE', store), \
                patch.object(server, 'require_local_violation_report_owned'), \
                patch.object(server, 'require_owned_violation_report'), \
                patch.object(server, 'violation_report_detail', return_value=item), \
                patch.object(server, 'violation_protocol_readiness', return_value=gate), \
                patch.object(server, '_violation_publication_document_metadata', return_value={'date': '2026-10-01'}), \
                patch.object(server, '_violation_protocol_filename', return_value='synthetic-protocol.docx'), \
                patch.object(server, '_resolve_violation_protocol_metadata', return_value={}), \
                patch.object(server, 'PROTOCOLS_DIR', protocols), \
                patch.object(server, 'build_violation_protocol_docx', side_effect=render_docx):
            result = server.generate_violation_protocol(item['id'], {
                'protocol_number': gate['protocol_number'], 'protocol_date': gate['protocol_date']})

        self.assertEqual(captured['customer_name_genitive'], rows[0]['genitive'])
        self.assertEqual(captured['supplier_name_genitive'], rows[1]['genitive'])
        docx_path = protocols / result['filename']
        self.assertTrue(docx_path.is_file())
        pdf_capture = {}

        def convert_pdf(source, destination):
            pdf_capture['source'] = Path(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'synthetic-pdf-from-current-docx')
            return destination

        with patch.object(server, 'PROTOCOLS_DIR', protocols), \
                patch.object(server.protocol_pdf, 'ensure_pdf', side_effect=convert_pdf):
            pdf_path, _ = server.violation_protocol_pdf(item['id'])
        self.assertEqual(pdf_capture['source'], docx_path)
        self.assertTrue(pdf_path.is_file())


if __name__ == '__main__':
    unittest.main()
