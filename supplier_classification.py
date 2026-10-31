"""Read-only operational supplier classification; identifiers stay literal text.

Subject-nature rules agreed 2026-10-30 (supersede the identifier-length matrix).
Document-only presentation semantics are not
changed. No names, schemes or Google tab positions establish a country.
"""
import json
from pathlib import Path
import re
import threading

VERSION = 'subject-nature-20261030-v2'
ENTITY_TYPES = frozenset({'legal_entity','individual_entrepreneur','foreign_legal_entity','unknown'})
_COUNTRIES = json.loads(Path(__file__).with_name('supplier_country_catalog.json').read_text(encoding='utf-8'))['countries']
_ALIASES = {}
for _code,_names in _COUNTRIES.items():
    for _name in [_code,*_names.values()]:
        if isinstance(_name,str):_ALIASES[' '.join(_name.casefold().split())]=_code
_ALIASES.update({'украина':'UA','ukr':'UA'})
_FORMS={'legal_entity':'legal_entity','legalentity':'legal_entity','юо':'legal_entity',
        'юридична особа':'legal_entity','individual_entrepreneur':'individual_entrepreneur',
        'privateentrepreneur':'individual_entrepreneur','фоп':'individual_entrepreneur',
        'фізична особа-підприємець':'individual_entrepreneur',
        'joint_activity':'legal_entity','спільна діяльність':'legal_entity',
        'branch':'legal_entity','representative_office':'legal_entity',
        'філія':'legal_entity','представництво':'legal_entity','other_organization':'legal_entity'}
_FOP_NAME=re.compile(r'^(?:ФОП(?=\s|[«"\'])|ФІЗИЧНА\s+ОСОБА[\s-]*ПІДПРИЄМЕЦЬ(?=\s|[«"\']|$))',re.I)
_OTHER_NAME=re.compile(r'^(?:(?:ТОВ|ТЗОВ|ПРАТ|ПАТ|АТ|ДП|КП|КНП)(?=\s|[«"\'])|ТОВАРИСТВО\b|(?:ПРИВАТНЕ|ДЕРЖАВНЕ|КОМУНАЛЬНЕ|КАЗЕННЕ|КОЛЕКТИВНЕ)\s+(?:ПІДПРИЄМСТВО|АКЦІОНЕРНЕ|НЕКОМЕРЦІЙНЕ)|ПУБЛІЧНЕ\s+АКЦІОНЕРНЕ|ФІЛІЯ\b|ПРЕДСТАВНИЦТВО\b|ДОГОВІР\s+ПРО\s+СПІЛЬНУ\s+ДІЯЛЬНІСТЬ\b|СПІЛЬНА\s+ДІЯЛЬНІСТЬ\b)',re.I)
_LOCK=threading.Lock()
_CACHE={'revision':None,'index':None}

def classify(identifier, organization=None, *, source=''):
    org=organization if isinstance(organization,dict) else {}
    result={'supplier_code':identifier,'entity_type':'unknown','classification_status':'needs_review',
            'classification_reason':'country_missing_or_unknown','registration_country':'',
            'classification_source':source,'classification_version':VERSION,'target_sheet':None,
            'append_allowed':False,'subject_nature':'unknown','subject_nature_sources':[]}
    def conflict(reason):
        result.update(classification_status='conflict',classification_reason=reason);return result
    if not isinstance(identifier,str) or not identifier.strip():
        result['classification_reason']='identifier_not_literal_text';return result
    result['identifier_format_hint']=('eight_digits' if re.fullmatch(r'[0-9]{8}',identifier)
      else 'nine_digits' if re.fullmatch(r'[0-9]{9}',identifier)
      else 'ten_digits' if re.fullmatch(r'[0-9]{10}',identifier) else 'passport_or_other')
    primary=(org.get('identifier') or {}).get('id') if isinstance(org.get('identifier'),dict) else None
    if primary is not None and (not isinstance(primary,str) or primary!=identifier):
        return conflict('source_identifier_conflict')
    address=org.get('address') if isinstance(org.get('address'),dict) else {}
    tokens=[]
    for key in ['countryCode','countryName','countryName_en','countryName_uk','countryName_ru']:
        v=address.get(key)
        if isinstance(v,dict):tokens.extend(v.values())
        else:tokens.append(v)
    countries={_ALIASES[' '.join(t.casefold().split())] for t in tokens
               if isinstance(t,str) and ' '.join(t.casefold().split()) in _ALIASES}
    if len(countries)>1:return conflict('country_evidence_conflict')
    if any(t not in (None,'') and (not isinstance(t,str) or ' '.join(t.casefold().split()) not in _ALIASES) for t in tokens):
        result['classification_reason']='country_evidence_unrecognized';return result
    if not countries:return result
    country=next(iter(countries));result['registration_country']=country
    evidence=[]
    for key in ['legalForm','legalFormCode','organizationType','typeOfEntity']:
        raw=org.get(key)
        if raw in (None,''):continue
        form=_FORMS.get(' '.join(raw.casefold().split())) if isinstance(raw,str) else None
        if not form:return conflict('unrecognized_explicit_legal_form')
        evidence.append((form,'primary.'+key))
    primary_id=org.get('identifier') if isinstance(org.get('identifier'),dict) else {}
    for key,name in [('identifier.legalName',primary_id.get('legalName')),('name',org.get('name'))]:
        if not isinstance(name,str):continue
        text=' '.join(name.strip(' «»"\'').split())
        if _FOP_NAME.search(text):evidence.append(('individual_entrepreneur','primary.'+key))
        if _OTHER_NAME.search(text):evidence.append(('legal_entity','primary.'+key))
    kinds={kind for kind,_ in evidence}
    result['subject_nature_sources']=[src for _,src in evidence]
    if len(kinds)>1:return conflict('subject_nature_evidence_conflict')
    if kinds:result['subject_nature']='fop' if next(iter(kinds))=='individual_entrepreneur' else 'not_fop'
    if country!='UA':
        # Existing transport enum retained; it does not assert legal form.
        result.update(entity_type='foreign_legal_entity',classification_status='nonresident',
                      classification_reason='nonresident_append_blocked');return result
    if not kinds:
        result['classification_reason']='subject_nature_not_established';return result
    established=next(iter(kinds))
    result.update(entity_type=established,classification_status='resolved',classification_reason='established_subject_nature',
                  target_sheet='ЮО' if established=='legal_entity' else 'ФОП',append_allowed=True)
    return result

def _revision(con):
    main=next((r[2] for r in con.execute('PRAGMA database_list') if r[1]=='main'),'')
    if not main:return None
    def stamp(p):
        try:s=p.stat();return (s.st_ino,s.st_size,s.st_mtime_ns)
        except FileNotFoundError:return None
    p=Path(main)
    return (str(p.resolve()),stamp(p),stamp(Path(str(p)+'-wal')),VERSION)

def build_index(con):
    """One scalar latest primary record per exact identifier, no DB writes.

    Country source is Prozorro supplier address.countryName/countryCode. No
    independent registration-country field is present in the standard payload.
    Unsupported explicit form fields block rather than silently guessing.
    """
    before=_revision(con)
    with _LOCK:
        if before is not None and _CACHE['revision']==before:return {k:dict(v) for k,v in _CACHE['index'].items()}
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    index={}
    if 'submissions' in tables:
        columns={r[1] for r in con.execute('PRAGMA table_info(submissions)')}
        date_expr="COALESCE(date_published,'') DESC," if 'date_published' in columns else ''
        if {'supplier_code','id','raw_json'}<=columns:
            sql=f'''WITH ranked AS (SELECT supplier_code,id,
              CASE WHEN json_valid(raw_json) THEN raw_json ELSE '{{}}' END payload,
              ROW_NUMBER() OVER(PARTITION BY supplier_code ORDER BY {date_expr} id DESC) rn
              FROM submissions WHERE COALESCE(supplier_code,'')<>'')
              SELECT supplier_code,id,json_extract(payload,'$.tenderers[0].identifier.id'),
              json_extract(payload,'$.tenderers[0].address.countryName'),
              json_extract(payload,'$.tenderers[0].address.countryName_en'),
              json_extract(payload,'$.tenderers[0].address.countryName_uk'),
              json_extract(payload,'$.tenderers[0].address.countryName_ru'),
              json_extract(payload,'$.tenderers[0].address.countryCode'),
              json_extract(payload,'$.tenderers[0].legalForm'),
              json_extract(payload,'$.tenderers[0].legalFormCode'),
              json_extract(payload,'$.tenderers[0].organizationType'),
              json_extract(payload,'$.tenderers[0].typeOfEntity'),
              json_extract(payload,'$.tenderers[0].identifier.legalName'),
              json_extract(payload,'$.tenderers[0].name') FROM ranked WHERE rn=1'''
            for row in con.execute(sql):
                code,sid,raw_id,*fields=tuple(row)
                address=dict(zip(['countryName','countryName_en','countryName_uk','countryName_ru','countryCode'],fields[:5]))
                # Multilingual countryName may be encoded as JSON by SQLite.
                if isinstance(address['countryName'],str) and address['countryName'].startswith('{'):
                    try:address['countryName']=json.loads(address['countryName'])
                    except ValueError:pass
                org={'identifier':{'id':raw_id,'legalName':fields[9]},'address':address,'name':fields[10],
                     **dict(zip(['legalForm','legalFormCode','organizationType','typeOfEntity'],fields[5:9]))}
                index[code]=classify(code,org,source=f'submissions/{sid}/tenderers[0]')
    # Diagnostic only. Never merge two source identities through whitespace.
    aliases={}
    for code in index:
        if isinstance(code,str):aliases.setdefault(re.sub(r'\s','',code),[]).append(code)
    for variants in aliases.values():
        if len(variants)>1:
            for code in variants:index[code].update(entity_type='unknown',classification_status='conflict',
                classification_reason='identifier_text_conflict',target_sheet=None,append_allowed=False)
    if before is not None and _revision(con)==before:
        with _LOCK:_CACHE.update(revision=before,index=index)
    return {k:dict(v) for k,v in index.items()}

def resolve(index,identifier):
    return dict(index.get(identifier) or classify(identifier))

def public_fields(result):
    labels={
      'established_subject_nature':'Тип підтверджено первинними даними або погодженим розглядом',
      'subject_nature_not_established':'Природу суб’єкта не встановлено; формат коду недостатній',
      'country_missing_or_unknown':'Країна постачальника не визначена у Prozorro',
      'country_evidence_unrecognized':'Країну в первинних даних не вдалося розпізнати',
      'country_evidence_conflict':'Суперечливі дані країни постачальника',
      'subject_nature_evidence_conflict':'Суперечливі дані про природу суб’єкта',
      'source_identifier_conflict':'Ідентифікатор не збігається з первинними даними',
      'identifier_text_conflict':'Відмінні текстові ідентифікатори не можна автоматично об’єднати',
      'nonresident_append_blocked':'Нерезидент: автоматичне додавання поки вимкнено',
      'unrecognized_explicit_legal_form':'Юридична форма потребує перевірки'}
    return {**{k:v for k,v in result.items() if k!='supplier_code'},
            'classification_reason_label':labels.get(result['classification_reason'],'Потрібна перевірка типу постачальника')}
