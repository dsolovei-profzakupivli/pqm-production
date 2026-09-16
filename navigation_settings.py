"""Global, presentation-only navbar overrides."""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ITEM_DEFAULTS={
 'workQueueNav':(None,'text',1,True),'applicationsNav':(None,'text',2,True),
 'historyNav':('history','icon',3,True),'suppliersNav':(None,'text',4,True),
 'requestsNav':('requests','icon',5,True),'referencesNav':('references','icon',6,True),
 'operationalTasksNav':(None,'text',7,True),'frameworksNav':('frameworks','icon',8,True),
 'procurementsNav':('procurements','icon',9,True),'auditBtn':('audit','icon',10,True),
 'administrationNav':('administration','icon',11,True),
 'edrMonitoringNav':(None,'text',12,True),
}
ICON_KEYS={'history','requests','references','frameworks','procurements','audit','administration'}
DISPLAY_MODES={'text','icon','icon-text'}

def migrate(con):
    con.execute('''CREATE TABLE IF NOT EXISTS navigation_settings(
      id INTEGER PRIMARY KEY CHECK(id=1),overrides_json TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT NOT NULL,updated_by TEXT NOT NULL DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS navigation_icons(
      icon_key TEXT PRIMARY KEY,name TEXT NOT NULL,svg TEXT NOT NULL,
      updated_at TEXT NOT NULL,updated_by TEXT NOT NULL DEFAULT '')''')

_SVG_TAGS={'svg','g','path','circle','rect','line','polyline','polygon','ellipse'}
_SVG_ATTRS={'viewBox','d','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','cx','cy','r','rx','ry','x','y','width','height','x1','y1','x2','y2','points','transform','opacity','fill-opacity','stroke-opacity','fill-rule','clip-rule'}
_PAINT=re.compile(r'(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]+|(?:rgb|hsl)a?\([0-9.,%+\- /degturnrad]+\))\Z')
_NUMBER=re.compile(r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?(?:px|%)?\Z')
COLOR_MODES={'original','currentColor'}
_STYLE_PAINT_ATTRS={'fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','stroke-miterlimit','fill-rule','clip-rule','opacity','fill-opacity','stroke-opacity'}
_SVG_ATTRS.add('stroke-miterlimit')

def _normalize_svg_presentation(node):
    space='{http://www.w3.org/XML/1998/namespace}space'
    if node.get(space) in {'preserve','default'}:node.attrib.pop(space)
    style=node.attrib.pop('style',None)
    if style is None:return
    if re.search(r'url\s*\(|javascript\s*:|https?\s*:|data\s*:|//',style,re.I):
        raise ValueError('Заборонене зовнішнє посилання або url(...)')
    if '\\' in style or '/*' in style:raise ValueError('Заборонений CSS escape або comment')
    # Strict declaration subset, not a CSS interpreter. No escapes/comments/URLs.
    for declaration in style.split(';'):
        if not declaration.strip():continue
        key,separator,value=declaration.partition(':');key=key.strip();value=value.strip()
        if not separator:raise ValueError('Некоректна SVG style declaration')
        if key=='enable-background' and re.fullmatch(r'new(?:(?:\s+[+\-]?(?:\d+(?:\.\d*)?|\.\d+)){4})?',value):continue
        if key not in _STYLE_PAINT_ATTRS:raise ValueError('Заборонена CSS-властивість: '+key)
        node.set(key,value)  # The same attribute/value allowlist runs below.
_EDITOR_METADATA_ATTRS={
    '{http://www.inkscape.org/namespaces/inkscape}version',
    '{http://www.inkscape.org/namespaces/inkscape}label',
    '{http://www.inkscape.org/namespaces/inkscape}groupmode',
    '{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}docname',
}

def _strip_svg_editor_metadata(root):
    # References/CSS remain forbidden: IDs have no rendering role in this subset.
    # ElementTree already discards XML comments and unused namespace declarations.
    if root.tag in {'svg','{http://www.w3.org/2000/svg}svg'}:
        root.attrib.pop('version',None)
    for node in root.iter():
        node.attrib.pop('id',None)
        for attr in _EDITOR_METADATA_ATTRS:node.attrib.pop(attr,None)
        _normalize_svg_presentation(node)
def sanitize_svg(raw):
    text=str(raw or '').strip()
    if len(text)>50000: raise ValueError('SVG завеликий')
    text=re.sub(r'^<\?xml\s+[^?]*\?>\s*','',text,count=1)
    if re.search(r'<!DOCTYPE|<!ENTITY|<\?',text,re.I):raise ValueError('Заборонена DTD або processing instruction')
    try: root=ET.fromstring(text)
    except ET.ParseError as exc: raise ValueError('Некоректний SVG') from exc
    _strip_svg_editor_metadata(root)
    for node in root.iter():
        tag=node.tag.rsplit('}',1)[-1]
        if node.tag.startswith('{') and not node.tag.startswith('{http://www.w3.org/2000/svg}'):
            raise ValueError('Заборонений namespace елемента: '+tag)
        if tag not in _SVG_TAGS or (node is root and tag!='svg'): raise ValueError('Заборонений елемент: '+tag)
        if (node.text or '').strip() or (node.tail or '').strip():raise ValueError('Заборонений текст або embedded HTML у SVG')
        node.tag=tag
        for attr,value in node.attrib.items():
            key=attr.rsplit('}',1)[-1]
            probe=str(value).casefold()
            if key.casefold().startswith('on'):raise ValueError('Заборонений атрибут: '+key)
            if key in {'href','src'} and not value.startswith('#'):raise ValueError('Заборонене зовнішнє посилання')
            if re.search(r'url\s*\(|javascript\s*:|https?\s*:|data\s*:|//',probe):raise ValueError('Заборонене зовнішнє посилання або url(...)')
            if key not in _SVG_ATTRS or attr!=key:raise ValueError('Заборонений атрибут: '+key)
            if key in {'fill','stroke'} and not _PAINT.fullmatch(value):raise ValueError('Некоректний колір: '+key)
            if key in {'stroke-width','stroke-miterlimit','opacity','fill-opacity','stroke-opacity'} and not _NUMBER.fullmatch(value):raise ValueError('Некоректне числове значення: '+key)
            choices={'stroke-linecap':{'butt','round','square'},'stroke-linejoin':{'miter','round','bevel'},'fill-rule':{'nonzero','evenodd'},'clip-rule':{'nonzero','evenodd'}}
            if key in choices and value not in choices[key]:raise ValueError('Некоректне значення: '+key)
    root.set('aria-hidden','true'); root.set('focusable','false')
    return ET.tostring(root,encoding='unicode',short_empty_elements=True)

def icon_preview(raw,mode='original',legacy=False):
    if mode not in COLOR_MODES:raise ValueError('Некоректний режим кольору')
    source_root=ET.fromstring(sanitize_svg(raw));root=ET.fromstring(ET.tostring(source_root,encoding='unicode'))
    for key in ('aria-hidden','focusable'):source_root.attrib.pop(key,None)
    source=ET.tostring(source_root,encoding='unicode')
    if mode=='currentColor':
        for node in root.iter():
            for attr in ('fill','stroke'):
                if attr in node.attrib and node.attrib[attr].casefold() not in {'none','transparent'}:node.set(attr,'currentColor')
    default_fill='none' if legacy else 'currentColor' if mode=='currentColor' else 'black'
    defaults={'fill':default_fill,'stroke':'currentColor' if legacy else 'none','stroke-width':'1.8' if legacy else '1','stroke-linecap':'round' if legacy else 'butt','stroke-linejoin':'round' if legacy else 'miter'}
    # Values are grammar-validated above. Inline presentation beats legacy navbar CSS.
    root.set('style',';'.join(k+':'+root.get(k,v) for k,v in defaults.items()))
    root.set('data-pqm-icon','true')
    return {'svg':ET.tostring(root,encoding='unicode'),'source_svg':source,'color_mode':mode}

def stored_icon(row):
    item=dict(row);root=ET.fromstring(item['svg']);mode=root.attrib.pop('data-pqm-color-mode',None)
    for key in ('aria-hidden','focusable'):root.attrib.pop(key,None)
    item.update(icon_preview(ET.tostring(root,encoding='unicode'),mode or 'original',legacy=mode is None))
    return item

def list_icons(con):
    return {'items':[stored_icon(row) for row in con.execute('SELECT icon_key,name,svg,updated_at,updated_by FROM navigation_icons ORDER BY name COLLATE NOCASE')]}

def save_icon(con,payload,user):
    key=str(payload.get('icon_key') or '').strip().lower(); name=str(payload.get('name') or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,39}',key): raise ValueError('Ключ: 2–40 латинських символів, цифр, _ або -')
    if key in ICON_KEYS: raise ValueError('Системну іконку не можна перезаписати')
    if not name or len(name)>80: raise ValueError('Вкажіть назву іконки до 80 символів')
    preview=icon_preview(payload.get('svg'),payload.get('color_mode','original'))
    root=ET.fromstring(preview['source_svg']);root.set('data-pqm-color-mode',preview['color_mode'])
    svg=ET.tostring(root,encoding='unicode'); stamp=datetime.now(timezone.utc).isoformat()
    con.execute('''INSERT INTO navigation_icons(icon_key,name,svg,updated_at,updated_by) VALUES(?,?,?,?,?)
      ON CONFLICT(icon_key) DO UPDATE SET name=excluded.name,svg=excluded.svg,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',(key,name,svg,stamp,user))
    return {'icon_key':key,'name':name,**preview,'updated_at':stamp,'updated_by':user}

def get(con):
    row=con.execute('SELECT overrides_json,updated_at,updated_by FROM navigation_settings WHERE id=1').fetchone()
    return {'overrides':json.loads(row[0] or '{}') if row else {},'updated_at':row[1] if row else '',
            'updated_by':row[2] if row else ''}

def validate(raw,icon_keys=None):
    if not isinstance(raw,dict): raise ValueError('overrides має бути object')
    merged={key:{'iconKey':d[0],'displayMode':d[1],'order':d[2],'visible':d[3]} for key,d in ITEM_DEFAULTS.items()}
    clean={}
    for key,value in raw.items():
        if key not in ITEM_DEFAULTS or not isinstance(value,dict): raise ValueError('Невідомий navigation item')
        if set(value)-{'iconKey','displayMode','order','visible'}: raise ValueError('Дозволені лише iconKey, displayMode, order, visible')
        item=dict(merged[key])
        if 'iconKey' in value:
            if value['iconKey'] is not None and value['iconKey'] not in (icon_keys or ICON_KEYS): raise ValueError('Невідома іконка')
            item['iconKey']=value['iconKey']
        if 'displayMode' in value:
            if value['displayMode'] not in DISPLAY_MODES: raise ValueError('Некоректний режим')
            item['displayMode']=value['displayMode']
        if 'order' in value:
            if isinstance(value['order'],bool) or not isinstance(value['order'],int) or not 1<=value['order']<=99: raise ValueError('Некоректний порядок')
            item['order']=value['order']
        if 'visible' in value:
            if not isinstance(value['visible'],bool): raise ValueError('visible має бути boolean')
            item['visible']=value['visible']
        merged[key]=item
    orders=[item['order'] for item in merged.values()]
    if len(orders)!=len(set(orders)): raise ValueError('Порядок пунктів не може дублюватися')
    for key,item in merged.items():
        default=dict(zip(('iconKey','displayMode','order','visible'),ITEM_DEFAULTS[key]))
        diff={field:item[field] for field in item if item[field]!=default[field]}
        if diff: clean[key]=diff
    return clean

def save(con,raw,user):
    custom={row[0] for row in con.execute('SELECT icon_key FROM navigation_icons')}; clean=validate(raw,ICON_KEYS|custom); stamp=datetime.now(timezone.utc).isoformat()
    con.execute('''INSERT INTO navigation_settings(id,overrides_json,updated_at,updated_by) VALUES(1,?,?,?)
      ON CONFLICT(id) DO UPDATE SET overrides_json=excluded.overrides_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
      (json.dumps(clean,ensure_ascii=False,separators=(',',':')),stamp,user))
    return get(con)

def reset(con):
    con.execute('DELETE FROM navigation_settings WHERE id=1')
    return get(con)
