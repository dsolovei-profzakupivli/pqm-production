import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from unittest.mock import patch
from lxml import etree
from protocol_template import build_from_template, context, template_path, NS, TemplateError
from protocol_docx import build_protocol_docx


class ProtocolTemplateTests(unittest.TestCase):
    def setUp(self):
        self.payload=dict(protocol_number='T-1', protocol_date='2026-09-05', date_from='2026-09-01',
                          date_to='2026-09-04', officer='Світлана НАМЯСЕНКО', items=[
            dict(protocol_decision='admit',supplier_name='A & B <ТОВ>',supplier_code='00123456',
                 pretty_id='UA-F-test',dk_code='123',category_title='Категорія',date_published='2026-09-01'),
            dict(protocol_decision='reject',supplier_name='ФОП',supplier_code='0123456789',
                 protocol_remarks='Довільний текст {{ count_all }}\nдругий рядок')])

    def test_counts_and_legacy_verb(self):
        values,groups=context(self.payload)
        self.assertEqual((2,1,1),tuple(values[x] for x in ('count_all','count_admitted','count_rejected')))
        self.assertEqual('склала',values['officer_verb'])
        self.payload['officer']='Олег ІВАНЕНКО'
        self.assertEqual('склав',context(self.payload)[0]['officer_verb'])
        self.assertEqual('00123456',groups['applications_all'][0]['supplier_code'])

    def test_unknown_decision_cannot_fallback(self):
        self.payload['items'][0]['protocol_decision']='pending'
        with TemporaryDirectory() as tmp,patch('protocol_docx.build_protocol_docx_legacy') as legacy:
            with self.assertRaises(ValueError):build_protocol_docx(self.payload,Path(tmp)/'x.docx')
            legacy.assert_not_called()

    def test_preserves_parts_and_expands_three_tables(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.docx';build_from_template(self.payload,path)
            with ZipFile(path) as result,ZipFile(template_path()) as original:
                for name in original.namelist():
                    if name!='word/document.xml':self.assertEqual(original.read(name),result.read(name),name)
                root=etree.fromstring(result.read('word/document.xml'))
            tables=root.xpath('.//w:tbl',namespaces=NS)[-3:]
            self.assertEqual([3,2,2],[len(t.findall('w:tr',NS)) for t in tables])
            text=''.join(root.xpath('.//w:t/text()',namespaces=NS))
            self.assertIn('A & B <ТОВ>',text)
            self.assertIn('{{ count_all }}',text)  # user data is not evaluated
            self.assertNotIn('{{ protocol_number }}',text)

    def test_empty_group_keeps_header(self):
        self.payload['items']=self.payload['items'][:1]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.docx';build_from_template(self.payload,path)
            with ZipFile(path) as z:root=etree.fromstring(z.read('word/document.xml'))
            self.assertEqual(1,len(root.xpath('.//w:tbl',namespaces=NS)[-1].findall('w:tr',NS)))

    def test_missing_template_does_not_overwrite_existing_output(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.docx';path.write_bytes(b'previous')
            with self.assertRaises(TemplateError):build_from_template(self.payload,path,Path(tmp)/'missing.docx')
            self.assertEqual(b'previous',path.read_bytes())

    def test_fallback_is_explicit_and_atomic(self):
        with TemporaryDirectory() as tmp,patch.dict('os.environ',{'PQM_APPLICATION_PROTOCOL_TEMPLATE':str(Path(tmp)/'missing.docx'),'PQM_PROTOCOL_ENGINE':'template'}):
            path=Path(tmp)/'x.docx';build_protocol_docx(self.payload,path)
            with ZipFile(path) as z:self.assertIn('word/document.xml',z.namelist())

    def test_template_controls_row_formatting(self):
        with TemporaryDirectory() as tmp:
            custom=Path(tmp)/'custom.docx';output=Path(tmp)/'out.docx'
            with ZipFile(template_path()) as src,ZipFile(custom,'w') as dst:
                for info in src.infolist():
                    data=src.read(info)
                    if info.filename=='word/document.xml':
                        root=etree.fromstring(data)
                        row=root.xpath('.//w:tbl',namespaces=NS)[-3].findall('w:tr',NS)[1]
                        for size in row.xpath('.//w:sz',namespaces=NS):size.set('{'+NS['w']+'}val','22')
                        data=etree.tostring(root)
                    dst.writestr(info,data)
            build_from_template(self.payload,output,custom)
            with ZipFile(output) as z:root=etree.fromstring(z.read('word/document.xml'))
            rows=root.xpath('.//w:tbl',namespaces=NS)[-3].findall('w:tr',NS)[1:]
            self.assertTrue(all(x.get('{'+NS['w']+'}val')=='22' for r in rows for x in r.xpath('.//w:sz',namespaces=NS)))


if __name__=='__main__':unittest.main()
