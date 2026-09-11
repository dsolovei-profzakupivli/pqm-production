import unittest
import declension,derived_fields,template_catalog,schema_catalog,task_documents
from test_task_documents import fixture

class OrganizationQuotesTests(unittest.TestCase):
    def test_normalization(self):
        for source,expected in [('"ГУРКІТ ГРУП"','«ГУРКІТ ГРУП»'),('«ГУРКІТ ГРУП»','«ГУРКІТ ГРУП»'),('ГУРКІТ ГРУП','ГУРКІТ ГРУП'),('"М\'ЯСОПРОДУКТ"','«М\'ЯСОПРОДУКТ»'),('«Назва "вкладена"»','«Назва "вкладена"»'),('"Незакрита','"Незакрита')]:
            self.assertEqual(declension.normalize_document_name(source),expected)
    def test_generic_and_base_context(self):
        source='ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ГУРКІТ ГРУП"'
        con,item=fixture();self.addCleanup(con.close)
        con.execute(
            'INSERT INTO supplier_edr_profiles(supplier_code,full_name) VALUES(?,?)',
            (item['supplier_code'], source),
        );con.commit()
        fields=template_catalog.validate(template_catalog.load(),schema_catalog.catalog('data/pqm.sqlite3'))
        values=task_documents.resolve_context(con,item,fields,{'required_fields':['supplier.name','supplier.name_genitive']})
        self.assertEqual(values['supplier.name'],source.replace('"ГУРКІТ ГРУП"','«ГУРКІТ ГРУП»'))
        self.assertEqual(values['supplier.name_genitive'],'ТОВАРИСТВА З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ГУРКІТ ГРУП»')
        self.assertEqual(con.execute('SELECT full_name FROM supplier_edr_profiles').fetchone()[0],source)
    def test_proper_name_not_inflected(self):
        source='ТОВАРИСТВО "ПРИВАТНЕ ПІДПРИЄМСТВО"'
        self.assertEqual(declension.decline_name(source,'legal_entity','genitive').value,'ТОВАРИСТВА "ПРИВАТНЕ ПІДПРИЄМСТВО"')
        self.assertEqual(declension.decline_name('ТОВАРИСТВО "А "Б""','legal_entity','genitive').status,'unresolved')

if __name__=='__main__':unittest.main()
