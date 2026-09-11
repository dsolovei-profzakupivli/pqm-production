import sqlite3
import unittest

import document_metadata as dm


def field(key='supplier.short_name', available=True, status='VALID'):
    available_for=(['nazk_supplier_request'] if available is True else
                   ([available] if isinstance(available,str) else []))
    return {'key':key,'label':'Скорочена назва','description':'Опис','group':'Постачальник',
      'binding_status':status,'source_binding':{'source_type':'derived'},'active':True,
      'deprecated':False,'available_for':available_for}


class DocumentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;dm.migrate(self.con)
        self.addCleanup(self.con.close)

    def test_default_validate_and_render(self):
        item=dm.templates(self.con,'nazk_supplier_request')[0]
        self.assertEqual(dm.validate_template(item['template_text'],[field()],'nazk_supplier_request'),['supplier.short_name'])
        self.assertEqual(dm.render(item['template_text'],{'supplier.short_name':'ТОВ «ФМТ»'}),
          'Запит до ТОВ «ФМТ» щодо надання довідки з Реєстру НАЗК')

    def test_violation_protocol_subject_is_registered_and_generic(self):
        document_type=dm.VIOLATION_REVIEW_PROTOCOL
        item=dm.templates(self.con,document_type)[0]
        keys=('report_id','tender_id','customer.short_name','supplier.short_name','supplier.code')
        fields=[field(key,document_type) for key in keys]
        self.assertEqual(dm.validate_template(item['template_text'],fields,document_type),sorted(keys))
        resolved=dm.render(item['template_text'],{
          'report_id':'UA-D-1','tender_id':'UA-1','customer.short_name':'ЗАМОВНИК',
          'supplier.short_name':'ТОВ «ТЕСТ»','supplier.code':'12345678'})
        self.assertEqual(resolved,'Розгляд звернення UA-D-1 по закупівлі UA-1 ЗАМОВНИК (на ТОВ «ТЕСТ»; 12345678)')
        self.assertIn(document_type,dm.registered_document_types({}))

    def test_protocol_subject_save_is_versioned_audited_and_idempotent(self):
        document_type=dm.VIOLATION_REVIEW_PROTOCOL
        keys=('report_id','tender_id','customer.short_name','supplier.short_name','supplier.code')
        fields=[field(key,document_type) for key in keys]
        runtime=dm.registered_document_types({})
        changed_text='Протокол {{report_id}} · {{customer.short_name}}'
        saved,changed=dm.save(self.con,document_type,dm.PROTOCOL_SUBJECT,
                              changed_text,fields,runtime,'Адміністратор')
        self.assertTrue(changed);self.assertEqual(saved['version'],2)
        repeated,changed=dm.save(self.con,document_type,dm.PROTOCOL_SUBJECT,
                                 changed_text,fields,runtime,'Адміністратор')
        self.assertFalse(changed);self.assertEqual(repeated['version'],2)
        event=self.con.execute('''SELECT old_template_text,new_template_text,changed_by
          FROM document_metadata_template_events WHERE document_type=? AND metadata_key=?''',
          (document_type,dm.PROTOCOL_SUBJECT)).fetchone()
        self.assertIn('{{tender_id}}',event['old_template_text'])
        self.assertEqual(event['new_template_text'],changed_text)
        self.assertEqual(event['changed_by'],'Адміністратор')

    def test_validation_rejects_unknown_unbound_unavailable_and_malformed(self):
        for template,fields,message in [
          ('{{supplier.unknown}}',[field()],'Невідоме'),
          ('{{supplier.short_name}}',[field(status='PROPOSED_UNBOUND')],'runtime binding'),
          ('{{supplier.short_name}}',[field(available=False)],'недоступне'),
          ('{{ supplier.short_name | upper }}',[field()],'Непідтримуваний')]:
            with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):
                dm.validate_template(template,fields,'nazk_supplier_request')

    def test_save_is_audited_and_idempotent(self):
        fields=[field()];runtime=['nazk_supplier_request']
        current=dm.templates(self.con,'nazk_supplier_request')[0]
        same,changed=dm.save(self.con,'nazk_supplier_request',dm.ASKOD_SHORT_SUMMARY,current['template_text'],fields,runtime,'Admin')
        self.assertFalse(changed)
        new='Документ для {{supplier.short_name}}'
        saved,changed=dm.save(self.con,'nazk_supplier_request',dm.ASKOD_SHORT_SUMMARY,new,fields,runtime,'Admin')
        self.assertTrue(changed);self.assertEqual(saved['version'],2)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM document_metadata_template_events').fetchone()[0],1)
        _,changed=dm.save(self.con,'nazk_supplier_request',dm.ASKOD_SHORT_SUMMARY,new,fields,runtime,'Admin')
        self.assertFalse(changed)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM document_metadata_template_events').fetchone()[0],1)

    def test_unregistered_document_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'не зареєстрований'):
            dm.save(self.con,'nazk_authority_request',dm.ASKOD_SHORT_SUMMARY,'Текст',[field()],['nazk_supplier_request'],'Admin')

    def test_create_edit_deactivate_and_audit_are_generic(self):
        fields=[field()];runtime=['nazk_supplier_request']
        payload={'document_type':'nazk_supplier_request','metadata_key':'registry_title',
                 'label':'Назва для реєстру','description':'Короткий опис',
                 'template_text':'Запис {{supplier.short_name}}','active':True}
        created,used=dm.create(self.con,payload,fields,runtime,'Admin')
        self.assertEqual(used,['supplier.short_name']);self.assertEqual(created['version'],1)
        self.assertEqual(self.con.execute("SELECT action FROM document_metadata_template_events WHERE metadata_key='registry_title'").fetchone()[0],'created')
        with self.assertRaisesRegex(dm.MetadataConflict,'уже існують'):
            dm.create(self.con,payload,fields,runtime,'Admin')
        edited,changed,_=dm.update(self.con,'nazk_supplier_request','registry_title',
          {'label':'Назва для зовнішнього реєстру','active':False},fields,runtime,'Editor')
        self.assertTrue(changed);self.assertEqual(edited['version'],2);self.assertEqual(edited['active'],0)
        self.assertNotIn('registry_title',dm.resolve_all(self.con,'nazk_supplier_request',fields,
          lambda keys:{key:'ТОВ «ТЕСТ»' for key in keys}))
        repeated,changed,_=dm.update(self.con,'nazk_supplier_request','registry_title',
          {'label':'Назва для зовнішнього реєстру','active':False},fields,runtime,'Editor')
        self.assertFalse(changed);self.assertEqual(repeated['version'],2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM document_metadata_template_events WHERE metadata_key='registry_title'").fetchone()[0],2)

    def test_create_validation_rejects_invalid_key_empty_and_unknown(self):
        base={'document_type':'nazk_supplier_request','metadata_key':'valid_key','label':'Назва',
              'template_text':'{{supplier.short_name}}'}
        for changes,message in [({'metadata_key':'Невірний ключ'},'Key має'),
                                ({'label':''},'Назва метаданих'),
                                ({'template_text':''},'Шаблон тексту'),
                                ({'template_text':'{{supplier.missing}}'},'Невідоме поле')]:
            with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):
                dm.create(self.con,{**base,**changes},[field()],['nazk_supplier_request'],'Admin')

    def test_used_flag_reads_resolved_metadata_without_mutating_history(self):
        self.con.execute('''CREATE TABLE generated_documents(
          document_type TEXT, metadata_json TEXT)''')
        historical='{"askod_short_summary":{"value":"Старе значення"}}'
        self.con.execute('INSERT INTO generated_documents VALUES(?,?)',('nazk_supplier_request',historical))
        item=dm.admin_catalog(self.con,[field()],{})['items'][0]
        self.assertTrue(item['used'])
        dm.update(self.con,'nazk_supplier_request',dm.ASKOD_SHORT_SUMMARY,
          {'active':False},[field()],dm.registered_document_types({}),'Admin')
        self.assertEqual(self.con.execute('SELECT metadata_json FROM generated_documents').fetchone()[0],historical)

    def test_resolved_items_preserve_persisted_order_and_skip_empty_values(self):
        persisted = {
            'second_created': {'label': 'Другий рядок', 'value': 'Друге значення', 'config_version': 4},
            'first_alphabetically': {'label': 'Перший за абеткою', 'value': 'Перше значення'},
            'empty_value': {'label': 'Порожнє', 'value': '   ', 'config_version': 9},
        }
        items = dm.resolved_items(persisted)
        self.assertEqual([item['metadata_key'] for item in items],
                         ['second_created', 'first_alphabetically'])
        self.assertEqual(items[0], {
            'metadata_key': 'second_created', 'label': 'Другий рядок',
            'resolved_text': 'Друге значення', 'version': 4, 'display_order': 0,
        })
        self.assertEqual(items[1]['version'], 1)


if __name__=='__main__':unittest.main()
