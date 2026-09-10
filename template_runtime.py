"""Small canonical registry adapter; legacy four templates keep their own behavior."""
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import threading
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from lxml import etree
import violation_protocol_docx as legacy
import template_catalog
from docx_conditionals import plan

ROOT=Path(__file__).parent
REPLACE_LOCK=threading.RLock()
CONFIG=ROOT/'metadata/runtime_templates.v1.json'
TEMPLATE_ROOT=(Path(os.environ['PQM_DATA_DIR'])/'templates' if os.environ.get('PQM_DATA_DIR') else ROOT/'templates')

def configurations():
    return json.loads(CONFIG.read_text(encoding='utf-8'))['templates']

def registered(key):
    config=configurations().get(key)
    if not config:raise ValueError('Шаблон не зареєстровано')
    return config

def template_path(key):
    if key in legacy.TEMPLATES:return legacy.TEMPLATES[key]
    config=registered(key)
    path=(TEMPLATE_ROOT/config['file']).resolve()
    if not path.is_relative_to(TEMPLATE_ROOT.resolve()) or path.suffix!='.docx':
        raise ValueError('Некоректний шлях зареєстрованого шаблону')
    return path

def validate_template(key, fields, path=None):
    config=registered(key);path=path or template_path(key)
    if not path.is_file():raise ValueError('Файл шаблону відсутній')
    try:
        report=template_catalog.scan_docx(path,fields,config['document_type'])
        if not report['can_activate_canonical']:
            raise ValueError('Шаблон не пройшов validation: '+json.dumps(report,ensure_ascii=False))
        missing=set(config['required_fields'])-set(report['recognized'])
        if missing:raise ValueError('У шаблоні відсутні поля: '+', '.join(sorted(missing)))
        conditions=[]
        with ZipFile(path) as archive:
            if archive.testzip():raise ValueError('Пошкоджений DOCX')
            for name in archive.namelist():
                if name.startswith('word/') and name.endswith('.xml'):
                    conditions.extend(c for c,_ in plan(etree.fromstring(archive.read(name)),fields,config['document_type'])[0])
        for field,variants in config.get('conditional_variants',{}).items():
            actual=[c.literal for c in conditions if c.key==field]
            if sorted(actual)!=sorted(variants):raise ValueError('Потрібно рівно по одному conditional variant: '+field)
        return report
    except (BadZipFile,etree.XMLSyntaxError) as exc:raise ValueError('Некоректний DOCX') from exc

def metadata(schema):
    fields=template_catalog.validate(template_catalog.load(),schema)
    result=template_catalog.templates_metadata(legacy.template_metadata(),schema,legacy.TEMPLATES)
    for key,c in configurations().items():
        path=template_path(key);exists=path.is_file();validation=None
        if exists:
            try:validation=validate_template(key,fields,path)
            except ValueError as exc:validation={'can_activate_canonical':False,'error':str(exc)}
        result.append({**c,'key':key,'filename':path.name,'exists':exists,'modified_at':datetime.fromtimestamp(path.stat().st_mtime).isoformat() if exists else None,
                       'template_reference':hashlib.sha256(path.read_bytes()).hexdigest() if exists else None,'validation':validation})
    return result

def replace(key, source, schema, finalize=None, diagnostics=None):
    with REPLACE_LOCK:
        return _replace(key,source,schema,finalize,diagnostics if diagnostics is not None else {})


def _replace(key, source, schema, finalize, diagnostics):
    diagnostics['failure_stage']='validation'
    if key in legacy.TEMPLATES:return legacy.replace_runtime_template(key,source)
    fields=template_catalog.validate(template_catalog.load(),schema)
    validate_template(key,fields,Path(source))
    diagnostics['validation_result']='passed'
    target=template_path(key);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and target.read_bytes()==Path(source).read_bytes():
        diagnostics['unchanged']=True
        if finalize:finalize(target)
        return target
    versions=target.parent/'_versions';versions.mkdir(exist_ok=True)
    diagnostics['failure_stage']='backup'
    backup=versions/(target.stem+'_'+uuid.uuid4().hex+'.docx') if target.exists() else None
    if backup:shutil.copy2(target,backup)
    fd,temp=tempfile.mkstemp(dir=target.parent,suffix='.docx');os.close(fd)
    replaced=False
    try:
        diagnostics['failure_stage']='atomic_replace'
        shutil.copyfile(source,temp);os.replace(temp,target);replaced=True
        if finalize:finalize(target)
    except Exception:
        if replaced:
            if backup:os.replace(backup,target)
            else:target.unlink(missing_ok=True)
        elif backup:backup.unlink(missing_ok=True)
        raise
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return target
