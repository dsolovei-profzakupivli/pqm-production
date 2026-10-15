"""Small in-memory OOXML export. Explicit inline strings cannot execute formulas."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
import re

HEADERS=('ЄДРПОУ / РНОКПП','Найменування постачальника','Дата кваліфікації',
         'Статус у відборі','Email із заявки','Телефон із заявки')
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def workbook(rows):
    if len(rows)>1048575:
        raise ValueError('Вибірка перевищує максимальну кількість рядків Excel')
    root=Element('worksheet',xmlns=NS)
    views=SubElement(root,'sheetViews');view=SubElement(views,'sheetView',workbookViewId='0')
    SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
    cols=SubElement(root,'cols')
    for i,width in enumerate((24,58,40,24,40,25),1):
        SubElement(cols,'col',min=str(i),max=str(i),width=str(width),customWidth='1')
    data=SubElement(root,'sheetData')
    for number,values in enumerate([HEADERS]+[r['values'] for r in rows],1):
        row=SubElement(data,'row',r=str(number))
        for column,value in enumerate(values):
            text=str(value or '')
            if len(text)>32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',text):
                raise ValueError('Значення не можна без втрат експортувати в Excel')
            cell=SubElement(row,'c',r=chr(65+column)+str(number),t='inlineStr')
            inline=SubElement(cell,'is');node=SubElement(inline,'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
            node.text=text
    SubElement(root,'autoFilter',ref='A1:F'+str(len(rows)+1))
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>''')
        z.writestr('_rels/.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr('xl/workbook.xml','''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Постачальники" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        z.writestr('xl/_rels/workbook.xml.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>''')
        # Literal CR must be a character reference: XML normalizes raw CR/CRLF
        # before a spreadsheet reader sees it. Keep inline strings, never formulas.
        xml=tostring(root,encoding='utf-8',xml_declaration=True).replace(b'\r',b'&#13;')
        z.writestr('xl/worksheets/sheet1.xml',xml)
    return output.getvalue()
