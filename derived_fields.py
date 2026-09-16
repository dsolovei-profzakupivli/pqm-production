"""Provider-neutral, declarative transformations. No eval, SQL or imports from metadata."""
import re
from declension import decline_name, decline_short_name, ENTITY_TYPES, normalize_document_name

CASES = ('nominative', 'genitive', 'dative', 'accusative', 'instrumental', 'locative', 'vocative')
TRANSFORMATIONS = {'declension': {'label': 'Відмінювання', 'cases': list(CASES)},
                  'conditional_prefix': {'label': 'Префікс за умовою'}}


def configured(field):
    return field.get('source_binding', {}).get('transformation_type') is not None


def configuration_errors(field, lookup):
    b = field['source_binding']; errors = []
    if b.get('source_type') != 'derived': errors.append('INVALID_DERIVED_SOURCE')
    if b.get('transformation_type') not in TRANSFORMATIONS: errors.append('UNSUPPORTED_TRANSFORMATION')
    if b.get('transformation_type')=='declension':
        if b.get('grammatical_case') not in CASES: errors.append('INVALID_GRAMMATICAL_CASE')
        entity_type_field=b.get('entity_type_field')
        if entity_type_field:
            entity_field=lookup.get(entity_type_field)
            if (not entity_field or entity_field.get('value_type')!='enum' or not entity_field['active']
                    or entity_field['deprecated'] or not set(field['available_for']).issubset(entity_field['available_for'])):
                errors.append('INVALID_ENTITY_TYPE_FIELD')
        elif b.get('entity_type') not in ENTITY_TYPES: errors.append('INVALID_ENTITY_TYPE')
    elif b.get('transformation_type')=='conditional_prefix':
        condition=lookup.get(b.get('condition_field'))
        if (not condition or condition.get('value_type')!='enum' or not condition['active'] or condition['deprecated']
                or not set(field['available_for']).issubset(condition['available_for'])):errors.append('INVALID_CONDITION_FIELD')
        elif b.get('equals') not in condition.get('enum_values',[]):errors.append('INVALID_CONDITION_LITERAL')
        if not isinstance(b.get('prefix'),str) or len(b['prefix'])>200:errors.append('INVALID_PREFIX')
    if b.get('unresolved_policy') != 'error': errors.append('UNSUPPORTED_UNRESOLVED_POLICY')
    source = lookup.get(b.get('source_field'))
    if not source: errors.append('UNKNOWN_SOURCE_FIELD')
    elif (source.get('value_type') != 'string' or not source['active'] or source['deprecated']
          or not set(field['available_for']).issubset(source['available_for'])):
        errors.append('SOURCE_TYPE_OR_AVAILABILITY')
    if field['value_type'] != 'string': errors.append('INVALID_TRANSFORM_RESULT_TYPE')
    def cycle(key,seen):
        if key in seen:return True
        node=lookup.get(key)
        return bool(node and any(cycle(dep,seen|{key}) for dep in dependencies(node)))
    if cycle(field['key'],set()):errors.append('CYCLIC_DERIVED_SOURCE')
    return errors

def dependencies(field):
    b=field['source_binding']
    return [b[k] for k in ('source_field','condition_field','entity_type_field') if b.get(k)]


def resolve(keys, fields, document_type, base_resolver):
    """Resolve dependency graph once per request; return ready canonical values."""
    lookup = {f['key']: f for f in fields}; values = {}; visiting = set()
    def get(key):
        if key in values: return values[key]
        f = lookup.get(key)
        if (not f or f.get('binding_status') != 'VALID' or not f['active']
                or f['deprecated'] or document_type not in f['available_for']):
            raise ValueError('Поле недоступне або binding пошкоджений: ' + key)
        if key in visiting: raise ValueError('Циклічна залежність: ' + key)
        visiting.add(key)
        if configured(f):
            b = f['source_binding']; original = get(b['source_field'])
            entity_type=None
            if b['transformation_type']=='conditional_prefix':
                value=(b['prefix'] if get(b['condition_field'])==b['equals'] else '')+original
            elif b['grammatical_case'] == 'nominative': value = original
            else:
                entity_type=get(b['entity_type_field']) if b.get('entity_type_field') else b['entity_type']
                if entity_type=='individual_entrepreneur':entity_type='fop'
                if entity_type=='legal_entity':original=normalize_document_name(original)
                resolver=decline_short_name if b.get('preserve_fop_abbreviation') else decline_name
                result = resolver(original, entity_type, b['grammatical_case'])
                value = result.value if result.status == 'resolved' else None
            if value is not None and (b.get('entity_type')=='legal_entity' or
                                      (b.get('entity_type_field') and entity_type=='legal_entity')):
                value=normalize_document_name(value)
            if value is None or not str(value).strip():
                raise ValueError('Не визначено «' + f['label'] + '» для «' + str(original or '')
                                 + '» (' + b.get('grammatical_case',b['transformation_type']) + '). Перевірте довідник «Відмінювання». '
                                 'Якщо цей відмінок не підтримується, генерація недоступна.')
        else: value = base_resolver(f)
        if value is None or not str(value).strip():
            raise ValueError('Не заповнено «' + f['label'] + '» (' + key + ')')
        if f['value_type'] == 'enum' and f.get('enum_values') and value not in f['enum_values']:
            raise ValueError('Невідоме значення: ' + key)
        values[key] = value; visiting.remove(key)
        return value
    for key in keys: get(key)
    return values


def make_field(payload, data):
    key = str(payload.get('key') or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]{0,63}', key) or key.split('.')[0] not in data['namespaces']:
        raise ValueError('Ключ: чинний namespace та назва латиницею, наприклад manager.full_name_genitive')
    label = str(payload.get('label') or '').strip()
    if not label or len(label) > 200: raise ValueError('Зазначте назву поля (до 200 символів)')
    docs = payload.get('available_for')
    if not isinstance(docs, list) or not docs or not all(isinstance(x, str) and x in data['document_types'] for x in docs):
        raise ValueError('Оберіть підтримувані типи документів')
    source = next((f for f in data['fields'] if f['key'] == payload.get('source_field')), None)
    if not source: raise ValueError('Оберіть базове canonical field')
    b = {'source_type': 'derived', 'source_field': source['key'],
         'transformation_type': payload.get('transformation_type'), 'grammatical_case': payload.get('grammatical_case'),
         'entity_type': payload.get('entity_type'), 'unresolved_policy': 'error',
         'dependencies': [], 'description': source['key'] + ' → declension / ' + str(payload.get('grammatical_case'))}
    if payload.get('transformation_type')=='conditional_prefix':
        for name in ('grammatical_case','entity_type'):b.pop(name)
        b.update(condition_field=payload.get('condition_field'),equals=payload.get('equals'),prefix=payload.get('prefix'),
                 description=source['key']+' → conditional prefix / '+str(payload.get('condition_field'))+' == '+str(payload.get('equals')))
    return {'key': key, 'label': label, 'group': source['group'], 'value_type': 'string', 'source_binding': b,
            'description': b['description'], 'available_for': list(dict.fromkeys(docs)), 'required_for': [],
            'default_format': None, 'example': None, 'nullable': True, 'active': True,
            'deprecated': False, 'replacement_key': None}
