"""Stage 2D: generation only, no NAZK transitions or direction records."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import operational_tasks
import template_catalog
import template_runtime
from declension import normalize_document_name
from document_semantics import supplier_code_semantics
import derived_fields
import document_bindings
import document_metadata
from supplier_contacts import supplier_contacts
from supplier_identity import (current_manager_rnokpp, document_name as supplier_document_name,
                               document_short_name as supplier_document_short_name)
from docx_conditionals import render, condition_keys, retained_scalar_keys

KEY='nazk_supplier_request'  # Server-owned action mapping, never supplied by client.

def migrate(con):
    con.executescript('''CREATE TABLE IF NOT EXISTS generated_documents (
      id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES operational_tasks(id),
      supplier_code TEXT NOT NULL, document_type TEXT NOT NULL, template_key TEXT NOT NULL,
      template_reference TEXT NOT NULL, filename TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL, generation_provider TEXT NOT NULL,
      status TEXT NOT NULL, document_date TEXT NOT NULL, version INTEGER NOT NULL,
      sha256 TEXT NOT NULL, UNIQUE(task_id,document_type,document_date,version));
      CREATE INDEX IF NOT EXISTS ix_generated_documents_task ON generated_documents(task_id,created_at);
    ''')
    columns={row[1] for row in con.execute('PRAGMA table_info(generated_documents)')}
    if 'metadata_json' not in columns:
        con.execute("ALTER TABLE generated_documents ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
    document_metadata.migrate(con)

def public_document(row):
    item=dict(row);item.pop('storage_name',None)
    raw=item.pop('metadata_json',None)
    try:item['metadata']=json.loads(raw or '{}')
    except (TypeError,json.JSONDecodeError):item['metadata']={}
    item['resolved_metadata']=document_metadata.resolved_items(item['metadata'])
    item['download_url']=f"/api/operational-tasks/{item['task_id']}/documents/{item['id']}/download"
    return item

def documents(con,task_id):
    return [public_document(r) for r in con.execute('SELECT * FROM generated_documents WHERE task_id=? ORDER BY created_at DESC,id DESC',(task_id,))]

def resolve_context(con,item,fields,config,keys=None):
    if item['task_type']!='nazk_check':raise ValueError('Документ доступний тільки для НАЗК-перевірки')
    if item['status'] in operational_tasks.TERMINAL:raise ValueError('Для завершеної задачі формування недоступне')
    manager=item.get('current_manager') or {}
    if not manager.get('manager_name'):raise ValueError('Неможливо сформувати запит: не визначено поточного керівника')
    if not item.get('task_person_is_current'):raise ValueError('Неможливо сформувати запит: особа задачі більше не є поточним керівником')
    if not item.get('effective_active_count'):raise ValueError('Неможливо сформувати запит: відсутні активні кваліфікації')
    if not item.get('nazk_records'):raise ValueError('Неможливо сформувати запит: відсутній пов’язаний запис Реєстру НАЗК')
    code=re.sub(r'\D','',str(item['supplier_code']))
    row=con.execute('SELECT * FROM supplier_registry_summary WHERE DIGITS(supplier_code)=?',(code,)).fetchone()
    data=dict(row) if row else {}
    semantics=supplier_code_semantics(str(data.get('supplier_code') or ''))
    contacts=supplier_contacts(con,code)
    name=supplier_document_name(con,code)
    data['document_name']=normalize_document_name(name) if semantics['entity_type']=='legal_entity' else name
    short_name=supplier_document_short_name(con,code)
    data['document_short_name']=normalize_document_name(short_name) if semantics['entity_type']=='legal_entity' else short_name
    resolved_rnokpp=current_manager_rnokpp(con,code,manager)
    if resolved_rnokpp['value']:
        manager={**manager,'manager_tax_id':resolved_rnokpp['value'],
                 'manager_tax_id_resolved_source':resolved_rnokpp['source']}
    def manager_record():
        row=con.execute('SELECT * FROM supplier_managers WHERE id=? AND DIGITS(supplier_code)=? AND is_current=1',(manager.get('id'),code)).fetchone()
        if not row:raise ValueError('Поточний керівник змінився. Оновіть картку.')
        result=dict(row)
        current_value=current_manager_rnokpp(con,code,result)
        if current_value['value']:
            result['manager_tax_id']=current_value['value']
            result['manager_tax_id_resolved_source']=current_value['source']
        return result
    def officer_record():
        row=con.execute('SELECT * FROM authorized_officers WHERE id=?',(item.get('assigned_officer_id'),)).fetchone()
        return dict(row) if row else {}
    stamp=datetime.now(ZoneInfo('Europe/Kyiv'))
    context={'supplier':data,'manager':document_bindings.ScopedRecord(manager,manager_record),'task':item,
             'officer':document_bindings.ScopedRecord({'full_name':item.get('assigned_officer_name')},officer_record),
             'code_semantics':semantics,'contacts':contacts,
             'system':{'today':stamp.date().isoformat(),'generated_at':stamp.isoformat()}}
    resolve_binding=document_bindings.resolver(context)
    def base_resolver(field):
        key=field['key']
        value=resolve_binding(field)
        if value is None or not str(value).strip():
            if key=='supplier.email':raise ValueError('Неможливо сформувати запит: в останній заявці постачальника не зазначено електронну адресу.')
            raise ValueError('Неможливо сформувати запит: не заповнено «'+field['label']+'» ('+key+')')
        if field['value_type']=='enum' and field.get('enum_values') and value not in field['enum_values']:raise ValueError('Невідоме значення: '+key)
        return value
    return derived_fields.resolve(keys or config['required_fields'],fields,KEY,base_resolver)

def prepared(con,item,schema):
    config=template_runtime.registered(KEY)
    if not config['active']:raise ValueError('Шаблон запиту неактивний')
    fields=template_catalog.validate(template_catalog.load(),schema)
    source=template_runtime.template_path(KEY)
    report=template_runtime.validate_template(KEY,fields)
    required=set(config['required_fields'])|condition_keys(source,fields,KEY)
    context=resolve_context(con,item,fields,config,sorted(required))
    retained=retained_scalar_keys(source,fields,KEY,context)
    missing=retained-set(context)
    if missing:context.update(resolve_context(con,item,fields,config,sorted(missing)))
    metadata=document_metadata.resolve_all(con,KEY,fields,
      lambda keys: resolve_context(con,item,fields,config,keys))
    return config,fields,context,metadata

def readiness(con,item,schema):
    result={'ready':False,'errors':[],'documents':documents(con,item['id'])}
    try:prepared(con,item,schema);result['ready']=True
    except (ValueError,OSError) as exc:result['errors']=[str(exc)]
    return result

def generate(con,item,schema,storage,actor):
    """Caller holds BEGIN IMMEDIATE until commit, including task identity read."""
    config,fields,context,metadata=prepared(con,item,schema)
    source=template_runtime.template_path(KEY)
    reference=hashlib.sha256(source.read_bytes()).hexdigest()
    stamp=datetime.now(timezone.utc).isoformat();day=datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
    version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM generated_documents WHERE task_id=? AND document_type=? AND document_date=?',(item['id'],KEY,day)).fetchone()[0]
    docid=uuid.uuid4().hex
    code=re.sub(r'\D','',str(context['supplier.code']))
    filename=config['output_name_pattern'].format(supplier_code=code,date=day,version=version)
    filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',filename).strip(' .')
    storage=Path(storage);storage_name=docid+'/'+filename;target=storage/storage_name
    try:
        render(source,target,context,fields,KEY)
        if reference!=hashlib.sha256(source.read_bytes()).hexdigest():raise ValueError('Шаблон змінився під час generation. Повторіть дію.')
        con.execute('''INSERT INTO generated_documents
          (id,task_id,supplier_code,document_type,template_key,template_reference,filename,storage_name,
           created_at,created_by,generation_provider,status,document_date,version,sha256,metadata_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (docid,item['id'],str(context['supplier.code']),KEY,KEY,reference,filename,storage_name,stamp,actor,
             config['generation_provider'],'generated',day,version,hashlib.sha256(target.read_bytes()).hexdigest(),
             json.dumps(metadata,ensure_ascii=False)))
        operational_tasks._event(con,item['id'],'supplier_request_generated',actor,metadata={'document_id':docid,'filename':filename,'template_reference':reference})
    except Exception:
        target.unlink(missing_ok=True)
        raise
    row=con.execute('SELECT * FROM generated_documents WHERE id=?',(docid,)).fetchone()
    return public_document(row)

def download(con,task_id,doc_id,storage):
    row=con.execute('SELECT * FROM generated_documents WHERE id=? AND task_id=?',(doc_id,task_id)).fetchone()
    if not row:raise KeyError(doc_id)
    root=Path(storage).resolve();path=(root/row['storage_name']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise KeyError(doc_id)
    return path,row['filename']
