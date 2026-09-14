import copy
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
import template_catalog
import template_runtime
import task_documents as td
import document_metadata as dm
from protocol_template import NS,paragraph_text


def fixture(code='43897155'):
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    con.create_function('DIGITS',1,lambda s:re.sub(r'\D','',s or ''))
    con.executescript('''CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,status TEXT);
    CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY,task_id TEXT,event_type TEXT,created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
    CREATE TABLE operational_task_channels(task_id TEXT,channel TEXT);
    CREATE TABLE supplier_registry_summary(supplier_code TEXT,supplier_name TEXT);
    CREATE TABLE supplier_edr_profiles(supplier_code TEXT,full_name TEXT,short_name TEXT,manager_name TEXT,source_sheet TEXT);
    CREATE TABLE supplier_managers(
      id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,manager_tax_id TEXT,
      is_current INTEGER,manager_tax_id_source TEXT,manager_tax_id_verified_at TEXT,
      manager_tax_id_verified_by TEXT,updated_at TEXT);
    CREATE TABLE submissions(id TEXT,supplier_code TEXT,supplier_name TEXT,date_published TEXT,synced_at TEXT,raw_json TEXT,framework_id TEXT);
    CREATE TABLE frameworks(id TEXT,pretty_id TEXT);''')
    td.migrate(con)
    tid='a'*32
    con.execute("INSERT INTO operational_tasks VALUES(?,'in_progress')",(tid,))
    supplier_name=('БАБІЙ СЕРГІЙ ПЕТРОВИЧ' if len(re.sub(r'\D','',code))==10 else
                   'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "КОНТРОЛЬ"')
    con.execute('INSERT INTO supplier_registry_summary VALUES(?,?)',(code,supplier_name))
    con.execute('INSERT INTO supplier_managers(id,supplier_code,manager_name,manager_tax_id,is_current) VALUES(1,?,?,?,1)',
                (code,'КОНТРОЛЬНИЙ КЕРІВНИК','3011007819'))
    for i,email in ((1,'old@example.com'),(2,'fixture@example.com')):
        con.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?,?)',(str(i),code,supplier_name,f'2026-09-0{i}',f'2026-09-0{i}',json.dumps({'tenderers':[{'contactPoint':{'email':email}}]}),'f'))
    con.commit()
    item={'id':tid,'supplier_code':code,'task_type':'nazk_check','status':'in_progress',
          'current_manager':{'id':1,'manager_name':'КОНТРОЛЬНИЙ КЕРІВНИК'},'task_person_is_current':True,
          'effective_active_count':1,'nazk_records':[{'source_id':'fixture'}]}
    return con,item


class TaskDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.schema=schema_catalog.catalog('data/pqm.sqlite3')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.con,self.item=fixture();self.addCleanup(self.con.close)
        self.out=Path(self.temp.name)/'documents'

    def generate(self):
        with self.con:
            self.con.execute('BEGIN IMMEDIATE')
            return td.generate(self.con,self.item,self.schema,self.out,'Test UO')

    def test_legal_and_fop_actual_template(self):
        for code,kind in [('43897155','legal_entity'),('1234567890','individual_entrepreneur')]:
            con,item=fixture(code)
            if kind=='individual_entrepreneur':
                con.execute('INSERT INTO supplier_edr_profiles VALUES(?,?,?,?,?)',
                  (code,'ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ БАБІЙ СЕРГІЙ ПЕТРОВИЧ','ФОП БАБІЙ С.П.',
                   'КОНТРОЛЬНИЙ КЕРІВНИК','ФОП'))
                con.commit()
            with con:
                con.execute('BEGIN IMMEDIATE')
                doc=td.generate(con,item,self.schema,self.out,'Test UO')
            summary=doc['metadata']['askod_short_summary']['value']
            self.assertEqual(summary.startswith('Запит до ФОП БАБІЙ С.П.'),kind=='individual_entrepreneur')
            path,_=td.download(con,item['id'],doc['id'],self.out)
            with ZipFile(path) as z:
                self.assertIsNone(z.testzip())
                text='\n'.join(paragraph_text(p) for p in etree.fromstring(z.read('word/document.xml')).xpath('.//w:p',namespaces=NS))
                self.assertNotIn('{{',text);self.assertNotIn('}}',text)
                self.assertEqual(text.count('З огляду на викладене'),1)
                self.assertEqual('стосовно керівника' in text,kind=='legal_entity')
                self.assertIn('fixture@example.com',text);self.assertNotIn('old@example.com',text)
                self.assertIn('На №',text);self.assertIn('Світлана НАМЯСЕНКО',text)
                with ZipFile(template_runtime.template_path(td.KEY)) as src:
                    for part in src.namelist():
                        if part!='word/document.xml':self.assertEqual(z.read(part),src.read(part))
            con.close()

    def test_version_history_and_no_direction_or_status_changes(self):
        one=self.generate();first=td.download(self.con,self.item['id'],one['id'],self.out)[0].read_bytes()
        two=self.generate()
        self.assertNotEqual(one['id'],two['id']);self.assertNotEqual(one['filename'],two['filename'])
        self.assertEqual(two['version'],one['version']+1)
        self.assertEqual(td.download(self.con,self.item['id'],one['id'],self.out)[0].read_bytes(),first)
        self.assertEqual(self.con.execute('SELECT status FROM operational_tasks').fetchone()[0],'in_progress')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM operational_task_channels').fetchone()[0],0)
        self.assertEqual([r[0] for r in self.con.execute('SELECT event_type FROM operational_task_events')],['supplier_request_generated']*2)

    def test_missing_email_no_older_fallback(self):
        self.con.execute("UPDATE submissions SET raw_json='{}' WHERE id='2'");self.con.commit()
        with self.assertRaisesRegex(ValueError,'електронну адресу'):self.generate()
        self.assertFalse(self.out.exists())

    def test_supplier_name_prefers_edr_full_name(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name) VALUES(?,?,?)",
                         ('43897155','ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ЄДР НАЗВА"','ТОВ "ЄДР"'))
        self.con.execute("UPDATE supplier_registry_summary SET supplier_name='НЕ CANONICAL SUMMARY'")
        self.con.execute("UPDATE submissions SET supplier_name='НАЗВА З ОСТАННЬОЇ ЗАЯВКИ'")
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        values=td.resolve_context(self.con,self.item,fields,{'required_fields':['supplier.name','supplier.name_genitive']})
        self.assertEqual(values['supplier.name'],'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ЄДР НАЗВА»')
        self.assertEqual(values['supplier.name_genitive'],'ТОВАРИСТВА З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ЄДР НАЗВА»')

    def test_supplier_name_falls_back_to_latest_submission_not_summary(self):
        self.con.execute("UPDATE supplier_registry_summary SET supplier_name='НЕ CANONICAL SUMMARY'")
        self.con.execute("UPDATE submissions SET supplier_name=CASE id WHEN '1' THEN 'СТАРА НАЗВА' ELSE 'ОСТАННЯ НАЗВА' END")
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        values=td.resolve_context(self.con,self.item,fields,{'required_fields':['supplier.name']})
        self.assertEqual(values['supplier.name'],'ОСТАННЯ НАЗВА')

    def test_supplier_name_missing_is_validation_error(self):
        self.con.execute("UPDATE submissions SET supplier_name='' ")
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        with self.assertRaisesRegex(ValueError,'supplier.name'):
            td.resolve_context(self.con,self.item,fields,{'required_fields':['supplier.name']})

    def test_short_name_prefers_edr_and_falls_back_to_document_name(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name) VALUES(?,?,?)",
                         ('43897155','ПОВНА НАЗВА','ТОВ "КОРОТКА"'))
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        values=td.resolve_context(self.con,self.item,fields,{'required_fields':['supplier.short_name']})
        self.assertEqual(values['supplier.short_name'],'ТОВ «КОРОТКА»')
        self.con.execute("UPDATE supplier_edr_profiles SET short_name='' ")
        values=td.resolve_context(self.con,self.item,fields,{'required_fields':['supplier.short_name']})
        self.assertEqual(values['supplier.short_name'],'ПОВНА НАЗВА')

    def test_resolved_askod_metadata_is_immutable_per_version(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name) VALUES(?,?,?)",
                         ('43897155','ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ПОВНА НАЗВА"','ТОВ "ПЕРША"'))
        self.con.commit()
        first=self.generate()
        self.assertEqual(first['metadata']['askod_short_summary']['value'],
          'Запит до ТОВ «ПЕРША» щодо надання довідки з Реєстру НАЗК')
        self.con.execute("UPDATE supplier_edr_profiles SET short_name='ТОВ \"ДРУГА\"'")
        self.con.commit()
        second=self.generate()
        self.assertIn('ТОВ «ДРУГА»',second['metadata']['askod_short_summary']['value'])
        stored=td.documents(self.con,self.item['id'])
        self.assertIn('ТОВ «ПЕРША»',stored[1]['metadata']['askod_short_summary']['value'])
        self.assertEqual(stored[1]['resolved_metadata'][0]['metadata_key'],'askod_short_summary')
        self.assertIn('ТОВ «ПЕРША»',stored[1]['resolved_metadata'][0]['resolved_text'])

    def test_generic_metadata_active_new_version_and_inactive_historical_version(self):
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        runtime=dm.registered_document_types(template_runtime.configurations())
        created,_=dm.create(self.con,{
          'document_type':td.KEY,'metadata_key':'acceptance_registry_title',
          'label':'Назва для реєстру протоколів',
          'template_text':'Реєстрова назва {{supplier.short_name}}','active':True,
        },fields,runtime,'Admin UI test')
        self.assertEqual(created['version'],1)
        self.con.commit()
        first=self.generate()
        first_items={item['metadata_key']:item for item in first['resolved_metadata']}
        self.assertIn('acceptance_registry_title',first_items)
        self.assertEqual(first_items['acceptance_registry_title']['label'],'Назва для реєстру протоколів')
        self.assertIn('КОНТРОЛЬ',first_items['acceptance_registry_title']['resolved_text'])
        dm.update(self.con,td.KEY,'acceptance_registry_title',{'active':False},fields,runtime,'Admin UI test')
        self.con.commit()
        second=self.generate()
        self.assertNotIn('acceptance_registry_title',
                         {item['metadata_key'] for item in second['resolved_metadata']})
        historical=td.documents(self.con,self.item['id'])[1]
        self.assertIn('acceptance_registry_title',
                      {item['metadata_key'] for item in historical['resolved_metadata']})

    def test_task_guards(self):
        for field,value in [('status','completed'),('status','cancelled'),('task_type','warning_block'),
                            ('current_manager',{}),('task_person_is_current',False),('effective_active_count',0)]:
            before=self.item.copy();self.item[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.generate()
            self.item=before
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM generated_documents').fetchone()[0],0)

    def test_unknown_enum(self):
        with patch.object(td,'supplier_code_semantics',return_value={'code_label':'РНОКПП','entity_type':'unknown'}):
            with self.assertRaisesRegex(ValueError,'Невідоме'):self.generate()

    def test_inactive_and_missing_template(self):
        config=copy.deepcopy(template_runtime.registered(td.KEY));config['active']=False
        with patch.object(template_runtime,'registered',return_value=config):
            with self.assertRaisesRegex(ValueError,'неактивний'):self.generate()
        with patch.object(template_runtime,'TEMPLATE_ROOT',Path(self.temp.name)/'absent'), \
             patch.object(template_runtime,'SOURCE_TEMPLATE_ROOT',Path(self.temp.name)/'absent-source'):
            with self.assertRaisesRegex(ValueError,'відсутній'):self.generate()

    def test_malformed_and_unknown_template_no_output(self):
        source=template_runtime.template_path(td.KEY)
        for old,new in [('{{/if}}','{{/bad}}'),('supplier.email','supplier.unknown')]:
            path=Path(self.temp.name)/'invalid.docx'
            with ZipFile(source) as src,ZipFile(path,'w') as dst:
                for info in src.infolist():
                    raw=src.read(info)
                    if info.filename=='word/document.xml':
                        root=etree.fromstring(raw);changed=False
                        for paragraph in root.xpath('.//w:p',namespaces=NS):
                            text=paragraph_text(paragraph)
                            if old not in text:continue
                            runs=paragraph.xpath('.//w:t',namespaces=NS)
                            runs[0].text=text.replace(old,new)
                            for run in runs[1:]:run.text=''
                            changed=True
                        self.assertTrue(changed,(old,new))
                        raw=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
                    dst.writestr(info,raw)
            with patch.object(template_runtime,'template_path',return_value=path):
                with self.assertRaises(ValueError):self.generate()
        self.assertFalse(self.out.exists())

    def test_registry_and_source_preservation(self):
        metadata=template_runtime.metadata(self.schema)
        self.assertEqual(len(metadata),5)
        self.assertTrue(metadata[-1]['validation']['can_activate_canonical'])
        runtime=template_runtime.template_path(td.KEY)
        self.assertTrue(runtime.is_file())
        with ZipFile(runtime) as package:
            self.assertIsNone(package.testzip())
        self.assertEqual(template_runtime.registered(td.KEY)['source_reference'],
                         'https://docs.google.com/document/d/16fmgZ54NtnYGFZGIvn6ZnjKfif9sep40T3ARpiA6xlQ/edit')

    def test_download_scope(self):
        doc=self.generate()
        with self.assertRaises(KeyError):td.download(self.con,'b'*32,doc['id'],self.out)
        self.con.execute("UPDATE generated_documents SET storage_name='../outside.docx'")
        with self.assertRaises(KeyError):td.download(self.con,self.item['id'],doc['id'],self.out)
