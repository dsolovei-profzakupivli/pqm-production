import copy
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
import schema_catalog
import template_catalog as t
import violation_protocol_docx as v

class TemplateCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=schema_catalog.catalog(Path(__file__).parent/'data/pqm.sqlite3')
    def test_unique_bindings_and_whitelists(self):
        data=t.load();fields=t.validate(data,self.schema)
        self.assertEqual(len(fields),len({f['key'] for f in fields}))
        self.assertFalse([f for f in fields if f['validation_errors']])
        self.assertEqual({f['key'] for f in fields if f['binding_status']=='PROPOSED_UNBOUND'},{'decision.url'})
        self.assertTrue(all('warning_block_protocol' in f['available_for'] for f in t.catalog(self.schema,'warning_block_protocol')['items']))
        self.assertFalse(any(f['key'].startswith('nazk.') for f in t.catalog(self.schema,'warning_block_protocol')['items']))
    def test_partial_ukrainian_search_all_four_attributes(self):
        for term,key in [('НАЗВА ПОСТАЧ','supplier.name'),('ПОПЕРЕДНЬОЇ ОСОБИ','manager.rnokpp'),('УПОВНОВАЖЕНА','uo.full_name'),('MANAGER.RNO','manager.rnokpp')]:
            self.assertIn(key,[f['key'] for f in t.catalog(self.schema,search=term)['items']])
    def test_broken_type_private_document_validation(self):
        for binding,typ,docs,expected in [
            ({'source_type':'schema_field','schema_field':'pqm.missing.field'},'string',[],'BROKEN_BINDING'),
            ({'source_type':'schema_field','schema_field':'pqm.supplier_managers.manager_name'},'integer',[],'INCOMPATIBLE_TYPE'),
            ({'source_type':'schema_field','schema_field':'pqm.amcu_registry.row_key'},'string',[],'PRIVATE_BINDING'),
            ({'source_type':'unbound'},'string',['invented'],'UNKNOWN_DOCUMENT_TYPE')]:
            data=t.load();data['fields'][0].update(source_binding=binding,value_type=typ,available_for=docs)
            self.assertIn(expected,' '.join(t.validate(data,self.schema)[0]['validation_errors']))
    def test_update_projection_audit_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.json';fixture=t.load();fixture['revision']=1;fixture['audit']=[]
            # This test isolates base-field editing; dependent fields have separate guards tests.
            fixture['fields']=[f for f in fixture['fields'] if not f['source_binding'].get('transformation_type')
                               and f['key']!='supplier.short_name']
            path.write_text(json.dumps(fixture),encoding='utf-8')
            sid='pqm.supplier_edr_profiles.full_name'
            def used():return next(x for x in t.project(copy.deepcopy(self.schema),t.load(path))['items'] if x['id']==sid)
            self.assertTrue(used()['used_in_templates'])
            for role in ('officer','viewer'):
                with self.assertRaises(PermissionError):t.update_field(self.schema,'supplier.name',{'active':False},'test',role,1,path)
            data=t.update_field(self.schema,'supplier.name',{'active':False},'Admin','admin',1,path)
            self.assertFalse(used()['used_in_templates']);self.assertEqual(data['audit'][0]['by'],'Admin')
            self.assertTrue(data['audit'][0]['old']['active']);self.assertFalse(data['audit'][0]['new']['active'])
            with self.assertRaises(ValueError):t.update_field(self.schema,'supplier.name',{'active':True},'Admin','admin',1,path)
            t.update_field(self.schema,'supplier.name',{'active':True,'available_for':['warning_block_protocol']},'Admin','admin',2,path)
            self.assertEqual(used()['document_types'],['warning_block_protocol'])
            t.update_field(self.schema,'supplier.name',{'source_binding':{'source_type':'schema_field','schema_field':'pqm.supplier_managers.manager_name'}},'Admin','admin',3,path)
            self.assertFalse(used()['used_in_templates'])
            t.update_field(self.schema,'supplier.name',{'source_binding':{'source_type':'schema_field','schema_field':'pqm.supplier_registry_summary.supplier_name'},'deprecated':True},'Admin','admin',4,path)
            self.assertFalse(used()['used_in_templates'])
    def test_nazk_supplier_code_label(self):
        self.assertEqual(t.supplier_code_label('44368854'),'код ЄДРПОУ')
        self.assertEqual(t.supplier_code_label('1234567890'),'РНОКПП')
        self.assertEqual(t.supplier_code_label('00123456'),'код ЄДРПОУ')
        self.assertEqual(t.supplier_code_label(''),'код ЄДРПОУ')
        self.assertEqual(t.supplier_code_label('123'),'код ЄДРПОУ')
        import server
        from document_semantics import supplier_code_label
        self.assertIs(t.supplier_code_label,supplier_code_label)
        self.assertIs(server.supplier_code_label,supplier_code_label)
        self.assertEqual(supplier_code_label('12 345-67890'),'РНОКПП')
        fields={f['key']:f for f in t.catalog(self.schema,'nazk_supplier_request')['items']}
        self.assertEqual(fields['supplier.code_label']['source_binding']['source_type'],'derived')
        self.assertEqual(fields['supplier.code_label']['binding_status'],'VALID')
        self.assertEqual(fields['supplier.code_label']['source_binding']['resolver'],'document_semantics.supplier_code_label')
        self.assertNotIn('supplier.address',fields)
        self.assertEqual(fields['supplier.email']['binding_status'],'VALID')
        self.assertEqual(fields['supplier.email']['required_for'],['nazk_supplier_request'])
    def test_supplier_entity_type_conditional_contract_bound(self):
        fields={f['key']:f for f in t.catalog(self.schema,'nazk_supplier_request')['items']}
        field=fields['supplier.entity_type']
        self.assertEqual(field['binding_status'],'VALID')
        self.assertEqual(field['source_binding']['source_type'],'derived')
        self.assertEqual(field['source_binding']['resolver'],'document_semantics.supplier_entity_type')
        self.assertEqual(field['value_type'],'enum')
        self.assertEqual(field['enum_values'],['legal_entity','individual_entrepreneur'])
        self.assertEqual(field['required_for'],['nazk_supplier_request'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.docx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{{supplier.entity_type}}</w:t></w:r></w:p></w:body></w:document>')
            report=t.scan_docx(path,list(fields.values()),'nazk_supplier_request')
            self.assertNotIn('supplier.entity_type',report['broken_bindings'])
            self.assertTrue(report['can_activate_canonical'])

    def test_shared_code_semantics(self):
        from document_semantics import supplier_code_semantics, supplier_code_label, supplier_entity_type
        for raw, normalized, label, entity in [
            ('1234567890','1234567890','РНОКПП','individual_entrepreneur'),
            ('44368854','44368854','код ЄДРПОУ','legal_entity'),
            ('12 345-67890','1234567890','РНОКПП','individual_entrepreneur'),
            ('44 368-854','44368854','код ЄДРПОУ','legal_entity'),
            ('','','код ЄДРПОУ','legal_entity'),
            ('123','123','код ЄДРПОУ','legal_entity')]:
            with self.subTest(raw=raw):
                result=supplier_code_semantics(raw)
                self.assertEqual(result,dict(normalized_code=normalized,code_label=label,entity_type=entity))
                self.assertEqual(supplier_code_label(raw),result['code_label'])
                self.assertEqual(supplier_entity_type(raw),result['entity_type'])

    def test_existing_templates_advisory_only_and_unchanged(self):
        fields=t.validate(t.load(),self.schema)
        for key,path in v.TEMPLATES.items():
            before=path.read_bytes();report=t.scan_docx(path,fields,t.RUNTIME_TYPES[key],key)
            self.assertTrue(report['legacy']);self.assertFalse(report['unknown']);self.assertEqual(before,path.read_bytes())
            self.assertFalse(report['can_activate_canonical'])
    def test_scanner_split_runs_unknown_unavailable_and_broken(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.docx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{{supplier.</w:t></w:r><w:r><w:t>name}} {{manager.full_name}} {{decision.date}} {{missing}}</w:t></w:r></w:p></w:body></w:document>')
            fields=t.validate(t.load(),self.schema);r=t.scan_docx(path,fields,'warning_block_protocol')
            self.assertIn('supplier.name',r['recognized']);self.assertIn('manager.full_name',r['unavailable'])
            self.assertEqual(r['unknown'],['missing']);self.assertIn('decision.date',r['unavailable'])
            self.assertNotIn('decision.date',r['broken_bindings'])
            self.assertFalse(r['can_activate_canonical'])

if __name__=='__main__':unittest.main()
