import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from schema_catalog import catalog, REGISTRY


class SchemaCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.db'
        with closing(sqlite3.connect(self.db)) as c:
            c.executescript("""CREATE TABLE frameworks(id TEXT PRIMARY KEY);
            CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT REFERENCES frameworks(id),supplier_code INTEGER,new_business_date TEXT,password_hash TEXT DEFAULT 'SECRET_DEFAULT');
            INSERT INTO submissions(id,supplier_code,password_hash) VALUES('PRIVATE_RECORD',123,'PRIVATE_HASH');
            CREATE TABLE application_fields(document_check_result_json TEXT);
            INSERT INTO application_fields VALUES('{"secret":"PRIVATE_JSON"}');""")
            c.commit()
    def tearDown(self):self.tmp.cleanup()
    def test_actual_structure_no_values_or_defaults_no_writes(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest();r=catalog(self.db)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        serial=json.dumps(r)
        for secret in ['PRIVATE_RECORD','PRIVATE_HASH','SECRET_DEFAULT','PRIVATE_JSON']:self.assertNotIn(secret,serial)
        code=next(x for x in r['items'] if x['id']=='pqm.submissions.supplier_code')
        self.assertEqual(code['type'],'INTEGER');self.assertFalse(code['technical'])
        self.assertNotEqual(code['source'],'SQLite PRAGMA table_info')
    def test_new_field_visible_unapproved(self):
        r=catalog(self.db);field=next(x for x in r['items'] if x['key']=='new_business_date')
        self.assertEqual(field['status'],'unapproved');self.assertFalse(field['technical'])
    def test_fk_and_logical_are_distinct(self):
        links=catalog(self.db)['relationships'];self.assertTrue(any(x['kind']=='fk' for x in links));self.assertTrue(any(x['kind']=='logical' for x in links))
    def test_json_and_derived_not_fake_columns(self):
        r=catalog(self.db);self.assertTrue(any(x['kind']=='json' for x in r['items']));self.assertTrue(any(x['kind']=='derived' for x in r['items']))
        self.assertTrue(r['missing_metadata_fields'])
    def test_missing_optional_bids_is_not_empty_database(self):
        r=catalog(self.db,Path(self.tmp.name)/'absent.db');self.assertFalse(r['stores'][1]['available']);self.assertTrue(r['warnings'])
    def test_registry_is_draft_regulatory_metadata_not_rules(self):
        r=json.loads(REGISTRY.read_text(encoding='utf-8'));self.assertEqual(len(r['groups']),9)
        self.assertFalse(any(x['status']=='approved' for x in r['fields'].values()))
        self.assertTrue(any(x.get('regulatory') for x in r['fields'].values()))
        self.assertEqual({x['mode'] for x in r['flows']},{'automatic','officer','manual','unconfirmed','planned'})
    def test_registry_does_not_execute_or_import_server(self):
        text=Path(__file__).with_name('schema_catalog.py').read_text(encoding='utf-8')
        self.assertNotIn('import server',text);self.assertNotIn('SELECT *',text)

if __name__=='__main__':unittest.main()
