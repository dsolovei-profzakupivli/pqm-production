"""Small in-memory OOXML export. Explicit inline strings cannot execute formulas."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
import re
import math
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

HEADERS=('ЄДРПОУ / РНОКПП','Найменування постачальника','Дата кваліфікації',
         'Статус у відборі','Email із заявки','Телефон із заявки')
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
WIDTHS=(21,55,20,22,38,28)
TABLE_STYLE='PqmSupplierRegistryStyle'


def qualification_instant(value):
    """Presentation only; never replace missing evidence or modify the source."""
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError,TypeError):
        return None


def row_height(values):
    # Conservative wrapping estimate for Arial 11, including explicit CRLF.
    lines=max(sum(max(1,math.ceil(len(part)/max(1,int(WIDTHS[i]*0.85))))
                  for part in str(values[i] or '').splitlines() or ['']) for i in (1,4,5))
    height=max(22,lines*15+4)
    if height>409:
        raise ValueError('Текст перевищує читабельну висоту рядка Excel')
    return height


def styles_xml():
    root=Element('styleSheet',xmlns=NS)
    formats=SubElement(root,'numFmts',count='1')
    SubElement(formats,'numFmt',numFmtId='164',formatCode='dd.mm.yyyy')
    fonts=SubElement(root,'fonts',count='2')
    for bold in (False,True):
        font=SubElement(fonts,'font');SubElement(font,'sz',val='11');SubElement(font,'color',rgb='FF000000');SubElement(font,'name',val='Arial')
        if bold:SubElement(font,'b')
    fills=SubElement(root,'fills',count='3')
    for pattern in ('none','gray125','solid'):
        p=SubElement(SubElement(fills,'fill'),'patternFill',patternType=pattern)
        if pattern=='solid':SubElement(p,'fgColor',rgb='FFDCE6F1');SubElement(p,'bgColor',indexed='64')
    borders=SubElement(root,'borders',count='2');SubElement(borders,'border')
    border=SubElement(borders,'border')
    for edge in ('left','right','top','bottom'):
        SubElement(SubElement(border,edge,style='thin'),'color',rgb='FFD0DAE3')
    base=SubElement(root,'cellStyleXfs',count='1')
    SubElement(base,'xf',numFmtId='0',fontId='0',fillId='0',borderId='0')
    xfs=SubElement(root,'cellXfs',count='5')
    # default, literal text, wrapped literal text, Excel date, heading
    for index,(fmt,wrap,header) in enumerate(((0,False,False),(49,False,False),(49,True,False),(164,False,False),(0,True,True))):
        xf=SubElement(xfs,'xf',numFmtId=str(fmt),fontId='1' if header else '0',fillId='2' if header else '0',
                      borderId='0' if index==0 else '1',xfId='0',applyAlignment='1',applyNumberFormat='1',applyFont='1',applyBorder='1',applyFill='1' if header else '0')
        SubElement(xf,'alignment',vertical='top',horizontal='left',wrapText='1' if wrap else '0')
    cs=SubElement(root,'cellStyles',count='1');SubElement(cs,'cellStyle',name='Normal',xfId='0',builtinId='0')
    # Custom differential table style: dynamic row bands survive Excel sorting,
    # with no built-in theme font changing black text to white.
    dxfs=SubElement(root,'dxfs',count='4')
    for i,color in enumerate(('FFFFFFFF','FFDCE6F1','FFFFFFFF','FFEDF3F8')):
        dxf=SubElement(dxfs,'dxf')
        font=SubElement(dxf,'font');SubElement(font,'b',val='1' if i==1 else '0');SubElement(font,'color',rgb='FF000000')
        p=SubElement(SubElement(dxf,'fill'),'patternFill',patternType='solid')
        # Excel table DXFs consume the background colour too, unlike ordinary
        # solid cell fills. Indexed 64 here produced black row bands in Excel.
        # Set both channels explicitly; never rely on automatic/theme colours.
        SubElement(p,'fgColor',rgb=color);SubElement(p,'bgColor',rgb=color)
        border=SubElement(dxf,'border')
        for edge in ('left','right','top','bottom','vertical','horizontal'):
            SubElement(SubElement(border,edge,style='thin'),'color',rgb='FFD0DAE3')
    table_styles=SubElement(root,'tableStyles',count='1',defaultTableStyle=TABLE_STYLE)
    style=SubElement(table_styles,'tableStyle',name=TABLE_STYLE,pivot='0',table='1',count='4')
    for kind,index in (('wholeTable',0),('headerRow',1),('firstRowStripe',2),('secondRowStripe',3)):
        attrs={'type':kind,'dxfId':str(index)}
        if kind.endswith('Stripe'):attrs['size']='1'
        SubElement(style,'tableStyleElement',**attrs)
    return tostring(root,encoding='utf-8',xml_declaration=True)


def workbook(rows):
    if len(rows)>1048575:
        raise ValueError('Вибірка перевищує максимальну кількість рядків Excel')
    root=Element('worksheet',xmlns=NS)
    views=SubElement(root,'sheetViews');view=SubElement(views,'sheetView',workbookViewId='0',showGridLines='0')
    SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
    cols=SubElement(root,'cols')
    for i,width in enumerate(WIDTHS,1):
        SubElement(cols,'col',min=str(i),max=str(i),width=str(width),customWidth='1')
    data=SubElement(root,'sheetData')
    ordered=sorted(rows,key=lambda r:qualification_instant(r['values'][2]) or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
    for number,values in enumerate([HEADERS]+[r['values'] for r in ordered],1):
        row=SubElement(data,'row',r=str(number),ht=str(34 if number==1 else row_height(values)),customHeight='1')
        for column,value in enumerate(values):
            text=str(value or '')
            if len(text)>32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',text):
                raise ValueError('Значення не можна без втрат експортувати в Excel')
            instant=qualification_instant(value) if column==2 and number>1 else None
            if instant:
                # Calendar date in PQM's operational timezone. Original instant
                # remains intact in PQM and is used above for exact ordering.
                day=instant.astimezone(ZoneInfo('Europe/Kyiv')).date()
                serial=(day-date(1899,12,30)).days
                cell=SubElement(row,'c',r='C'+str(number),s='3',t='n')
                SubElement(cell,'v').text=str(serial)
                continue
            if column==2 and number>1:
                SubElement(row,'c',r='C'+str(number),s='3')
                continue
            cell=SubElement(row,'c',r=chr(65+column)+str(number),t='inlineStr',s='4' if number==1 else ('2' if column in (1,4,5) else '1'))
            inline=SubElement(cell,'is');node=SubElement(inline,'t',{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
            node.text=text
    # Filtering belongs to the Excel Table below. A worksheet AutoFilter on
    # the same range overlaps it and Excel repairs/removes the table filter.
    parts=SubElement(root,'tableParts',count='1',**{'xmlns:r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'})
    SubElement(parts,'tablePart',**{'r:id':'rId1'})
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/></Types>''')
        z.writestr('_rels/.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr('xl/workbook.xml','''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Постачальники" sheetId="1" r:id="rId1"/></sheets></workbook>''')
        z.writestr('xl/_rels/workbook.xml.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        # Literal CR must be a character reference: XML normalizes raw CR/CRLF
        # before a spreadsheet reader sees it. Keep inline strings, never formulas.
        xml=tostring(root,encoding='utf-8',xml_declaration=True).replace(b'\r',b'&#13;')
        z.writestr('xl/worksheets/sheet1.xml',xml)
        z.writestr('xl/styles.xml',styles_xml())
        table=Element('table',xmlns=NS,id='1',name='PqmSuppliers',displayName='PqmSuppliers',ref='A1:F'+str(len(rows)+1),totalsRowShown='0')
        SubElement(table,'autoFilter',ref='A1:F'+str(len(rows)+1))
        columns=SubElement(table,'tableColumns',count='6')
        for i,label in enumerate(HEADERS,1):SubElement(columns,'tableColumn',id=str(i),name=label)
        SubElement(table,'tableStyleInfo',name=TABLE_STYLE,showFirstColumn='0',showLastColumn='0',showRowStripes='1',showColumnStripes='0')
        z.writestr('xl/tables/table1.xml',tostring(table,encoding='utf-8',xml_declaration=True))
        z.writestr('xl/worksheets/_rels/sheet1.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/></Relationships>')
    return output.getvalue()
