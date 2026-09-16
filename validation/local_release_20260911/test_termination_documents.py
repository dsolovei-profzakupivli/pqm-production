import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
from lxml import etree
import schema_catalog
import task_documents as td
import template_runtime
import template_catalog
from test_task_documents import fixture


class TerminationDocumentTests(unittest.TestCase):
    def setUp(self):
        self.con,self.item=fixture('2884318089');self.addCleanup(self.con.close)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)/'documents'
        self.schema=schema_catalog.catalog('data/pqm.sqlite3')
        self.item.update(task_type='termination_exclusion',status='ready_for_document',
            protocol_number='TEST-701',protocol_date='2026-09-16',assigned_officer_name='СВІТЛАНА НАМЯСЕНКО',
            target_qualifications=[{'qualification_id':'test-q','decision':'exclude','effective_active':1}],
            source_context={'supplier':{'type':'individual_entrepreneur','code':'2884318089','code_label':'РНОКПП',
                'full_name':'ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ ПРЕСЛІЦЬКА КАТЕРИНА КАЗИМИРІВНА',
                'short_name':'ФОП ПРЕСЛІЦЬКА К.К.'},
                'termination':{'details':'TEST рішення','record_date':'2026-09-01','record_number':'TEST-10'}})
        self.runtime=Path(self.temp.name)/'templates'
        self.patcher=patch.object(template_runtime,'TEMPLATE_ROOT',self.runtime);self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_fop_generation_history_download_pdf_source_no_task_transition(self):
        ready=td.termination_readiness(self.con,self.item,self.schema)
        self.assertTrue(ready['ready'],ready['errors'])
        before=self.con.execute('SELECT status FROM operational_tasks').fetchone()[0]
        one=td.generate_termination(self.con,self.item,self.schema,self.out,'Fixture')
        two=td.generate_termination(self.con,self.item,self.schema,self.out,'Fixture')
        self.assertEqual((one['version'],two['version']),(1,2))
        path,filename=td.download(self.con,self.item['id'],two['id'],self.out)
        with ZipFile(path) as z:
            tree=etree.fromstring(z.read('word/document.xml'))
            text=''.join(tree.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
        self.assertNotIn('{{',text);self.assertIn('TEST-701',text);self.assertIn('16.09.2026',text)
        self.assertIn('TEST рішення',text);self.assertIn('Світлана НАМЯСЕНКО',text)
        pdf_source,pdf_name=td.amcu_pdf_source(self.con,self.item['id'],two['id'],self.out)
        self.assertEqual(pdf_source,path);self.assertTrue(pdf_name.endswith('.pdf'))
        self.assertTrue(two['pdf_url']);self.assertEqual(len(td.documents(self.con,self.item['id'])),2)
        self.assertEqual(self.con.execute('SELECT status FROM operational_tasks').fetchone()[0],before)

    def test_legal_entity_blocked_and_missing_fields_blocked(self):
        legal=copy.deepcopy(self.item);legal['source_context']['supplier']['type']='legal_entity'
        self.assertFalse(td.termination_readiness(self.con,legal,self.schema)['ready'])
        with self.assertRaisesRegex(ValueError,'юридичної'):td.generate_termination(self.con,legal,self.schema,self.out,'Fixture')
        for key in ('protocol_number','protocol_date'):
            item=copy.deepcopy(self.item);item[key]=''
            self.assertFalse(td.termination_readiness(self.con,item,self.schema)['ready'])
        item=copy.deepcopy(self.item);item['target_qualifications'][0]['decision']=''
        self.assertFalse(td.termination_readiness(self.con,item,self.schema)['ready'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM generated_documents').fetchone()[0],0)

    def test_source_integrity_and_alias_validation(self):
        source=Path('templates/termination_exclusion_protocol.docx')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),'00cb3869715e4f40ec1d10c246844e86149bb6b831b3dd54dfc7d6c6c35b046d')
        fields=template_catalog.validate(template_catalog.load(),self.schema)
        self.assertTrue(template_runtime.validate_template(td.TERMINATION_PROTOCOL_KEY,fields,source)['can_activate_canonical'])
        self.assertEqual(Path('templates/violation_protocols/decline_p49_1_2.docx').read_bytes(),
                         Path('data/templates/violation_protocols/decline_p49_1_2.docx').read_bytes())

    def test_unresolved_required_case_and_completed_block_without_output(self):
        unresolved={'status':'unresolved','grammatical_case':'genitive','original':'TEST','resolved_value':''}
        with patch.object(td,'_declension_item',return_value=unresolved):
            ready=td.termination_readiness(self.con,self.item,self.schema)
            self.assertFalse(ready['ready']);self.assertTrue(ready['unresolved'])
            with self.assertRaises(td.DeclensionRequired):td.generate_termination(self.con,self.item,self.schema,self.out,'Fixture')
        for state in ('completed','cancelled','awaiting_sync'):
            item=copy.deepcopy(self.item);item['status']=state
            self.assertFalse(td.termination_readiness(self.con,item,self.schema)['ready'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM generated_documents').fetchone()[0],0)

    def test_nazk_pdf_source_supported_and_scoped(self):
        self.item['task_type']='nazk_check'
        con,item=fixture();self.addCleanup(con.close)
        document=td.generate(con,item,self.schema,self.out,'Fixture')
        source,name=td.amcu_pdf_source(con,item['id'],document['id'],self.out)
        self.assertTrue(source.is_file());self.assertTrue(name.endswith('.pdf'));self.assertTrue(document['pdf_url'])
        with self.assertRaises(KeyError):td.amcu_pdf_source(con,'wrong-task',document['id'],self.out)
