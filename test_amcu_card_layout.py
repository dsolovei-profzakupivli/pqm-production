"""Addressed modal-only UI regressions; no DB or network."""
import subprocess
import unittest
from pathlib import Path

class AmcuCardLayoutTests(unittest.TestCase):
    def test_real_renderers_fields_history_empty_and_other_types(self):
        result=subprocess.run(['node','validation/amcu_card_layout_unit.cjs'],
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_equal_columns_word_wrap_and_narrow_stack_are_scoped_to_modal(self):
        css=Path('styles.css').read_text(encoding='utf-8')
        self.assertIn('#operationalTaskDialog .operational-amcu-decision-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))',css)
        self.assertIn('white-space:normal;overflow-wrap:anywhere;word-break:normal',css)
        self.assertIn('@media(max-width:700px){#operationalTaskDialog .operational-amcu-decision-cards{grid-template-columns:minmax(0,1fr)}}',css)

    def test_saved_metadata_contract_is_version_specific_and_read_only(self):
        import json
        import task_documents as documents
        import operational_tasks as tasks
        import test_task_documents as fixtures
        con,item=fixtures.fixture();self.addCleanup(con.close)
        item['task_type']='amcu_exclusion'
        for version in [1,2,3]:
            metadata={'subject':{'label':'Збережена тема','value':f'Версія {version}','config_version':version},
                      'custom':{'label':'Інше поле','value':f'Додатковий текст {version}','config_version':7}}
            con.execute('''INSERT INTO generated_documents
              (id,task_id,supplier_code,document_type,template_key,template_reference,filename,storage_name,
               created_at,created_by,generation_provider,status,document_date,version,sha256,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (str(version)*32,item['id'],item['supplier_code'],documents.AMCU_PROTOCOL_KEY,documents.AMCU_PROTOCOL_KEY,
               'synthetic',f'protocol_v{version}.docx',f'v{version}/protocol.docx',f'2026-10-17T10:00:0{version}Z',
               'fixture','docx_local','generated','2026-10-17',version,'synthetic',json.dumps(metadata)))
        before='\n'.join(con.iterdump())
        current=tasks.task_ui_summary(con,item,{'generated_documents'})['officer_decision']['documents'][0]
        self.assertEqual(current['version'],3)
        self.assertEqual([m['metadata_key'] for m in current['resolved_metadata']],['subject','custom'])
        self.assertEqual([m['resolved_text'] for m in current['resolved_metadata']],['Версія 3','Додатковий текст 3'])
        self.assertEqual([m['version'] for m in current['resolved_metadata']],[3,7])
        self.assertEqual(before,'\n'.join(con.iterdump()))
        con.execute("UPDATE generated_documents SET metadata_json='{}' WHERE version=3")
        current=tasks.task_ui_summary(con,item,{'generated_documents'})['officer_decision']['documents'][0]
        self.assertEqual(current['version'],3);self.assertEqual(current['resolved_metadata'],[])
        self.assertEqual(documents.documents(con,item['id'])[1]['resolved_metadata'][0]['resolved_text'],'Версія 2')
