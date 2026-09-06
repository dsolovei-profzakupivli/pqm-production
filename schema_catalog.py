"""Read-only structure + descriptive metadata. Never imports the runtime server."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

REGISTRY = Path(__file__).parent / 'metadata' / 'data_schema.v1.json'


def inspect_database(path):
    # No init_db, record reads, index scans, defaults or stored JSON values.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as con:
        con.execute('PRAGMA query_only=ON')
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [{'key': r[1], 'type': r[2], 'required': bool(r[3]), 'primary_key': bool(r[5]),
                        'primary_key_position': r[5]} for r in con.execute('PRAGMA table_info(' + quoted + ')')]
            links = [{'key': r[3], 'target_table': r[2], 'target_key': r[4], 'on_delete': r[6]}
                     for r in con.execute('PRAGMA foreign_key_list(' + quoted + ')')]
            tables.append({'name': name, 'columns': columns, 'links': links})
        return tables


def catalog(pqm_path, bids_path=None, registry_path=REGISTRY):
    registry = json.loads(Path(registry_path).read_text(encoding='utf-8'))
    entries = registry['fields']
    result = {'version': registry['version'], 'groups': registry['groups'], 'modules': registry['modules'],
              'items': [], 'relationships': [], 'flows': registry['flows'], 'warnings': [],
              'stores': [], 'missing_metadata_fields': [], 'source': 'Read-only physical introspection + versioned descriptive registry'}
    present = set()
    for database, path in [('pqm', pqm_path), ('bids', bids_path)]:
        if path is None:
            result['stores'].append({'id': database, 'available': False, 'tables': 0, 'fields': 0})
            result['warnings'].append('ProzorroBids не підключено: фізична структура цього сховища не перевірена.')
            continue
        try:
            tables = inspect_database(path)
        except (OSError, sqlite3.Error):
            if database == 'pqm':
                raise RuntimeError('Не вдалося прочитати структуру PQM. Предметні дані не змінено.') from None
            result['stores'].append({'id': database, 'available': False, 'tables': 0, 'fields': 0})
            result['warnings'].append('Структура ProzorroBids зараз недоступна; це не означає відсутність таблиць.')
            continue
        result['stores'].append({'id': database, 'available': True, 'tables': len(tables),
                                 'fields': sum(len(t['columns']) for t in tables)})
        for table in tables:
            for column in table['columns']:
                identity = '.'.join([database, table['name'], column['key']])
                present.add(identity)
                metadata = entries.get(identity)
                if metadata is None:
                    metadata = {'label': column['key'], 'description': 'Опис не погоджено. Нове або неописане фізичне поле.',
                                'groups': [registry['groups'][-1]], 'source': 'Потребує опису/погодження', 'modules': [],
                                'editing': 'unknown', 'editing_note': 'Не встановлено; це не дозвіл редагування',
                                'status': 'unapproved', 'technical': False, 'evidence': []}
                item = {**metadata, **column, 'id': identity, 'kind': 'physical', 'database': database,
                        'table': table['name'], 'structure_source': 'SQLite PRAGMA table_info',
                        'foreign_keys': [link for link in table['links'] if link['key'] == column['key']],
                        'source_field': table['name'] + '.' + column['key']}
                result['items'].append(item)
            for link in table['links']:
                result['relationships'].append({'kind': 'fk', 'from': database + '.' + table['name'] + '.' + link['key'],
                    'to': database + '.' + link['target_table'] + '.' + str(link['target_key']),
                    'note': 'Declared FK · ON DELETE ' + link['on_delete']})
    available = {s['id'] for s in result['stores'] if s['available']}
    for identity, metadata in entries.items():
        if metadata['kind'] == 'physical':
            if metadata['database'] in available and identity not in present:
                result['missing_metadata_fields'].append(identity)
            continue
        storage = '.'.join([metadata['database'], metadata['table'], metadata['key']])
        if metadata['kind'] == 'json' and storage not in present:
            continue
        result['items'].append({**metadata, 'id': identity, 'type': 'JSON path' if metadata['kind'] == 'json' else 'derived',
                                'structure_source': 'Semantic registry; не окрема колонка SQLite'})
    result['relationships'].extend({**link, 'available': link['from'] in present and link['to'] in present}
                                   for link in registry['logical_links'])
    return result
