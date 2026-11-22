"""Task-card protocol projection shows the latest generated document per type."""
import unittest

import operational_tasks as tasks
import task_documents as docs
import validation.local_release_20260911.test_task_documents as fixtures


class CurrentProtocolTests(unittest.TestCase):
    def setUp(self):
        self.con,self.item=fixtures.fixture()
        self.addCleanup(self.con.close)
        self.item.update(task_type='amcu_exclusion',protocol_number='701',protocol_date='2026-09-14')

    def add(self,ident,version,created_at,kind=docs.AMCU_PROTOCOL_KEY,task=None):
        self.con.execute('''INSERT INTO generated_documents
          (id,task_id,supplier_code,document_type,template_key,template_reference,filename,
           storage_name,created_at,created_by,generation_provider,status,document_date,version,
           sha256,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (ident,task or self.item['id'],'43897155',kind,kind,'synthetic',f'protocol-v{version}.docx',
           ident+'/synthetic.docx',created_at,'test','docx_local','generated','2026-09-14',version,
           'synthetic','{}'))

    def summary(self):
        return tasks.task_ui_summary(self.con,self.item,{'generated_documents'})

    def test_only_latest_per_protocol_type_is_in_current_card(self):
        for version in range(1,4):
            self.add(str(version)*32,version,f'2026-09-14T10:00:0{version}Z')
        card=self.summary()['officer_decision']['documents']
        history=docs.documents(self.con,self.item['id'])
        self.assertEqual([d['version'] for d in card],[3])
        self.assertEqual([d['version'] for d in history],[3,2,1])
        self.assertEqual([d['id'] for d in card],[history[0]['id']])

    def test_distinct_protocol_types_and_other_tasks_are_not_collapsed(self):
        self.add('a'*32,1,'2026-09-14T10:00:01Z')
        self.add('b'*32,2,'2026-09-14T10:00:02Z')
        self.add('c'*32,1,'2026-09-14T10:00:03Z',kind=docs.TERMINATION_PROTOCOL_KEY)
        self.add('d'*32,1,'2099-01-01T00:00:00Z',task='different-task')
        self.assertEqual({d['id'] for d in self.summary()['officer_decision']['documents']},
                         {'b'*32,'c'*32})

    def test_projection_does_not_mutate_generation_rows(self):
        for version in range(1,4):
            self.add(str(version)*32,version,f'2026-09-14T10:00:0{version}Z')
        before='\n'.join(self.con.iterdump())
        for _ in range(3):self.summary()
        self.assertEqual(before,'\n'.join(self.con.iterdump()))


if __name__=='__main__':
    unittest.main()
