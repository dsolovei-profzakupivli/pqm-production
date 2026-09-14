import unittest
from unittest.mock import patch
import operational_tasks,task_documents as td,template_catalog,schema_catalog
from test_task_documents import fixture

class ManagerRnokppDocumentTests(unittest.TestCase):
    def setUp(self):
        self.con,self.item=fixture();self.addCleanup(self.con.close)
        self.fields=template_catalog.validate(template_catalog.load(),schema_catalog.catalog('data/pqm.sqlite3'))
        self.item['current_manager'].update(manager_name='РУДЬ ОЛЕКСАНДР ПЕТРОВИЧ',manager_tax_id='3011007819')
    def resolve(self):
        return td.resolve_context(self.con,self.item,self.fields,{'required_fields':['manager.full_name','manager.rnokpp']})
    def test_current_saved(self):
        self.assertEqual(self.resolve(),{'manager.full_name':'РУДЬ ОЛЕКСАНДР ПЕТРОВИЧ','manager.rnokpp':'3011007819'})
    def test_missing_required(self):
        self.item['current_manager']['manager_tax_id']=None
        with self.assertRaisesRegex(ValueError,'manager.rnokpp'):self.resolve()
    def test_previous_manager_never_reused(self):
        self.item['task_person_is_current']=False
        with self.assertRaisesRegex(ValueError,'поточним керівником'):self.resolve()
        self.item['task_person_is_current']=True
        self.item['source_context']={'manager_tax_id':'3011007819'}
        self.item['current_manager']={'id':2,'manager_name':'ІНША ОСОБА','manager_tax_id':None}
        with self.assertRaisesRegex(ValueError,'manager.rnokpp'):self.resolve()
    def test_existing_save_immediately_resolved(self):
        self.con.execute("UPDATE supplier_managers SET manager_name=?,manager_tax_id=NULL WHERE id=1",
                         (self.item['current_manager']['manager_name'],))
        def detail(con,task_id):
            self.item['current_manager']=dict(con.execute('SELECT id,manager_name,manager_tax_id FROM supplier_managers WHERE is_current=1').fetchone())
            return self.item
        with patch.object(operational_tasks,'detail',side_effect=detail):
            operational_tasks.set_task_manager_tax_id(self.con,self.item['id'],'3011007819','Test UO')
        self.assertEqual(self.resolve()['manager.rnokpp'],'3011007819')
        self.assertEqual(self.con.execute('SELECT event_type FROM operational_task_events').fetchone()[0],'manager_tax_id_added')
    def test_individual_entrepreneur_uses_own_canonical_rnokpp(self):
        self.con.close()
        self.con,self.item=fixture('2452014059')
        self.addCleanup(self.con.close)
        self.item['current_manager'].update(manager_name='БАБІЙ СЕРГІЙ ПЕТРОВИЧ',manager_tax_id=None)
        self.con.execute("UPDATE supplier_managers SET manager_name=?,manager_tax_id=NULL WHERE id=1",
                         ('БАБІЙ СЕРГІЙ ПЕТРОВИЧ',))
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,short_name,manager_name,source_sheet) VALUES(?,?,?,?,?)""",
          ('2452014059','ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ БАБІЙ СЕРГІЙ ПЕТРОВИЧ',
           'ФОП БАБІЙ С.П.','БАБІЙ СЕРГІЙ ПЕТРОВИЧ','ФОП'))
        self.assertEqual(self.resolve()['manager.rnokpp'],'2452014059')
    def test_ten_digit_code_without_fop_identity_proof_is_not_rnokpp(self):
        self.con.close()
        self.con,self.item=fixture('2452014059')
        self.addCleanup(self.con.close)
        self.item['current_manager'].update(manager_name='БАБІЙ СЕРГІЙ ПЕТРОВИЧ',manager_tax_id=None)
        self.con.execute("UPDATE supplier_managers SET manager_name=?,manager_tax_id=NULL WHERE id=1",
                         ('БАБІЙ СЕРГІЙ ПЕТРОВИЧ',))
        with self.assertRaisesRegex(ValueError,'manager.rnokpp'):
            self.resolve()
    def test_fop_identity_mismatch_does_not_expose_supplier_code(self):
        self.con.close()
        self.con,self.item=fixture('2452014059')
        self.addCleanup(self.con.close)
        self.item['current_manager'].update(manager_name='ІНША ОСОБА',manager_tax_id=None)
        self.con.execute("UPDATE supplier_managers SET manager_name=?,manager_tax_id=NULL WHERE id=1",('ІНША ОСОБА',))
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,short_name,manager_name,source_sheet) VALUES(?,?,?,?,?)""",
          ('2452014059','ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ БАБІЙ СЕРГІЙ ПЕТРОВИЧ',
           'ФОП БАБІЙ С.П.','БАБІЙ СЕРГІЙ ПЕТРОВИЧ','ФОП'))
        with self.assertRaisesRegex(ValueError,'manager.rnokpp'):
            self.resolve()

if __name__=='__main__':unittest.main()
