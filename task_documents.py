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
from declension import decline_name, decline_short_name, normalize_document_name
from document_semantics import supplier_code_semantics
import derived_fields
import document_bindings
import document_metadata
from supplier_contacts import supplier_contacts
from supplier_identity import (current_manager_rnokpp, document_name as supplier_document_name,
                               document_short_name as supplier_document_short_name)
from docx_conditionals import render, condition_keys, retained_scalar_keys

KEY='nazk_supplier_request'  # Server-owned action mapping, never supplied by client.
AMCU_PROTOCOL_KEY='amcu_exclusion_protocol'
TERMINATION_PROTOCOL_KEY='termination_exclusion_protocol'


class DeclensionRequired(ValueError):
    def __init__(self,unresolved):
        self.unresolved=unresolved
        super().__init__('Потрібні перевірені відмінкові форми')


def officer_document_name(value):
    """Presentation-only Ім'я ПРІЗВИЩЕ; canonical identity remains unchanged."""
    parts=' '.join(str(value or '').split()).split()
    if not parts:return ''
    return ' '.join([*(part.lower().capitalize() for part in parts[:-1]),parts[-1].upper()])

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
    if item.get('document_type')==AMCU_PROTOCOL_KEY:
        item['display_filename']=amcu_business_filename(item)
    item['download_url']=f"/api/operational-tasks/{item['task_id']}/documents/{item['id']}/download"
    if item.get('document_type') in {AMCU_PROTOCOL_KEY,TERMINATION_PROTOCOL_KEY,KEY}:
        item['pdf_url']=f"/api/operational-tasks/{item['task_id']}/documents/{item['id']}/pdf"
    return item


def _amcu_protocol_number(item):
    """Recover the immutable protocol number from the stored AMCU artifact identity."""
    filename=Path(str(item.get('filename') or '')).stem
    marker='_'+str(item.get('supplier_code') or '')+'_'
    if marker in filename:
        tail=filename.split(marker,1)[1]
        version_suffix='_v'+str(item.get('version') or '')
        if version_suffix and tail.endswith(version_suffix):
            return tail[:-len(version_suffix)]
    return ''


def amcu_business_filename(item,suffix='.docx'):
    number=_amcu_protocol_number(item) or '—'
    safe_number=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',number).strip(' .') or '—'
    return f"Протокол № {safe_number} від {_display_date(item.get('document_date'))} (пп. 7 п. 40){suffix}"

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


def resolve_amcu_protocol_context(con,item,fields,keys):
    """Resolve the approved AMKU protocol contract."""
    if item.get('task_type')!='amcu_exclusion':
        raise ValueError('AMКУ protocol context доступний тільки для задачі виключення')
    code=re.sub(r'\D','',str(item.get('supplier_code') or ''))
    row=con.execute('SELECT * FROM supplier_registry_summary WHERE DIGITS(supplier_code)=?',(code,)).fetchone()
    data=dict(row) if row else {}
    data.setdefault('supplier_code',code)
    semantics=supplier_code_semantics(str(data.get('supplier_code') or code))
    name=supplier_document_name(con,code)
    data['document_name']=normalize_document_name(name) if semantics['entity_type']=='legal_entity' else name
    short_name=supplier_document_short_name(con,code)
    data['document_short_name']=(normalize_document_name(short_name)
                                 if semantics['entity_type']=='legal_entity' else short_name)
    decisions=[{'number':decision.get('decision_no') or '',
                'date':decision.get('decision_date') or '',
                'authority':decision.get('authority') or '',
                'extract_url':decision.get('extract_url') or '',
                'linked_reference':'від '+_display_date(decision.get('decision_date'))+
                                   ' № '+str(decision.get('decision_no') or '')}
               for decision in item.get('amcu_decisions') or []]
    if not decisions:raise ValueError('Не додано жодного рішення АМКУ')
    if any(not str(decision['extract_url']).strip() for decision in decisions):
        raise ValueError('Додайте посилання на витяг для всіх рішень АМКУ')
    unresolved=[]
    cases={'supplier.name_genitive':('genitive',data['document_name']),
           'supplier.name_accusative':('accusative',data['document_name']),
           'supplier.short_name_genitive':('genitive',data['document_short_name']),
           'supplier.short_name_dative':('dative',data['document_short_name']),
           'supplier.short_name_accusative':('accusative',data['document_short_name'])}
    entity_type='fop' if semantics['entity_type']=='individual_entrepreneur' else semantics['entity_type']
    for key,(grammatical_case,original) in cases.items():
        if key not in keys:continue
        result=(decline_short_name(original,entity_type,grammatical_case)
                if key.startswith('supplier.short_name_') else
                decline_name(original,entity_type,grammatical_case))
        if result.status!='resolved':
            unresolved.append({'subject_label':'Постачальник','original':original,
              'entity_type':entity_type,'grammatical_case':grammatical_case,
              'entity_identifier':code,'task_id':item.get('id'),'context_type':'amcu_exclusion'})
    if unresolved:raise DeclensionRequired(unresolved)
    task={**item,'amcu_decisions':decisions,
          'amcu_decision_basis_phrase':('на підставі рішення' if len(decisions)==1 else 'на підставі рішень'),
          'amcu_is_single_decision':'true' if len(decisions)==1 else 'false',
          'amcu_has_multiple_decisions':'true' if len(decisions)>1 else 'false'}
    def officer_record():
        officer=con.execute('SELECT * FROM authorized_officers WHERE id=?',(item.get('assigned_officer_id'),)).fetchone()
        return dict(officer) if officer else {}
    def formatted_officer_record():
        officer=officer_record()
        return {**officer,'full_name':officer_document_name(officer.get('full_name'))}
    presented_officer=officer_document_name(item.get('assigned_officer_name'))
    context={'supplier':data,'task':task,'decision':{'number':item.get('protocol_number') or '',
             'date':item.get('protocol_date') or ''},
             'officer':document_bindings.ScopedRecord(
                {'full_name':presented_officer} if presented_officer else {},formatted_officer_record),
             'code_semantics':semantics}
    resolve_binding=document_bindings.resolver(context)
    def base_resolver(field):
        value=resolve_binding(field)
        if value is None or value=='' or (isinstance(value,list) and not value):
            raise ValueError('Не заповнено «'+field['label']+'» ('+field['key']+')')
        return value
    return derived_fields.resolve(keys,fields,AMCU_PROTOCOL_KEY,base_resolver)


def _display_date(value):
    raw=str(value or '')[:10]
    try:return datetime.fromisoformat(raw).strftime('%d.%m.%Y')
    except ValueError:return raw


def _declension_item(original,entity_type,grammatical_case,subject_label,identifier='',task_id='',context_type=''):
    result=decline_name(original,entity_type,grammatical_case)
    return {'subject_label':subject_label,'original':original,'entity_type':entity_type,
            'grammatical_case':grammatical_case,'entity_identifier':identifier,
            'task_id':task_id,'context_type':context_type,'status':result.status,
            'source':result.source,'resolved_value':result.value}


def _short_declension_item(original,entity_type,grammatical_case,subject_label,identifier='',task_id='',context_type=''):
    result=decline_short_name(original,entity_type,grammatical_case)
    return {'subject_label':subject_label,'original':original,'entity_type':entity_type,
            'grammatical_case':grammatical_case,'entity_identifier':identifier,
            'task_id':task_id,'context_type':context_type,'status':result.status,
            'source':result.source,'resolved_value':result.value}


def amcu_declension_review(con,item):
    """All AMKU forms remain reviewable even when automatic resolution succeeded."""
    code=re.sub(r'\D','',str(item.get('supplier_code') or ''))
    semantics=supplier_code_semantics(code)
    entity_type='fop' if semantics['entity_type']=='individual_entrepreneur' else semantics['entity_type']
    full=supplier_document_name(con,code)
    short=supplier_document_short_name(con,code)
    return [_declension_item(full,entity_type,'genitive','Постачальник',code,item.get('id'),'amcu_exclusion'),
            _declension_item(full,entity_type,'accusative','Постачальник',code,item.get('id'),'amcu_exclusion'),
            _short_declension_item(short,entity_type,'genitive','Скорочена назва постачальника',code,item.get('id'),'amcu_exclusion'),
            _short_declension_item(short,entity_type,'dative','Скорочена назва постачальника',code,item.get('id'),'amcu_exclusion'),
            _short_declension_item(short,entity_type,'accusative','Скорочена назва постачальника',code,item.get('id'),'amcu_exclusion')]


def _termination_boundary(con,item):
    """Canonical payload/gate only. The supplied FOP wording is not silently activated."""
    source=item.get('source_context') or {}; supplier=source.get('supplier') or {}
    code=re.sub(r'\D','',str(supplier.get('code') or item.get('supplier_code') or ''))
    entity_type='fop' if supplier.get('type')=='individual_entrepreneur' else 'legal_entity'
    full=str(supplier.get('full_name') or supplier.get('name') or '')
    short=str(supplier.get('short_name') or full)
    declensions=[_declension_item(full,entity_type,'genitive','Постачальник',code,item.get('id'),'termination_exclusion'),
      _declension_item(full,entity_type,'accusative','Постачальник',code,item.get('id'),'termination_exclusion'),
      _short_declension_item(short,entity_type,'genitive','Скорочена назва постачальника',code,item.get('id'),'termination_exclusion')]
    unresolved=[entry for entry in declensions[:2] if entry['status']!='resolved']
    termination=source.get('termination') or {}
    termination_reference=' · '.join(str(termination.get(key) or '').strip() for key in
      ('details','record_date','record_number') if str(termination.get(key) or '').strip())
    payload={'decision.number':item.get('protocol_number') or '',
      'decision.date':item.get('protocol_date') or '',
      'supplier.code':code,'supplier.code_label':supplier.get('code_label') or '',
      'supplier.name':full,'supplier.short_name':short,
      'supplier.name_genitive':declensions[0].get('resolved_value') or '',
      'supplier.name_accusative':declensions[1].get('resolved_value') or '',
      'supplier.short_name_genitive':declensions[2].get('resolved_value') or '',
      'termination.details':termination.get('details') or '',
      'termination.record_date':termination.get('record_date') or '',
      'termination.record_number':termination.get('record_number') or '',
      'termination.reference':termination_reference,
      'uo.full_name':officer_document_name(item.get('assigned_officer_name'))}
    errors=[]
    if supplier.get('type')!='individual_entrepreneur':
        errors.append('Для юридичної особи потрібен окремо погоджений юридичний текст шаблону')
    if unresolved:errors.insert(0,'Потрібні перевірені відмінкові форми')
    return {'ready':False,'errors':errors,'declensions':declensions,'unresolved':unresolved,
      'documents':[doc for doc in documents(con,item['id']) if doc['document_type']==TERMINATION_PROTOCOL_KEY],
      'canonical_payload':payload,'template_boundary':('fop_candidate' if supplier.get('type')=='individual_entrepreneur' else 'legal_entity_blocked')}


def prepared_termination(con,item,schema):
    boundary=_termination_boundary(con,item)
    if boundary['template_boundary']!='fop_candidate':raise ValueError(boundary['errors'][-1])
    if item.get('task_type')!='termination_exclusion':raise ValueError('Документ доступний тільки для задачі припинення')
    if item.get('status') in operational_tasks.TERMINAL or item.get('status')=='awaiting_sync':
        raise ValueError('Формування для розглянутої/завершеної задачі недоступне')
    targets=item.get('target_qualifications') or []
    if not targets or any(x.get('decision') not in {'exclude','keep'} for x in targets):
        raise ValueError('Оберіть рішення для кожної зафіксованої кваліфікації')
    if not any(x.get('decision')=='exclude' and x.get('effective_active') for x in targets):
        raise ValueError('Відсутні активні кваліфікації з рішенням про виключення')
    if boundary['unresolved']:raise DeclensionRequired(boundary['unresolved'])
    config=template_runtime.registered(TERMINATION_PROTOCOL_KEY)
    if not config['active']:raise ValueError('Шаблон припинення неактивний')
    fields=template_catalog.validate(template_catalog.load(),schema)
    report=template_runtime.validate_template(TERMINATION_PROTOCOL_KEY,fields)
    context=boundary['canonical_payload']
    for key in set(config['required_fields'])|set(report['recognized']):
        if not str(context.get(key) or '').strip():raise ValueError('Не заповнено поле: '+key)
    from datetime import date
    context['decision.date']=date.fromisoformat(str(context['decision.date'])[:10]).isoformat()
    metadata=document_metadata.resolve_all(con,TERMINATION_PROTOCOL_KEY,fields,
                                          lambda keys:{key:context.get(key) for key in keys})
    return config,fields,context,metadata


def termination_readiness(con,item,schema=None):
    result=_termination_boundary(con,item)
    try:prepared_termination(con,item,schema);result['ready']=True;result['errors']=[]
    except DeclensionRequired as exc:result['errors']=[str(exc)];result['unresolved']=exc.unresolved
    except (ValueError,OSError,TypeError) as exc:result['errors']=[str(exc)]
    return result


def nazk_declension_review(con,item):
    code=re.sub(r'\D','',str(item.get('supplier_code') or ''))
    semantics=supplier_code_semantics(code)
    entity_type='fop' if semantics['entity_type']=='individual_entrepreneur' else semantics['entity_type']
    manager=item.get('current_manager') or {}
    return [_declension_item(supplier_document_name(con,code),entity_type,'genitive','Постачальник',code,item.get('id'),'nazk_check'),
            _declension_item(manager.get('manager_name') or '','person','genitive','Керівник',
                             manager.get('manager_tax_id') or '',item.get('id'),'nazk_check')]


def prepared_amcu(con,item,schema):
    try:config=template_runtime.registered(AMCU_PROTOCOL_KEY)
    except ValueError as exc:raise ValueError('Шаблон протоколу АМКУ ще не зареєстрований') from exc
    if not config['active']:raise ValueError('Шаблон протоколу АМКУ неактивний')
    if item.get('task_type')!='amcu_exclusion':raise ValueError('Документ доступний тільки для задачі АМКУ')
    if item.get('status') in operational_tasks.TERMINAL:raise ValueError('Для завершеної задачі формування недоступне')
    if not item.get('effective_active_count'):raise ValueError('Відсутні активні кваліфікації постачальника')
    fields=template_catalog.validate(template_catalog.load(),schema)
    source=template_runtime.template_path(AMCU_PROTOCOL_KEY)
    report=template_runtime.validate_template(AMCU_PROTOCOL_KEY,fields)
    # These values are also generation invariants (document date/version scope
    # and safe output naming), even when a future canonical template omits one
    # of them from visible text.
    required={'decision.number','decision.date','supplier.code'}
    required.update(config.get('required_fields') or [])
    required.update(condition_keys(source,fields,AMCU_PROTOCOL_KEY))
    for key in report.get('recognized') or []:
        required.add('amcu.decisions[]' if key.startswith('amcu.decisions[].') else key)
    context=resolve_amcu_protocol_context(con,item,fields,sorted(required))
    metadata=document_metadata.resolve_all(con,AMCU_PROTOCOL_KEY,fields,
      lambda keys:resolve_amcu_protocol_context(con,item,fields,keys))
    return config,fields,context,metadata


def amcu_readiness(con,item,schema):
    declensions=amcu_declension_review(con,item)
    result={'ready':False,'errors':[],'declensions':declensions,
            'unresolved':[entry for entry in declensions if entry['status']!='resolved'],
            'documents':[doc for doc in documents(con,item['id']) if doc['document_type']==AMCU_PROTOCOL_KEY]}
    try:prepared_amcu(con,item,schema);result['ready']=True
    except DeclensionRequired as exc:
        result['errors']=[str(exc)];result['unresolved']=exc.unresolved
    except (ValueError,OSError) as exc:result['errors']=[str(exc)]
    return result


def generate_amcu(con,item,schema,storage,actor,_document_type=AMCU_PROTOCOL_KEY):
    """Generate only the artifact/version; never completes the task or excludes a supplier."""
    key=_document_type
    config,fields,context,metadata=(prepared_termination if key==TERMINATION_PROTOCOL_KEY else prepared_amcu)(con,item,schema)
    source=template_runtime.template_path(key)
    reference=hashlib.sha256(source.read_bytes()).hexdigest();stamp=datetime.now(timezone.utc).isoformat()
    document_date=str(context['decision.date'])[:10]
    version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM generated_documents WHERE task_id=? AND document_type=? AND document_date=?',
      (item['id'],key,document_date)).fetchone()[0]
    docid=uuid.uuid4().hex;code=re.sub(r'\D','',str(context['supplier.code']))
    filename=config['output_name_pattern'].format(supplier_code=code,date=document_date,version=version,
      protocol_number=str(context['decision.number']))
    filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',filename).strip(' .')
    storage=Path(storage);storage_name=docid+'/'+filename;target=storage/storage_name
    try:
        render(source,target,context,fields,key,aliases=config.get('placeholder_aliases'))
        if reference!=hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('Шаблон змінився під час generation. Повторіть дію.')
        con.execute('''INSERT INTO generated_documents
          (id,task_id,supplier_code,document_type,template_key,template_reference,filename,storage_name,
           created_at,created_by,generation_provider,status,document_date,version,sha256,metadata_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (docid,item['id'],code,key,key,reference,filename,storage_name,stamp,actor,
           config['generation_provider'],'generated',document_date,version,hashlib.sha256(target.read_bytes()).hexdigest(),
           json.dumps(metadata,ensure_ascii=False)))
        operational_tasks._event(con,item['id'],key+'_generated',actor,
          metadata={'document_id':docid,'filename':filename,'template_reference':reference})
    except Exception:
        target.unlink(missing_ok=True);raise
    return public_document(con.execute('SELECT * FROM generated_documents WHERE id=?',(docid,)).fetchone())


def generate_termination(con,item,schema,storage,actor):
    return generate_amcu(con,item,schema,storage,actor,_document_type=TERMINATION_PROTOCOL_KEY)

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
    declensions=nazk_declension_review(con,item)
    result={'ready':False,'errors':[],'declensions':declensions,
            'unresolved':[entry for entry in declensions if entry['status']!='resolved'],
            'documents':documents(con,item['id'])}
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
    filename=(amcu_business_filename(dict(row))
              if row['document_type']==AMCU_PROTOCOL_KEY else row['filename'])
    return path,filename


def amcu_pdf_source(con,task_id,doc_id,storage):
    row=con.execute('SELECT * FROM generated_documents WHERE id=? AND task_id=?',(doc_id,task_id)).fetchone()
    if not row or row['document_type'] not in {AMCU_PROTOCOL_KEY,TERMINATION_PROTOCOL_KEY,KEY}:raise KeyError(doc_id)
    source,filename=download(con,task_id,doc_id,storage)
    return source,Path(filename).with_suffix('.pdf').name
