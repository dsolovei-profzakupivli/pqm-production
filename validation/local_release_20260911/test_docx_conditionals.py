import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from docx import Document
from docx.shared import Pt
import schema_catalog
import template_catalog
from docx_conditionals import render
from template_conditions import ConditionalError

TYPE='nazk_supplier_request'
FOP='{{#if supplier.entity_type == "individual_entrepreneur"}}'
LEGAL='{{#if supplier.entity_type == "legal_entity"}}'
END='{{/if}}'


class ConditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields=template_catalog.validate(template_catalog.load(),schema_catalog.catalog(Path('data/pqm.sqlite3')))

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source=Path(self.folder.name)/'source.docx'
        self.output=Path(self.folder.name)/'result.docx'
        self.context={'supplier.entity_type':'legal_entity','supplier.email':'test@example.com','supplier.name':'Назва'}

    def fixture(self, paragraphs):
        d=Document()
        d.styles['Normal'].font.name='Times New Roman'
        d.styles['Normal'].font.size=Pt(12)
        for text in paragraphs:d.add_paragraph(text)
        d.save(self.source)
        return d

    def build(self):
        return render(self.source,self.output,self.context,self.fields,TYPE)

    def test_both_branches_scalars_no_markers_or_empty_paragraphs(self):
        self.fixture(['Назва: {{supplier.name}}',FOP,'Для ФОП',END,LEGAL,'Для ЮО',END,'Кінець'])
        before=self.source.read_bytes()
        for entity,expected,absent in [('individual_entrepreneur','Для ФОП','Для ЮО'),('legal_entity','Для ЮО','Для ФОП')]:
            self.context['supplier.entity_type']=entity
            self.build()
            self.assertEqual([p.text for p in Document(self.output).paragraphs],['Назва: Назва',expected,'Кінець'])
            self.assertEqual(self.source.read_bytes(),before)
            self.assertNotIn(absent,'\n'.join(p.text for p in Document(self.output).paragraphs))

    def test_invalid_context_no_output(self):
        self.fixture([FOP,'FOP',END])
        for value in (None,'unknown',1):
            self.context['supplier.entity_type']=value
            with self.assertRaises(ConditionalError):self.build()
            self.assertFalse(self.output.exists())
        del self.context['supplier.entity_type']
        with self.assertRaises(ConditionalError):self.build()

    def test_bad_syntax_no_output(self):
        for paragraphs in ([FOP,'x'],[END],[FOP,LEGAL,'x',END,END],
            ['{{#if supplier.entity_type != "legal_entity"}}','x',END],
            ['{{#if supplier.entity_type == "legal_entity" or true}}','x',END],
            [FOP,'{{else}}',END],['inline '+FOP,'x',END],
            ['{{#if supplier.entity_type == "unknown"}}','x',END],
            ['{{#if missing.field == "x"}}','x',END]):
            with self.subTest(paragraphs=paragraphs):
                self.fixture(paragraphs)
                with self.assertRaises(ConditionalError):self.build()
                self.assertFalse(self.output.exists())

    def test_unavailable_and_non_string_field(self):
        for marker in ('{{#if warning.references == "x"}}','{{#if system.today == "x"}}'):
            self.fixture([marker,'x',END])
            with self.assertRaises(ConditionalError):self.build()

    def test_split_markers_and_scalar_style_preserved(self):
        d=Document()
        p=d.add_paragraph();p.add_run(FOP[:10]);p.add_run(FOP[10:])
        p=d.add_paragraph();p.add_run('{{supplier.').bold=True;p.add_run('name}}')
        d.add_paragraph(END);d.add_paragraph('Tail');d.save(self.source)
        self.context['supplier.entity_type']='individual_entrepreneur'
        self.build();p=Document(self.output).paragraphs[0]
        self.assertEqual(p.text,'Назва');self.assertTrue(p.runs[0].bold)

    def test_whole_table_removed_headers_supported(self):
        d=Document();d.add_paragraph(FOP)
        d.add_table(rows=1,cols=1).cell(0,0).text='FOP table'
        d.add_paragraph(END);d.add_paragraph('Tail')
        h=d.sections[0].header;h.paragraphs[0].text=LEGAL;h.add_paragraph('Header');h.add_paragraph(END)
        d.save(self.source);self.build();out=Document(self.output)
        self.assertEqual(len(out.tables),0)
        self.assertEqual([p.text for p in out.paragraphs],['Tail'])
        self.assertEqual([p.text for p in out.sections[0].header.paragraphs],['Header'])

    def test_cross_cell_markers_rejected(self):
        d=Document();table=d.add_table(rows=1,cols=2)
        table.cell(0,0).text=FOP;table.cell(0,1).text=END;d.save(self.source)
        with self.assertRaises(ConditionalError):self.build()

    def test_required_email_and_atomic_failure(self):
        self.fixture([LEGAL,'x',END]);self.build();before=self.output.read_bytes()
        self.context['supplier.email']=None
        with self.assertRaises(ConditionalError):self.build()
        self.assertEqual(self.output.read_bytes(),before)

    def test_generic_string_condition_not_nazk_specific(self):
        self.fixture(['{{#if supplier.name == "Назва"}}','Matched',END,
                      '{{#if supplier.name == "Other"}}','','Not matched',END])
        self.build()
        self.assertEqual([p.text for p in Document(self.output).paragraphs],['Matched'])

    def test_false_branch_still_validated(self):
        self.fixture([FOP,'{{unknown.field}}',END])
        with self.assertRaises(ConditionalError):self.build()
        self.assertFalse(self.output.exists())
        from docx_conditionals import condition_keys, retained_scalar_keys
        self.fixture([FOP,'{{manager.full_name_genitive}}',END,LEGAL,'{{supplier.name_genitive}}',END])
        self.assertEqual(condition_keys(self.source,self.fields,TYPE),{'supplier.entity_type'})
        context={'supplier.entity_type':'individual_entrepreneur'}
        self.assertEqual(retained_scalar_keys(self.source,self.fields,TYPE,context),{'manager.full_name_genitive'})

    def test_same_cell_blocks_keep_other_content(self):
        d=Document();cell=d.add_table(rows=1,cols=1).cell(0,0)
        cell.paragraphs[0].text=FOP;cell.add_paragraph('Excluded');cell.add_paragraph(END);cell.add_paragraph('Kept')
        d.save(self.source);self.build()
        self.assertEqual(Document(self.output).tables[0].cell(0,0).text,'Kept')

    def test_catalog_scanner_conditional_gate(self):
        self.fixture([LEGAL,'{{supplier.name}}',END])
        report=template_catalog.scan_docx(self.source,self.fields,TYPE)
        self.assertTrue(report['can_activate_canonical'])
        self.fixture([LEGAL,'x'])
        report=template_catalog.scan_docx(self.source,self.fields,TYPE)
        self.assertFalse(report['can_activate_canonical']);self.assertTrue(report['conditional_errors'])

    def test_existing_four_packages_unchanged(self):
        from violation_protocol_docx import TEMPLATES
        for key,path in TEMPLATES.items():
            before=path.read_bytes()
            report=template_catalog.scan_docx(path,self.fields,template_catalog.RUNTIME_TYPES[key],key)
            self.assertFalse(report['conditional_errors'])
            self.assertFalse(report['unknown'])
            self.assertEqual(before,path.read_bytes())
