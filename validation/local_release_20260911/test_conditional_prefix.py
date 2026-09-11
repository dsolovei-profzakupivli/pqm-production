import copy,json,tempfile,unittest
from pathlib import Path
import template_catalog as tc,derived_fields as df,schema_catalog

class ConditionalPrefixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'catalog.json';self.path.write_text(json.dumps(tc.load()),encoding='utf-8')
        self.schema=schema_catalog.catalog('data/pqm.sqlite3')
        self.payload=dict(key='supplier.test_display',label='Документна назва',source_field='supplier.name',
             transformation_type='conditional_prefix',condition_field='supplier.entity_type',equals='individual_entrepreneur',
             prefix='ФОП ',available_for=['nazk_supplier_request'],mode='create',revision=tc.load(self.path)['revision'])
    def test_save_reload_audit_and_resolve(self):
        data=tc.save_derived(self.schema,self.payload,'Test Admin','admin',self.path)
        self.assertEqual(data['audit'][-1]['key'],'supplier.test_display')
        fields=tc.validate(tc.load(self.path),self.schema)
        for kind,name,expected in [('individual_entrepreneur','БАБІЙ СЕРГІЙ ПЕТРОВИЧ','ФОП БАБІЙ СЕРГІЙ ПЕТРОВИЧ'),('legal_entity','ТОВАРИСТВО «ГУРКІТ ГРУП»','ТОВАРИСТВО «ГУРКІТ ГРУП»')]:
            values={'supplier.name':name,'supplier.entity_type':kind}
            result=df.resolve(['supplier.test_display'],fields,'nazk_supplier_request',lambda f:values[f['key']])
            self.assertEqual(result['supplier.test_display'],expected);self.assertEqual(result['supplier.name'],name)
        with self.assertRaises(ValueError):df.resolve(['supplier.test_display'],fields,'nazk_supplier_request',lambda f:'unknown')
        projected=tc.project(copy.deepcopy(self.schema),data)
        self.assertTrue(any(x['id']=='document_field.supplier.test_display' for x in projected['items']))
    def test_validation_and_permissions(self):
        for change in [{'equals':'unknown'},{'condition_field':'manager.rnokpp'},{'prefix':42},{'source_field':'supplier.test_display'}]:
            with self.assertRaises(ValueError):tc.save_derived(self.schema,{**self.payload,**change},'Test','admin',self.path)
        with self.assertRaises(PermissionError):tc.save_derived(self.schema,self.payload,'Viewer','viewer',self.path)

if __name__=='__main__':unittest.main()
