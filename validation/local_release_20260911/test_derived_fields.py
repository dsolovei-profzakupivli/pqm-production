import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from lxml import etree
import declension
import derived_fields as d
import template_catalog as t
import template_runtime
import task_documents as td
from test_task_documents import fixture
import schema_catalog
from protocol_template import NS, paragraph_text


class DerivedFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.schema=schema_catalog.catalog('data/pqm.sqlite3')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'catalog.json'
        self.path.write_text(json.dumps(t.load(),ensure_ascii=False),encoding='utf-8')
    def payload(self,**changes):
        return dict(key='manager.test_case',label='Тестове похідне поле',source_field='manager.full_name',
                    transformation_type='declension',grammatical_case='genitive',entity_type='person',
                    available_for=['nazk_supplier_request'],mode='create',revision=t.load(self.path)['revision'],**changes)
    def save(self,p,role='admin'):return t.save_derived(self.schema,p,'Test Admin',role,self.path)
    def test_create_edit_audit_reload_and_schema(self):
        data=self.save(self.payload());field=next(f for f in data['fields'] if f['key']=='manager.test_case')
        self.assertEqual(data['audit'][-1]['new'],field)
        self.assertEqual(data['audit'][-1]['by'],'Test Admin')
        p=self.payload();p.update(mode='update',label='Нова назва',grammatical_case='nominative')
        data=self.save(p);self.assertEqual(data['audit'][-1]['old']['label'],'Тестове похідне поле')
        revision=data['revision'];self.save(dict(p,revision=revision))
        self.assertEqual(t.load(self.path)['revision'],revision)
        projected=t.project(copy.deepcopy(self.schema),data)
        item=next(f for f in projected['items'] if f['id']=='document_field.manager.test_case')
        self.assertEqual(item['kind'],'derived');self.assertEqual(item['source_field'],'manager.full_name')
        self.assertEqual(item['transformation']['grammatical_case'],'nominative')
    def test_reject_unauthorized_collision_invalid_and_cycle(self):
        for role in ('officer','viewer'):
            with self.assertRaises(PermissionError):self.save(self.payload(),role)
        for change in ({'key':'manager.full_name'},{'key':'bad();'}, {'source_field':'manager.absent'},
                       {'transformation_type':'eval'}, {'grammatical_case':'fake'}, {'available_for':['unknown']},
                       {'source_field':'manager.rnokpp','available_for':['warning_notice']}, {'revision':-1}):
            p=self.payload();p.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.save(p)
        self.save(self.payload());p=self.payload();p.update(mode='update',source_field='manager.test_case')
        with self.assertRaisesRegex(ValueError,'CYCLIC'):self.save(p)
    def test_all_cases_and_source_unchanged(self):
        data=t.load(self.path);key='manager.full_name_genitive';original='КОВАЛЬСЬКА МАРІЯ ІВАНІВНА'
        f=next(f for f in data['fields'] if f['key']==key)
        for case in d.CASES:
            f['source_binding']['grammatical_case']=case;fields=t.validate(data,self.schema)
            if case in ('nominative','genitive','accusative'):
                values=d.resolve([key],fields,'nazk_supplier_request',lambda f:original)
                self.assertEqual(values['manager.full_name'],original)
                expected={'nominative':original,'genitive':'КОВАЛЬСЬКОЇ МАРІЇ ІВАНІВНИ','accusative':'КОВАЛЬСЬКУ МАРІЮ ІВАНІВНУ'}[case]
                self.assertEqual(values[key],expected)
            else:
                with self.assertRaisesRegex(ValueError,'Не визначено'):d.resolve([key],fields,'nazk_supplier_request',lambda f:original)
    def test_override_reload_shared_path_and_memoization(self):
        path=Path(self.tmp.name)/'overrides.csv'
        path.write_text('entity_type;original;genitive;dative;accusative;comment\nperson;ПІБ ОСОБИ;Ручна форма;;;;\n',encoding='utf-8-sig')
        store=declension.OverrideStore(path);fields=t.validate(t.load(),self.schema);calls=[]
        with patch.object(declension,'DEFAULT_OVERRIDE_STORE',store):
            for expected in ('Ручна форма','Інша ручна форма'):
                path.write_text('entity_type;original;genitive;dative;accusative;comment\nperson;ПІБ ОСОБИ;'+expected+';;;;\n',encoding='utf-8-sig')
                def base(f):calls.append(f['key']);return 'ПІБ ОСОБИ'
                values=d.resolve(['manager.full_name','manager.full_name_genitive'],fields,'nazk_supplier_request',base)
                self.assertEqual(values['manager.full_name_genitive'],expected)
        self.assertEqual(calls,['manager.full_name']*2)
    def test_runtime_resolves_arbitrary_configured_key_without_code(self):
        data=self.save(self.payload());fields=t.validate(data,self.schema)
        con,item=fixture();self.addCleanup(con.close)
        item['current_manager']['manager_name']='БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ'
        context=td.resolve_context(con,item,fields,{'required_fields':['manager.test_case']})
        self.assertEqual(context['manager.test_case'],'БОНДАРЯ СЕРГІЯ ВОЛОДИМИРОВИЧА')
        item['current_manager']['manager_name']='Ініціал'
        with self.assertRaisesRegex(ValueError,'Не визначено'):td.resolve_context(con,item,fields,{'required_fields':['manager.test_case']})
    def test_template_role_specific_tokens_and_rendering(self):
        with ZipFile(template_runtime.template_path(td.KEY)) as z:
            root=etree.fromstring(z.read('word/document.xml'))
            raw='\n'.join(paragraph_text(p) for p in root.xpath('.//w:p',namespaces=NS))
            self.assertEqual(raw.count('{{manager.full_name_genitive}}'),2)
            self.assertEqual(raw.count('{{manager.full_name}}'),1)
        for code in ('43897155','1234567890'):
            con,item=fixture(code);self.addCleanup(con.close)
            item['current_manager']['manager_name']='БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ'
            with con:
                con.execute('BEGIN IMMEDIATE');doc=td.generate(con,item,self.schema,self.tmp.name,'Test')
            path,_=td.download(con,item['id'],doc['id'],self.tmp.name)
            with ZipFile(path) as z:
                paragraphs=[paragraph_text(p) for p in etree.fromstring(z.read('word/document.xml')).xpath('.//w:p',namespaces=NS)]
                variant=next(p for p in paragraphs if p.startswith('З огляду на викладене'))
                search=next(p for p in paragraphs if 'за пошуковим запитом' in p)
                self.assertIn('БОНДАРЯ СЕРГІЯ ВОЛОДИМИРОВИЧА',variant)
                self.assertIn('БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ',search)
                self.assertNotIn('{{',''.join(paragraphs))


if __name__=='__main__':unittest.main()
