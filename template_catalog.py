"""Versioned document API metadata. No renderer, business queries or implicit bindings."""
import copy
import json
import os
import re
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from document_semantics import supplier_code_label
import derived_fields
import document_bindings

CATALOG=Path(__file__).parent/'metadata/template_fields.v1.json'
LEGACY=CATALOG.with_name('template_legacy_tokens.v1.json')
LOCK=threading.RLock()
VALUE_TYPES={'string','integer','decimal','boolean','date','datetime','url','enum','object','array<object>'}
RUNTIME_TYPES={'warning':'warning_notice','decline_p49_1_2':'decline_p49_1_2','decline_p49_3':'decline_p49_3','application_protocol':'application_review_protocol'}

def load(path=CATALOG):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def validate(data,schema):
    sources={x['id']:x for x in schema['items']}
    items=[];seen=set()
    for raw in data['fields']:
        f=copy.deepcopy(raw);errors=[];key=f['key'];b=f['source_binding'];kind=b.get('source_type')
        if key in seen:errors.append('DUPLICATE_KEY')
        seen.add(key)
        if f['value_type'] not in VALUE_TYPES:errors.append('INVALID_TYPE')
        if set(f['available_for'])-set(data['document_types']):errors.append('UNKNOWN_DOCUMENT_TYPE')
        if set(f.get('required_for',[]))-set(f['available_for']):errors.append('INVALID_REQUIRED_FOR')
        if f.get('replacement_key') and f['replacement_key'] not in {x['key'] for x in data['fields']}:errors.append('UNKNOWN_REPLACEMENT')
        deps=[b.get('schema_field')] if kind=='schema_field' else b.get('dependencies',[]) if kind=='derived' else []
        if kind not in {'schema_field','derived','unbound'}:errors.append('INVALID_BINDING')
        if kind=='derived' and not b.get('description'):errors.append('MISSING_DERIVATION')
        errors.extend(document_bindings.binding_errors(b))
        for dep in deps:
            source=sources.get(dep)
            if not source:errors.append('BROKEN_BINDING: '+str(dep));continue
            if (source.get('technical') or source.get('private')) and dep not in b.get('allow_technical',[]):errors.append('PRIVATE_BINDING: '+dep)
            if kind=='schema_field':
                sql=source.get('type','').upper();typ=f['value_type']
                ok=(typ in {'string','enum','date','datetime','url'} and ('TEXT' in sql or 'CHAR' in sql)) or (typ in {'integer','boolean'} and 'INT' in sql) or (typ=='decimal' and any(x in sql for x in ['REAL','NUM','DEC','INT'])) or source.get('kind')!='physical'
                if not ok:errors.append('INCOMPATIBLE_TYPE: '+dep)
        f['validation_errors']=errors
        f['binding_status']='BROKEN_BINDING' if errors else 'PROPOSED_UNBOUND' if kind=='unbound' else 'VALID'
        items.append(f)
    lookup={f['key']:f for f in items}
    for f in items:
        if derived_fields.configured(f):
            f['validation_errors'].extend(derived_fields.configuration_errors(f,lookup))
            if f['validation_errors']:f['binding_status']='BROKEN_BINDING'
    for _ in items:
        changed=False
        for f in items:
            if derived_fields.configured(f) and f['binding_status']=='VALID':
                if any(not lookup.get(dep) or lookup[dep]['binding_status']!='VALID' for dep in derived_fields.dependencies(f)):
                    f['validation_errors'].append('BROKEN_DERIVED_SOURCE');f['binding_status']='BROKEN_BINDING';changed=True
        if not changed:break
    return items

def project(schema,data=None):
    data=data or load();fields=validate(data,schema)
    index={}
    for f in fields:
        if not f['active'] or f['deprecated'] or f['binding_status']!='VALID':continue
        b=f['source_binding'];deps=[b['schema_field']] if b['source_type']=='schema_field' else b.get('dependencies',[])
        for dep in deps:index.setdefault(dep,[]).append(f)
    for item in schema['items']:
        used=index.get(item['id'],[])
        item.update(used_in_templates=bool(used),template_keys=[x['key'] for x in used],
          template_groups=sorted({x['group'] for x in used}),document_types=sorted({t for x in used for t in x['available_for']}),
          template_fields=[{k:x[k] for k in ('key','label','group','value_type','available_for','source_binding')} for x in used])
    # Semantic catalog fields are visible records, never new physical DB columns.
    group='Похідні поля документів'
    if group not in schema['groups']:schema['groups'].append(group)
    schema['items']=[x for x in schema['items'] if not x['id'].startswith('document_field.')]
    for f in fields:
        b=f['source_binding']
        if b['source_type']!='derived':continue
        schema['items'].append({'id':'document_field.'+f['key'],'key':f['key'],'label':f['label'],
          'description':f['description'],'kind':'derived','database':'document_context','table':None,'type':f['value_type'],
          'groups':[group],'modules':[],'source':b.get('source_field') or ', '.join(b.get('dependencies',[])),
          'source_field':b.get('source_field'),'transformation':copy.deepcopy(b),'technical':False,
          'status':'approved' if f['binding_status']=='VALID' else 'unapproved','editing':'system',
          'editing_note':'Конфігурація — Адміністрування → Каталог полів шаблонів',
          'structure_source':'Template Field Catalog; не колонка SQLite','template_fields':[f],
          'used_in_templates':f['active'] and not f['deprecated'],'template_keys':[f['key']],
          'document_types':f['available_for'],'template_groups':[f['group']]})
    return schema

def catalog(schema,document_type='',search='',path=CATALOG):
    data=load(path)
    if document_type and document_type not in data['document_types']:raise ValueError('Невідомий тип документа')
    items=validate(data,schema);q=search.strip().casefold()
    items=[f for f in items if (not document_type or document_type in f['available_for']) and (not q or any(q in str(f.get(k,'')).casefold() for k in ('label','description','group','key')))]
    return {'version':data['version'],'revision':data['revision'],'document_types':data['document_types'],'items':items,
            'transformations':derived_fields.TRANSFORMATIONS}


def save_derived(schema,payload,actor,role,path=CATALOG):
    if role!='admin':raise PermissionError('Лише Адміністратор')
    if not isinstance(payload,dict):raise ValueError('Некоректна конфігурація')
    allowed={'key','label','source_field','transformation_type','grammatical_case','entity_type','available_for','revision','mode','condition_field','equals','prefix'}
    if set(payload)-allowed:raise ValueError('Непідтримуваний параметр')
    with LOCK:
        data=load(path)
        if payload.get('revision')!=data['revision']:raise ValueError('Каталог змінено. Оновіть сторінку.')
        field=derived_fields.make_field(payload,data)
        old=next((f for f in data['fields'] if f['key']==field['key']),None)
        if payload.get('mode')=='create':
            if old:raise ValueError('Ключ уже існує')
        elif payload.get('mode')=='update':
            if not old or not derived_fields.configured(old):raise ValueError('Можна змінювати тільки configurable derived field')
        else:raise ValueError('Некоректний режим')
        before=copy.deepcopy(old)
        if old:
            field['required_for']=old['required_for']
            old.update(field)
        else:data['fields'].append(field)
        errors=[e for f in validate(data,schema) for e in f['validation_errors']]
        if errors:raise ValueError('Конфігурація невалідна: '+'; '.join(errors))
        if before==field:return data
        data['revision']+=1
        data['audit'].append({'at':datetime.now(timezone.utc).isoformat(),'by':actor,'key':field['key'],
                              'old':before,'new':copy.deepcopy(field)})
        path=Path(path);tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,path)
        return data

def update_field(schema,key,patch,actor,role,revision,path=CATALOG):
    if role!='admin':raise PermissionError('Лише Адміністратор')
    allowed={'label','description','group','value_type','source_binding','available_for','required_for','default_format','example','nullable','active','deprecated','replacement_key','item_schema'}
    if set(patch)-allowed:raise ValueError('Непідтримуване поле конфігурації')
    with LOCK:
        data=load(path)
        if revision!=data['revision']:raise ValueError('Каталог змінено. Оновіть сторінку.')
        old=next((f for f in data['fields'] if f['key']==key),None)
        if not old:raise ValueError('Невідомий stable key')
        before=copy.deepcopy(old);old.update(patch)
        if not isinstance(old.get('source_binding'),dict):raise ValueError('Binding має бути об’єктом')
        for name in ('available_for','required_for'):
            if not isinstance(old.get(name),list) or not all(isinstance(x,str) for x in old[name]):raise ValueError('Перелік типів документів має бути масивом')
        for name in ('dependencies','allow_technical'):
            values=old['source_binding'].get(name,[])
            if not isinstance(values,list) or not all(isinstance(x,str) for x in values):raise ValueError('Залежності мають бути масивом ідентифікаторів Схеми')
        for flag in ('active','deprecated','nullable'):
            if not isinstance(old[flag],bool):raise ValueError('Некоректне логічне значення')
        checked=next(f for f in validate(data,schema) if f['key']==key)
        if checked['validation_errors']:raise ValueError('; '.join(checked['validation_errors']))
        invalid=[f for f in validate(data,schema) if derived_fields.configured(f) and f['validation_errors']]
        if invalid:raise ValueError('Зміна пошкоджує похідне поле: '+invalid[0]['key'])
        if before==old:return data
        data['revision']+=1;data['audit'].append({'at':datetime.now(timezone.utc).isoformat(),'by':actor,'key':key,'old':before,'new':copy.deepcopy(old)})
        path=Path(path);tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,path)
        return data

def scan_docx(path,fields,document_type,runtime_key=''):
    from docx_conditionals import plan
    from template_conditions import ConditionalError
    from lxml import etree
    conditional_errors=[]
    tokens=set()
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not(name.startswith('word/') and name.endswith('.xml')):continue
            raw=z.read(name)
            root=ET.fromstring(raw)
            texts=[''.join(x.text or '' for x in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                   for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')]
            if any('{{#if' in t or '{{/if' in t for t in texts):
                try:
                    blocks,_=plan(etree.fromstring(raw),fields,document_type,
                                  validate_scalars=not bool(runtime_key))
                    tokens.update(condition.key for condition,_ in blocks)
                except ConditionalError as exc:conditional_errors.append(str(exc))
            for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                text=''.join(x.text or '' for x in paragraph.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                tokens.update(x.strip().lstrip('#/') for x in re.findall(r'\{\{\s*(.*?)\s*\}\}',text)
                              if not x.strip().startswith(('#if','/if')))
    legacy=set(load(LEGACY).get(runtime_key,[]));lookup={f['key']:f for f in fields}
    report={k:[] for k in ('recognized','legacy','unknown','unavailable','broken_bindings')}
    for token in sorted(tokens):
        if token in legacy or any(x.startswith(token+'.') for x in legacy):report['legacy'].append(token);continue
        f=lookup.get(token)
        if not f:report['unknown'].append(token);continue
        report['recognized'].append(token)
        if document_type not in f['available_for'] or not f['active'] or f['deprecated']:report['unavailable'].append(token)
        if f['binding_status']!='VALID':report['broken_bindings'].append(token)
    report['conditional_errors']=conditional_errors
    report['can_activate_canonical']=not any(report[k] for k in ('unknown','unavailable','broken_bindings','legacy','conditional_errors'))
    report['mode']='advisory_legacy_runtime_unchanged'
    return report

def templates_metadata(items,schema,paths):
    fields=validate(load(),schema)
    return [{**x,'template_key':x['key'],'document_type':RUNTIME_TYPES[x['key']],'format':'docx','generation_provider':'docx_local',
      'active':bool(x['exists']),'output_name_pattern':None,'provider_config':None,'destination_config':None,
      'validation':scan_docx(paths[x['key']],fields,RUNTIME_TYPES[x['key']],x['key']) if x['exists'] else None} for x in items]
