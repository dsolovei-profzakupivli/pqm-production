"""Metadata paths over explicitly scoped canonical records; no SQL/eval/imports from metadata."""
import json
from pathlib import Path

CONFIG=Path(__file__).parent/'metadata/document_sources.v1.json'

class ScopedRecord(dict):
    """Hydrate an already identity-scoped record once if a new Catalog column is requested."""
    def __init__(self,record,loader):
        super().__init__(record or {});self.loader=loader
    def get(self,key,default=None):
        if key not in self and self.loader:
            loader,self.loader=self.loader,None
            self.update(loader() or {})
        return super().get(key,default)

def binding_errors(binding):
    config=json.loads(CONFIG.read_text(encoding='utf-8'))
    kind=binding.get('source_type')
    if kind=='schema_field':
        if binding.get('schema_field','').rpartition('.')[0] not in config['schema_scopes']:
            return ['MISSING_CANONICAL_SCOPE']
    elif kind=='derived' and not binding.get('transformation_type'):
        path=binding.get('context_path') or config['semantic_sources'].get(binding.get('resolver'))
        if not path:return ['MISSING_RUNTIME_BINDING']
        if (not isinstance(path,str) or path.split('.')[0] not in {'supplier','manager','officer','task','system','code_semantics','contacts','report','customer','decision'}
                or any(not p.isidentifier() or p.startswith('_') for p in path.split('.'))):return ['INVALID_CONTEXT_PATH']
        if binding.get('aggregate') not in (None,'count'):return ['INVALID_AGGREGATE']
    return []

def path_value(root,path):
    value=root
    for part in path.split('.'):
        if not part or part.startswith('_'):raise ValueError('Invalid document source path')
        if isinstance(value,list):
            if len(value)!=1:raise ValueError('Неоднозначне джерело документа: '+path)
            value=value[0]
        if not isinstance(value,dict):return None
        value=value.get(part)
    return value

def resolver(context):
    config=json.loads(CONFIG.read_text(encoding='utf-8'))
    def resolve(field):
        b=field['source_binding']
        if b['source_type']=='schema_field':
            table,sep,column=b['schema_field'].rpartition('.')
            scope=config['schema_scopes'].get(table)
            if not sep or not scope:raise ValueError('Не визначено canonical scope: '+table)
            return path_value(context,scope+'.'+column)
        if b['source_type']=='derived':
            path=b.get('context_path') or config['semantic_sources'].get(b.get('resolver'))
            if not path:raise ValueError('Відсутній executable binding: '+field['key'])
            value=path_value(context,path)
            if b.get('aggregate')=='count':return len(value or [])
            return value
        raise ValueError('UNBOUND: '+field['key'])
    return resolve
