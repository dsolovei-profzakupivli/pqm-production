"""Presentation regressions; all inputs are synthetic, with no runtime access."""
import io
import unittest
from datetime import datetime
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from openpyxl import load_workbook
import supplier_xlsx
import test_supplier_filter_excel as fixtures


class XlsxFormattingTests(unittest.TestCase):
    def rows(self):
        return [{'values':[code,name,stamp,'Активний',email,phone]} for code,name,stamp,email,phone in [
            ('0001','=literal\r\nУкраїна','2026-10-14T23:30:00Z','Case@EXAMPLE.invalid','+380001; 001'),
            ('0002','Ранній','2026-10-15T02:30:00.004491+03:00','',''),
            ('0003','Пізніший','2026-10-15T02:30:00.004492+03:00','',''),
            ('0004','Немає дати','','',''),('0005','Некоректна','invalid','','')]]

    def sheet(self,rows=None):
        return load_workbook(io.BytesIO(supplier_xlsx.workbook(self.rows() if rows is None else rows))).active

    def test_exact_order_then_invalid_dates_last_without_input_mutation(self):
        rows=self.rows();original=repr(rows);ws=self.sheet(rows)
        self.assertEqual([ws.cell(i,1).value for i in range(2,7)],['0003','0002','0001','0004','0005'])
        self.assertEqual(repr(rows),original)
        self.assertIsNone(ws['C5'].value);self.assertIsNone(ws['C6'].value)

    def test_typed_kyiv_calendar_date_and_format(self):
        ws=self.sheet()
        for i in range(2,5):
            c=ws.cell(i,3)
            self.assertEqual(c.value,datetime(2026,10,15));self.assertEqual(c.data_type,'d')
            self.assertEqual(c.number_format,'dd.mm.yyyy')

    def test_dst_date_boundaries(self):
        rows=[{'values':['01','Весна','2026-03-28T22:30:00Z','','','']},
              {'values':['02','Осінь','2026-10-24T21:30:00Z','','','']}]
        ws=self.sheet(rows)
        self.assertEqual(ws['C2'].value,datetime(2026,10,25))
        self.assertEqual(ws['C3'].value,datetime(2026,3,29))

    def test_literal_values_formula_guard_crlf_and_contacts(self):
        ws=self.sheet();self.assertEqual(ws['A4'].value,'0001');self.assertEqual(ws['A4'].data_type,'s')
        self.assertEqual(ws['B4'].value,'=literal\r\nУкраїна');self.assertEqual(ws['B4'].data_type,'s')
        self.assertEqual(ws['E4'].value,'Case@EXAMPLE.invalid');self.assertEqual(ws['F4'].value,'+380001; 001')
        self.assertTrue(all(c.data_type!='f' for row in ws for c in row))

    def test_table_filter_freeze_borders_and_no_protection(self):
        ws=self.sheet();self.assertEqual(ws.max_column,6)
        self.assertEqual([c.value for c in ws[1]],list(supplier_xlsx.HEADERS))
        self.assertEqual(ws.tables['PqmSuppliers'].ref,'A1:F6')
        self.assertEqual(ws.tables['PqmSuppliers'].autoFilter.ref,'A1:F6')
        self.assertIsNone(ws.auto_filter.ref);self.assertEqual(ws.freeze_panes,'A2')
        self.assertFalse(ws.protection.sheet);self.assertEqual(ws['A2'].border.bottom.style,'thin')

    def test_top_alignment_wrapping_and_height(self):
        ws=self.sheet()
        for row in ws:
            for c in row:self.assertEqual(c.alignment.vertical,'top')
        for column in 'BEF':self.assertTrue(ws[column+'2'].alignment.wrap_text)
        rows=[{'values':['01','Довга назва '*30,'2026-10-14T14:00:00+03:00','','Email'*50,'+380 '*30]}]
        self.assertGreater(self.sheet(rows).row_dimensions[2].height,30)

    def test_empty_table_and_missing_fields(self):
        ws=self.sheet([]);self.assertEqual(ws.max_row,1);self.assertEqual(ws.tables['PqmSuppliers'].ref,'A1:F1')

    def test_ooxml_single_filter_owner_and_consistent_table_relationship(self):
        ns={'s':supplier_xlsx.NS,'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        for rows in ([],self.rows()[:1],self.rows()):
            with self.subTest(count=len(rows)),ZipFile(io.BytesIO(supplier_xlsx.workbook(rows))) as z:
                sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                table=ET.fromstring(z.read('xl/tables/table1.xml'))
                self.assertIsNone(sheet.find('s:autoFilter',ns),'Worksheet filter must not overlap table filter')
                filters=table.findall('s:autoFilter',ns)
                self.assertEqual(len(filters),1)
                self.assertEqual(filters[0].get('ref'),table.get('ref'))
                self.assertEqual(table.get('ref'),'A1:F'+str(len(rows)+1))
                columns=table.findall('s:tableColumns/s:tableColumn',ns)
                self.assertEqual([c.get('name') for c in columns],list(supplier_xlsx.HEADERS))
                self.assertEqual([c.get('id') for c in columns],['1','2','3','4','5','6'])
                parts=sheet.findall('s:tableParts/s:tablePart',ns);self.assertEqual(len(parts),1)
                rel=ET.fromstring(z.read('xl/worksheets/_rels/sheet1.xml.rels'))[0]
                self.assertEqual(parts[0].get('{'+ns['r']+'}id'),rel.get('Id'))
                self.assertEqual(rel.get('Target'),'../tables/table1.xml')

    def test_no_silent_row_height_clipping(self):
        with self.assertRaisesRegex(ValueError,'висоту'):
            self.sheet([{'values':['1','X'*32767,'','','','']}])

    def test_black_text_grid_widths_and_compact_height(self):
        ws=self.sheet()
        self.assertEqual(ws.row_dimensions[1].height,34)
        self.assertEqual(ws.row_dimensions[2].height,22)
        self.assertEqual(ws.row_dimensions[4].height,34)
        self.assertEqual(supplier_xlsx.row_height(['1','a\nb\nc','','','','']),49)
        for col,width in zip('ABCDEF',(21,55,20,22,38,28)):
            self.assertEqual(ws.column_dimensions[col].width,width)
        for row in ws:
            for cell in row:
                self.assertEqual(cell.font.color.rgb,'FF000000')
                self.assertEqual(cell.font.sz,11)
                self.assertEqual(cell.font.name,'Arial')
                self.assertEqual(cell.font.b,cell.row==1)
                self.assertEqual(cell.alignment.horizontal,'left')
                self.assertEqual(cell.alignment.vertical,'top')
                for edge in ('left','right','top','bottom'):
                    side=getattr(cell.border,edge)
                    self.assertEqual(side.style,'thin');self.assertEqual(side.color.rgb,'FFD0DAE3')
        self.assertEqual(ws['A1'].fill.fgColor.rgb,'FFDCE6F1')

    def test_dynamic_table_style_has_exact_stripes_and_no_white_font(self):
        with ZipFile(io.BytesIO(supplier_xlsx.workbook(self.rows()))) as z:
            ns={'s':supplier_xlsx.NS}
            styles=ET.fromstring(z.read('xl/styles.xml'))
            table=ET.fromstring(z.read('xl/tables/table1.xml'))
            self.assertEqual(table.find('s:tableStyleInfo',ns).get('name'),supplier_xlsx.TABLE_STYLE)
            self.assertEqual(table.find('s:tableStyleInfo',ns).get('showRowStripes'),'1')
            custom=styles.find('s:tableStyles/s:tableStyle',ns)
            self.assertEqual(custom.get('name'),supplier_xlsx.TABLE_STYLE)
            dxfs=styles.findall('s:dxfs/s:dxf',ns)
            expected={'wholeTable':'FFFFFFFF','headerRow':'FFDCE6F1','firstRowStripe':'FFFFFFFF','secondRowStripe':'FFEDF3F8'}
            for element in custom:
                kind=element.get('type');dxf=dxfs[int(element.get('dxfId'))]
                self.assertEqual(dxf.find('s:fill/s:patternFill/s:fgColor',ns).get('rgb'),expected[kind])
                self.assertEqual(dxf.find('s:font/s:color',ns).get('rgb'),'FF000000')
                self.assertEqual(dxf.find('s:font/s:b',ns).get('val'),'1' if kind=='headerRow' else '0')
                for edge in ('left','right','top','bottom','vertical','horizontal'):
                    side=dxf.find('s:border/s:'+edge,ns)
                    self.assertEqual(side.get('style'),'thin');self.assertEqual(side[0].get('rgb'),'FFD0DAE3')
                if kind.endswith('Stripe'):self.assertEqual(element.get('size'),'1')

    def test_borders_only_in_table_and_gridlines_hidden(self):
        ws=self.sheet()
        self.assertFalse(ws.sheet_view.showGridLines)
        for coordinate in ('G1','G2','A8','A100','Z100'):
            cell=ws[coordinate]
            for edge in ('left','right','top','bottom'):
                side=getattr(cell.border,edge)
                self.assertTrue(side is None or side.style is None,coordinate)
        with ZipFile(io.BytesIO(supplier_xlsx.workbook(self.rows()))) as z:
            ns={'s':supplier_xlsx.NS}
            styles=ET.fromstring(z.read('xl/styles.xml'))
            sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(styles.find('s:cellXfs/s:xf',ns).get('borderId'),'0')
            self.assertEqual(styles.find('s:cellStyleXfs/s:xf',ns).get('borderId'),'0')
            self.assertEqual(len(styles.find('s:borders/s:border',ns)),0)
            self.assertEqual(sheet.find('s:sheetViews/s:sheetView',ns).get('showGridLines'),'0')
            self.assertFalse(sheet.findall('s:cols/s:col[@style]',ns))
            self.assertFalse(sheet.findall('s:sheetData/s:row[@s]',ns))
            cells=sheet.findall('s:sheetData/s:row/s:c',ns)
            self.assertEqual(len(cells),36)
            self.assertTrue(all(c.get('s') in {'1','2','3','4'} for c in cells))

    def test_table_dxf_fill_channels_are_explicit_identical_and_never_black(self):
        """Catches the actual Excel regression missed by fgColor-only checks."""
        with ZipFile(io.BytesIO(supplier_xlsx.workbook(self.rows()))) as z:
            ns={'s':supplier_xlsx.NS}
            styles=ET.fromstring(z.read('xl/styles.xml'))
            fills=styles.findall('s:dxfs/s:dxf/s:fill/s:patternFill',ns)
            self.assertEqual(len(fills),4)
            expected=['FFFFFFFF','FFDCE6F1','FFFFFFFF','FFEDF3F8']
            for fill,color in zip(fills,expected):
                self.assertEqual(fill.attrib,{'patternType':'solid'})
                for channel in ('fgColor','bgColor'):
                    node=fill.find('s:'+channel,ns)
                    self.assertIsNotNone(node)
                    self.assertEqual(node.attrib,{'rgb':color})
                    self.assertNotEqual(node.get('rgb'),'FF000000')
                    self.assertEqual(node.get('rgb')[:2],'FF')
            # Body XFs must not introduce an overriding solid fill.
            xfs=styles.findall('s:cellXfs/s:xf',ns)
            for xf in xfs[:4]:self.assertEqual(xf.get('fillId'),'0')

    def test_formula_prefixes_are_unchanged_literal_text(self):
        for prefix in '=+-@':
            value=prefix+'literal'
            ws=self.sheet([{'values':[value,value,'2026-10-14T12:00:00+03:00',value,value,value]}])
            for col in 'ABDEF':
                self.assertEqual(ws[col+'2'].value,value);self.assertEqual(ws[col+'2'].data_type,'s')


class FilenameTests(unittest.TestCase):
    def test_framework_search_name_category_and_intersection(self):
        fixture=fixtures.SupplierFilterExcelTests();fixture.setUp()
        try:
            import server
            fixture.con.execute("INSERT INTO framework_service_directory(pretty_id,framework_id,category,synced_at) VALUES('UA-F-f1','f1','Металеві вироби','synthetic')")
            for search in ('ВІДБІР F1','МЕТАЛЕВІ ВИРОБИ','UA-F-f1','03110000-1'):
                result=server.framework_registry({'search':[search],'dk_code':['03110000-1']},fixture.con)
                self.assertIn('f1',[item['framework_id'] for item in result['items']])
            self.assertEqual(server.framework_registry({'search':['Металеві'],'dk_code':['03220000-2']},fixture.con)['total'],0)
        finally:fixture.doCleanups()

    def test_filename_uses_cached_framework_not_search_input(self):
        fixture=fixtures.SupplierFilterExcelTests();fixture.setUp()
        try:
            import server
            params={'registry_only':['1'],'framework_id':['f1'],'dk_code':['FAKE']}
            self.assertEqual(server.supplier_registry_excel_filename(params,connection=fixture.con),'03110000-1_pqm-suppliers.xlsx')
            params['framework_id']=['f1','f2']
            self.assertEqual(server.supplier_registry_excel_filename(params,connection=fixture.con),'pqm-suppliers.xlsx')
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
