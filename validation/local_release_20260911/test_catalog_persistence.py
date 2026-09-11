import json,tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import schema_catalog,template_catalog as t

class CatalogPersistenceTests(unittest.TestCase):
    def test_concurrent_revision_and_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.json';path.write_text(json.dumps(t.load(),ensure_ascii=False),encoding='utf-8')
            schema=schema_catalog.catalog('data/pqm.sqlite3');before=t.load(path)
            def save(i):
                try:
                    t.save_derived(schema,dict(key='supplier.persistence_test',label='Перевірка',source_field='supplier.name',transformation_type='declension',grammatical_case='genitive',entity_type='legal_entity',available_for=['nazk_supplier_request'],mode='create',revision=before['revision']),'Test Admin','admin',path)
                    return 'saved'
                except ValueError:return 'conflict'
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(save,range(4)))
            self.assertEqual(results.count('saved'),1)
            after=t.load(path);self.assertEqual(after['revision'],before['revision']+1)
            self.assertEqual(len(after['audit']),len(before['audit'])+1)
            self.assertEqual(after['fields'][:-1],before['fields'])
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(save(5),'conflict');self.assertEqual(t.load(path),after)

if __name__=='__main__':unittest.main()
