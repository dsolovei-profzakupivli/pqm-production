import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

import schema_catalog
import task_documents as td
import template_catalog
import template_runtime
import declension
from protocol_template import NS, paragraph_text


ROOT = Path(__file__).resolve().parents[2]
TASK_ID = 'b' * 32


def synthetic_schema(root):
    fields = template_catalog.load()['fields']
    columns = {}
    integer_columns = set()
    for field in fields:
        binding = field.get('source_binding', {})
        references = ([binding['schema_field']] if binding.get('source_type') == 'schema_field'
                      else binding.get('dependencies', []) if binding.get('source_type') == 'derived'
                      else [])
        for reference in references:
            parts = reference.split('.', 2)
            if len(parts) != 3 or parts[0] != 'pqm':
                continue
            _, table, column = parts
            columns.setdefault(table, set()).add(column)
            if field['value_type'] in {'integer', 'boolean'}:
                integer_columns.add((table, column))
    db = root / 'schema.sqlite'
    con = sqlite3.connect(db)
    for table, names in columns.items():
        definitions = []
        for column in sorted(names):
            kind = 'INTEGER' if (table, column) in integer_columns else 'TEXT'
            definitions.append('"' + column.replace('"', '""') + '" ' + kind)
        con.execute('CREATE TABLE "' + table.replace('"', '""') + '" (' + ','.join(definitions) + ')')
    con.commit()
    con.close()
    return schema_catalog.catalog(db)


def fixture(root, *, supplier_code='2343812174', manager_name='САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ',
            manager_tax_id='2343812174', supplier_name='ФОП САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ',
            edr_source='фоп', records=None):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.create_function('DIGITS', 1, lambda value: re.sub(r'\D', '', value or ''))
    con.executescript('''
      CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,status TEXT);
      CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY,task_id TEXT,event_type TEXT,created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
      CREATE TABLE operational_task_channels(task_id TEXT,channel TEXT);
      CREATE TABLE supplier_registry_summary(supplier_code TEXT,supplier_name TEXT);
      CREATE TABLE supplier_edr_profiles(supplier_code TEXT,full_name TEXT,short_name TEXT,manager_name TEXT,source_sheet TEXT);
      CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,manager_tax_id TEXT,is_current INTEGER,manager_tax_id_source TEXT,manager_tax_id_verified_at TEXT,manager_tax_id_verified_by TEXT,updated_at TEXT);
      CREATE TABLE submissions(id TEXT,supplier_code TEXT,supplier_name TEXT,date_published TEXT,synced_at TEXT,raw_json TEXT,framework_id TEXT);
      CREATE TABLE frameworks(id TEXT,pretty_id TEXT);
      CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT);
    ''')
    td.migrate(con)
    con.execute("INSERT INTO operational_tasks VALUES(?,'in_progress')", (TASK_ID,))
    con.execute('INSERT INTO supplier_registry_summary VALUES(?,?)', (supplier_code, supplier_name))
    con.execute('INSERT INTO supplier_edr_profiles VALUES(?,?,?,?,?)',
                (supplier_code, supplier_name, '', manager_name, edr_source))
    con.execute('''INSERT INTO supplier_managers
      (id,supplier_code,manager_name,manager_tax_id,is_current,manager_tax_id_source)
      VALUES(1,?,?,?,1,'synthetic_verified_fixture')''',
                (supplier_code, manager_name, manager_tax_id))
    con.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?)',
                ('1', supplier_code, supplier_name, '2026-10-01', '2026-10-01', '{}', 'f'))
    con.commit()
    item = {'id': TASK_ID, 'supplier_code': supplier_code, 'task_type': 'nazk_check',
            'status': 'in_progress', 'current_manager': {'id': 1, 'manager_name': manager_name},
            'task_person_is_current': True, 'effective_active_count': 1,
            'nazk_records': list(records or [{'source_id': 'test-1',
            'full_name': manager_name, 'offense_name': 'Подання завідомо недостовірних відомостей у декларації особи, уповноваженої на виконання функцій держави або місцевого самоврядування',
                'punishment': '', 'court_case_number': '131/42/26',
                'sentence_date': '2026-01-28', 'punishment_start': '2026-02-10',
                'sentence_number': '133719812', 'court_name': 'Іллінецький районний суд Вінницької області',
                'decision_url': 'https://reyestr.court.gov.ua/Review/133719812'}])}
    return con, item


class NazkAuthorityRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old_template_root = template_runtime.TEMPLATE_ROOT
        template_runtime.TEMPLATE_ROOT = self.root / 'runtime_templates'
        self.addCleanup(setattr, template_runtime, 'TEMPLATE_ROOT', old_template_root)
        self.schema = synthetic_schema(self.root)
        self.storage = self.root / 'documents'

    def generate(self, **kwargs):
        con, item = fixture(self.root, **kwargs)
        self.addCleanup(con.close)
        overrides = self.root / 'declension_overrides.csv'
        overrides.write_text(
            'entity_type;original;genitive;dative;accusative;comment\n'
            'person;САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ;Салія Володимира Миколайовича;;;\n',
            encoding='utf-8')
        with patch.object(declension, 'DEFAULT_OVERRIDE_STORE', declension.OverrideStore(overrides)):
            with con:
                con.execute('BEGIN IMMEDIATE')
                doc = td.generate_authority(con, item, self.schema, self.storage, 'Synthetic test')
        self.assertEqual(con.execute('SELECT status FROM operational_tasks WHERE id=?',
                                     (item['id'],)).fetchone()[0], 'in_progress')
        self.assertEqual(con.execute('SELECT COUNT(*) FROM operational_task_channels').fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events WHERE event_type='request_sent'").fetchone()[0], 0)
        self.assertEqual(con.execute('SELECT event_type FROM operational_task_events ORDER BY id DESC LIMIT 1').fetchone()[0],
                         'nazk_authority_request_generated')
        path, _ = td.download(con, item['id'], doc['id'], self.storage)
        with ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            root = etree.fromstring(archive.read('word/document.xml'))
            text = '\n'.join(paragraph_text(p) for p in root.xpath('.//w:p', namespaces=NS))
            relationships = archive.read('word/_rels/document.xml.rels').decode('utf-8')
        return con, item, doc, path, text, relationships

    def test_template_is_registered_and_conditional_variants_are_exact(self):
        fields = template_catalog.validate(template_catalog.load(), self.schema)
        report = template_runtime.validate_template(
            'nazk_authority_request', fields,
            template_runtime.SOURCE_TEMPLATE_ROOT / 'nazk_authority_request.docx')
        self.assertTrue(report['can_activate_canonical'], report)
        config = template_runtime.registered('nazk_authority_request')
        self.assertEqual(config['conditional_variants']['supplier.entity_type'],
                         ['individual_entrepreneur', 'legal_entity'])

    def test_fop_uses_approved_main_text_and_registry_fields_without_unresolved_tokens(self):
        _, _, _, _, text, rels = self.generate()
        self.assertIn('Салія Володимира Миколайовича', text)
        self.assertIn('2343812174', text)
        self.assertIn('подання завідомо недостовірних відомостей', text.casefold())
        self.assertIn('131/42/26', text)
        self.assertIn('28.01.2026', text)
        self.assertIn('10.02.2026', text)
        self.assertIn('Іллінецький районний суд Вінницької області', text)
        self.assertNotIn('{{', text)
        self.assertNotIn('керівника юридичної особи', text)
        self.assertNotIn('Відомості про пов’язаний запис Реєстру НАЗК', text)
        self.assertNotIn('ПІБ особи:', text)
        self.assertNotIn('Просимо перевірити наявність у Реєстрі інформації щодо особи, зазначеної нижче.', text)
        self.assertIn('Чи наявна в Реєстрі інформація стосовно Салія Володимира Миколайовича (РНОКПП: 2343812174) станом на дату надання відповіді на цей запит.', text)

    def test_removed_duplicate_registry_block_does_not_reappear_from_optional_fields(self):
        record = {'source_id': 'synthetic-record',
                  'full_name': 'САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ',
                  'punishment': 'СИНТЕТИЧНЕ СТЯГНЕННЯ',
                  'sentence_number': 'SYNTHETIC-DECISION-NUMBER',
                  'sentence_date': '2026-01-28',
                  'punishment_start': '2026-02-10'}
        _, _, _, _, text, rels = self.generate(records=[record])
        self.assertNotIn('СИНТЕТИЧНЕ СТЯГНЕННЯ', text)
        self.assertNotIn('SYNTHETIC-DECISION-NUMBER', text)
        self.assertNotIn('Посилання на судове рішення:', text)
        self.assertNotIn('https://', rels)
        self.assertNotIn('{{', text)

    def test_legal_entity_uses_synthetic_manager_and_supplier_genitive(self):
        _, _, _, _, text, _ = self.generate(
            supplier_code='45145640', manager_name='ІВАНЕНКО ОЛЕГ ПЕТРОВИЧ',
            manager_tax_id='3012345678', supplier_name='ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ТЕСТОВА ЗАКУПІВЛЯ»',
            edr_source='юридична особа',
            records=[{'source_id': 'synthetic-record', 'full_name': 'ІВАНЕНКО ОЛЕГ ПЕТРОВИЧ'}])
        self.assertIn('ІВАНЕНКА ОЛЕГА ПЕТРОВИЧА', text)
        self.assertIn('3012345678', text)
        self.assertIn('ТОВАРИСТВА З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ', text)
        self.assertIn('45145640', text)
        legal_sentence = ('Чи наявна, станом на дату надання відповіді на цей запит, у Реєстрі інформація '
                          'стосовно фізичної особи Іваненка Олега Петровича (РНОКПП: 3012345678), яка згідно '
                          'з інформацією в ЄДР є керівником постачальника Товариства з обмеженою '
                          'відповідальністю «Тестова закупівля» (ЄДРПОУ: 45145640).')
        self.assertIn(legal_sentence.casefold(), ' '.join(text.split()).casefold())
        self.assertNotIn('{{', text)

    def test_missing_or_invalid_rnokpp_blocks_without_creating_document_or_event(self):
        for value in ('', '12345678', '12345678901'):
            con, item = fixture(self.root, supplier_code='45145640',
                                manager_name='ІВАНЕНКО ОЛЕГ ПЕТРОВИЧ', manager_tax_id=value,
                                supplier_name='ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ТЕСТ»',
                                edr_source='юридична особа')
            with self.subTest(value=value), con:
                con.execute('BEGIN IMMEDIATE')
                with self.assertRaises(ValueError):
                    td.generate_authority(con, item, self.schema, self.storage, 'Synthetic test')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM generated_documents').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM operational_task_events').fetchone()[0], 0)
            con.close()

    def test_latest_linked_record_is_selected_by_decision_date_and_ambiguous_dates_fail_closed(self):
        older = {'source_id': 'z-old', 'full_name': 'САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ', 'sentence_date': '2026-01-01'}
        newer = {'source_id': 'a-new', 'full_name': 'САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ', 'sentence_date': '2026-02-01'}
        con, item = fixture(self.root, records=[older, newer])
        fields = template_catalog.validate(template_catalog.load(), self.schema)
        config = template_runtime.registered(td.AUTHORITY_KEY)
        values = td.resolve_context(con, item, fields, config, ['nazk.record.person_name'], td.AUTHORITY_KEY)
        self.assertEqual(values['nazk.record.person_name'], 'САЛІЙ ВОЛОДИМИР МИКОЛАЙОВИЧ')
        tied = dict(newer, source_id='z-new', sentence_date='2026-02-01', punishment_start='2026-02-12')
        newer['punishment_start'] = '2026-02-10'
        item['nazk_records'] = [newer, tied]
        selected = td._authority_record(item)
        self.assertEqual(selected['source_id'], 'z-new')
        same_date = dict(newer, source_id='other-id')
        item['nazk_records'] = [newer, same_date]
        with self.assertRaisesRegex(ValueError, 'дати пов’язаних записів збігаються'):
            td._authority_record(item)
        item['nazk_records'][0].pop('sentence_date')
        with self.assertRaisesRegex(ValueError, 'немає коректної дати'):
            td._authority_record(item)
        con.close()


if __name__ == '__main__':
    unittest.main()
