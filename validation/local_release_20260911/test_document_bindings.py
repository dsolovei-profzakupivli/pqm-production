import copy
import unittest
import derived_fields, document_bindings, template_catalog, schema_catalog, task_documents
from test_task_documents import fixture

class DocumentBindingTests(unittest.TestCase):
    def setUp(self):
        self.schema=schema_catalog.catalog('data/pqm.sqlite3')
        self.data=template_catalog.load()
    def test_new_catalog_alias_no_python_change(self):
        alias=copy.deepcopy(next(f for f in self.data['fields'] if f['key']=='manager.rnokpp'))
        alias['key']='manager.identity_document_value'
        self.data['fields'].append(alias)
        fields=template_catalog.validate(self.data,self.schema)
        con,item=fixture();self.addCleanup(con.close)
        item['current_manager']['manager_tax_id']='3011007819'
        values=task_documents.resolve_context(con,item,fields,{'required_fields':[alias['key'],'manager.rnokpp']})
        self.assertEqual(values[alias['key']],values['manager.rnokpp'])
    def test_existing_fields_without_whitelist(self):
        con,item=fixture();self.addCleanup(con.close)
        item.update(created_at='2026-09-10T10:00:00',assigned_officer_name='Тестова УО')
        item['nazk_records']=[{'court_case_number':'123/26'}]
        keys=['task.created_at','task.type','uo.full_name','task.responsible_uo','nazk.record.case_number','system.today']
        values=task_documents.resolve_context(con,item,template_catalog.validate(self.data,self.schema),{'required_fields':keys})
        self.assertEqual(values['nazk.record.case_number'],'123/26')
        self.assertEqual(values['uo.full_name'],values['task.responsible_uo'])
        self.assertEqual(values['task.type'],'nazk_check')
    def test_unbound_unavailable_private_and_invalid_paths(self):
        fields=template_catalog.validate(self.data,self.schema)
        for key in ['decision.number','amcu.count']:
            with self.assertRaises(ValueError):derived_fields.resolve([key],fields,'nazk_supplier_request',lambda f:self.fail('must not read source'))
        self.assertTrue(document_bindings.binding_errors({'source_type':'derived','context_path':'task.__class__'}))
        f=copy.deepcopy(self.data['fields'][1]);f['source_binding']={'source_type':'schema_field','schema_field':'pqm.amcu_registry.row_key'}
        data=copy.deepcopy(self.data);data['fields']=[f]
        self.assertNotEqual(template_catalog.validate(data,self.schema)[0]['binding_status'],'VALID')
    def test_ambiguous_record_not_first_match(self):
        with self.assertRaisesRegex(ValueError,'Неоднозначне'):
            document_bindings.path_value({'records':[{'name':'A'},{'name':'B'}]},'records.name')
    def test_all_bound_fields_have_machine_binding(self):
        for f in template_catalog.validate(self.data,self.schema):
            if f['binding_status']=='VALID':self.assertFalse(document_bindings.binding_errors(f['source_binding']))
    def test_new_manager_column_hydrates_current_identity(self):
        alias=copy.deepcopy(next(f for f in self.data['fields'] if f['key']=='manager.rnokpp'))
        alias['key']='manager.identity_source';alias['source_binding']['schema_field']='pqm.supplier_managers.manager_tax_id_source'
        self.data['fields'].append(alias)
        con,item=fixture();self.addCleanup(con.close)
        con.execute("UPDATE supplier_managers SET manager_tax_id_source='operational_manual' WHERE id=1")
        con.execute('INSERT INTO supplier_managers(id,supplier_code,is_current,manager_tax_id_source) VALUES(?,?,?,?)',
                    (2,'43897155',0,'previous_person'))
        result=task_documents.resolve_context(con,item,template_catalog.validate(self.data,self.schema),{'required_fields':[alias['key']]})
        self.assertEqual(result[alias['key']],'operational_manual')

if __name__=='__main__':unittest.main()
