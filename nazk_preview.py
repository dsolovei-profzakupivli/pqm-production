"""Read-only supplier-level NAZK preview. No migrations, reconciliation or writes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time

import nazk_workflow as canonical
import supplier_activity

REASONS = {
    'eligible_new_cycle': 'Непокритий ризик; відкритої перевірки або задачі немає',
    'waiting_response_existing_cycle': 'Відповідь очікується — новий цикл не потрібний',
    'refuted_current_risk_covered': 'Спростовано; поточні записи НАЗК покрито',
    'refuted_requires_new_basis_review': 'Спростовано; можливу нову підставу слід розглянути окремо',
    'existing_work': 'Відкрита перевірка або задача вже існує',
    'open_check_without_task': 'Перевірка є, операційної задачі немає',
    'completed_current_risk_covered': 'Завершена перевірка покриває поточний ризик',
    'no_active_qualifications': 'Немає активних кваліфікацій',
    'activity_projection_conflict': 'Поточна активність не збігається зі збереженим зведенням',
    'current_manager_missing': 'Немає поточного керівника',
    'current_registry_match_missing': 'Немає чинного збігу НАЗК',
    'same_cycle_not_current': 'Цей цикл уже позначено неактуальним',
    'other_state_requires_separate_review': 'Інший стан — потрібний окремий розгляд',
    'no_linked_active_applications': 'Активні кваліфікації є, пов’язаних активних заявок немає',
    'historical_task_key_conflict': 'Конфлікт ключа історичної задачі',
    'canonical_state_does_not_allow_new_cycle': 'Чинні canonical-правила не дозволяють новий цикл',
}
STATES = {'needs_supplier_review': 'Потребує перевірки', 'needs_check': 'Перевірка за заявкою',
          'waiting_response': 'Очікується відповідь', 'on_request': 'На запит',
          'refuted': 'Спростовано', 'confirmed': 'Підтверджено', 'inactive': 'Неактуально',
          'not_required': 'Немає збігу'}
GROUPS = {'candidate', 'existing', 'completed', 'inactive', 'blocked', 'excluded'}
TERMINAL = {'completed', 'cancelled'}


def query_options(params):
    allowed = {'search', 'state', 'reason', 'group', 'scope', 'page', 'size'}
    if set(params) - allowed or any(len(v) != 1 for v in params.values()):
        raise ValueError('Непідтримувані параметри попереднього перегляду')
    options = {key: values[0] for key, values in params.items()}
    options.setdefault('scope', 'active')
    if options['scope'] not in {'active', 'all', 'inactive'}:
        raise ValueError('Невідомий фільтр активності')
    for key, choices in [('state', STATES), ('reason', REASONS), ('group', GROUPS)]:
        if options.get(key) and options[key] not in choices:
            raise ValueError('Невідомий фільтр попереднього перегляду')
    if len(options.get('search', '')) > 160:
        raise ValueError('Пошуковий запит задовгий')
    try:
        options['page'] = int(options.get('page', 1))
        options['size'] = int(options.get('size', 100))
    except (TypeError, ValueError):
        raise ValueError('Некоректна сторінка') from None
    if options['page'] < 1 or not 10 <= options['size'] <= 200:
        raise ValueError('Некоректний розмір або номер сторінки')
    return options


@contextmanager
def read_connection(db_path, *, audit=None):
    uri = Path(db_path).resolve(strict=True).as_uri() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        con.create_function('NORMALIZE_NAME', 1, canonical.normalize_name, deterministic=True)
        con.create_function('DIGITS', 1, lambda value: re.sub(r'\D', '', str(value or '')), deterministic=True)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                   sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_RECURSIVE}
        def authorize(action, arg1, arg2, db, trigger):
            if audit is not None:
                audit.append(action)
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        con.set_authorizer(authorize)
        deadline = time.monotonic() + 15
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 2000)
        con.execute('BEGIN')
        yield con
    finally:
        con.close()


def classify(row):
    """Conservative preview policy over existing canonical read helpers."""
    active, stored = row['active_count'], row['stored_active_count']
    manager, matches = row['manager'], row['matches']
    checks = sorted([c for c in row['checks'] if manager and (
        c.get('manager_id') == manager['id'] or (c.get('manager_id') is None and
        canonical.normalize_name(c['manager_name']) == canonical.normalize_name(manager['manager_name'])))],
        key=lambda c: (c.get('completed_at') or c.get('started_at') or c.get('created_at') or '', c['id']), reverse=True)
    opened = [c for c in checks if c['workflow_status'] in canonical.OPEN_WORKFLOW_STATUSES]
    latest = checks[0] if checks else {}
    state = canonical.get_supplier_nazk_presentation_state(
        row['application_state'], opened[0]['workflow_status'] if opened else
        ('not_current' if latest.get('workflow_status') == 'not_current' else ''),
        registry_match=bool(matches), active_qualification=active > 0,
        legacy_result=latest.get('result') if latest.get('workflow_status') == 'completed' else row['legacy_result'])
    covering = canonical.find_covering_factual_check(checks, matches)
    decision = canonical._supplier_state_from_prefetched(stored or 0, manager, matches, checks)
    tasks = row['tasks']
    open_tasks = [t for t in tasks if t['status'] not in TERMINAL]
    keys = {f"nazk_check:{row['code']}:{manager['id']}:{fact['source_id']}" for fact in matches} if manager else set()
    conflict = any(t['status'] in TERMINAL and t['task_key'] in keys for t in tasks)
    group, reason = 'candidate', 'eligible_new_cycle'
    if active <= 0:
        group, reason = 'inactive', 'no_active_qualifications'
    elif stored is None or stored != active:
        group, reason = 'blocked', 'activity_projection_conflict'
    elif not manager:
        group, reason = 'blocked', 'current_manager_missing'
    elif not matches:
        group, reason = 'excluded', 'current_registry_match_missing'
    elif state == 'waiting_response':
        group, reason = 'existing', 'waiting_response_existing_cycle'
    elif state == 'refuted':
        group, reason = 'completed', 'refuted_current_risk_covered' if covering else 'refuted_requires_new_basis_review'
    elif opened or open_tasks:
        group, reason = 'existing', 'open_check_without_task' if opened and not open_tasks else 'existing_work'
    elif covering:
        group, reason = 'completed', 'completed_current_risk_covered'
    elif latest.get('workflow_status') == 'not_current' and decision.get('action') is None:
        group, reason = 'excluded', 'same_cycle_not_current'
    elif state != 'needs_supplier_review':
        group, reason = 'completed' if latest.get('workflow_status') == 'completed' else 'excluded', 'other_state_requires_separate_review'
    elif row['linked_active_applications'] <= 0:
        group, reason = 'blocked', 'no_linked_active_applications'
    elif conflict:
        group, reason = 'blocked', 'historical_task_key_conflict'
    elif decision.get('action') != 'create_needs_review':
        group, reason = 'blocked', 'canonical_state_does_not_allow_new_cycle'
    selected = opened[0] if opened else latest
    return {'code': row['code'], 'name': row['name'], 'active_count': active,
        'stored_active_count': stored, 'state': state, 'group': group, 'reason': reason,
        'source_ids': sorted(str(f['source_id']) for f in matches),
        'checks': [{'id': c['id'], 'status': c['workflow_status'], 'result': c.get('result'),
                    'covers_current_risk': bool(covering and covering['check_id'] == c['id'])} for c in checks],
        'tasks': [{'id': t['id'], 'status': t['status'], 'check_id': t['check_id']} for t in tasks],
        'responsible_officer': {'id': selected.get('responsible_officer_id'),
                                'name': selected.get('responsible_officer_name') or ''},
        'linked_active_applications': row['linked_active_applications'],
        'covering_check_id': covering['check_id'] if covering else None,
        'potential_new_check': group == 'candidate', 'potential_new_task': group == 'candidate',
        'existing_check_without_task': bool(opened and not open_tasks)}


def snapshot(db_path, params, *, role, permissions, risk_projector, audit=None):
    if role not in {'admin', 'officer', 'viewer'} or not {'tasks.read', 'suppliers.read'} <= set(permissions):
        raise PermissionError('Недостатньо прав для перегляду НАЗК')
    options = query_options(params)
    with read_connection(db_path, audit=audit) as con:
        # Reuse the exact existing KPI/risk population logic with our RO connection.
        risk_codes = set(risk_projector(con)['nazk_codes'])
        population = {r[0] for r in con.execute('''SELECT supplier_code FROM supplier_registry_summary
          UNION SELECT supplier_code FROM submissions WHERE COALESCE(supplier_code,'')<>''
          ''')}
        codes = sorted(population & risk_codes)
        names = {canonical.normalize_name(r[0]) for r in con.execute('SELECT full_name FROM nazk_registry')}
        rows = []
        for code in codes:
            summary = con.execute('SELECT supplier_name,active_count FROM supplier_registry_summary WHERE supplier_code=?', (code,)).fetchone()
            manager_row = con.execute('SELECT id,manager_name FROM supplier_managers WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1', (code,)).fetchone()
            manager = dict(manager_row) if manager_row else None
            matches = canonical.registry_matches(con, manager['manager_name']) if manager else []
            checks = [dict(r) for r in con.execute('''SELECT c.*,GROUP_CONCAT(m.nazk_source_id) source_ids
              FROM supplier_nazk_checks c LEFT JOIN supplier_nazk_check_matches m ON m.check_id=c.id
              WHERE c.supplier_code=? GROUP BY c.id''', (code,))]
            tasks = [dict(r) for r in con.execute('''SELECT id,task_key,status,
              json_extract(source_context,'$.nazk_check_id') check_id FROM operational_tasks
              WHERE task_type='nazk_check' AND supplier_code=?''', (code,))]
            active = con.execute(f'''SELECT COUNT(DISTINCT rc.id) FROM registry_contracts rc
              JOIN frameworks f ON f.id=rc.framework_id WHERE rc.supplier_code=? AND {supplier_activity.effective_active_sql('rc','f')}''', (code,)).fetchone()[0]
            linked = con.execute(f'''SELECT COUNT(DISTINCT s.id) FROM registry_contracts rc
              JOIN frameworks f ON f.id=rc.framework_id JOIN qualifications q ON q.id=rc.qualification_id
              JOIN submissions s ON s.id=q.submission_id WHERE rc.supplier_code=? AND {supplier_activity.effective_active_sql('rc','f')}''', (code,)).fetchone()[0]
            legacy = con.execute('''SELECT rv.result FROM supplier_nazk_reviews rv
              JOIN supplier_edr_profiles ep ON ep.supplier_code=rv.supplier_code
              WHERE rv.supplier_code=? AND COALESCE(ep.manager_name,'')<>''
              AND NORMALIZE_NAME(rv.manager_name)=NORMALIZE_NAME(ep.manager_name)''', (code,)).fetchone()
            name = summary['supplier_name'] if summary else ''
            if not name:
                latest = con.execute('SELECT supplier_name FROM submissions WHERE supplier_code=? ORDER BY date_published DESC,id DESC LIMIT 1', (code,)).fetchone()
                name = latest[0] if latest else 'Назву не отримано'
            rows.append(classify({'code': code, 'name': name, 'active_count': active,
                'stored_active_count': summary['active_count'] if summary else None, 'manager': manager,
                'matches': matches, 'checks': checks, 'tasks': tasks, 'linked_active_applications': linked,
                'legacy_result': legacy['result'] if legacy else '',
                'application_state': canonical.get_supplier_application_nazk_state(con, code, names)['state']}))
        # Complete the snapshot before returning; never persist it or mutate a workflow.
    scope = options['scope']
    scoped = [r for r in rows if scope == 'all' or (r['active_count'] > 0 if scope == 'active' else r['active_count'] == 0)]
    counters = {'population': len(rows), 'active_suppliers': sum(r['active_count'] > 0 for r in rows),
        'new_checks': sum(r['potential_new_check'] for r in scoped),
        'new_tasks': sum(r['potential_new_task'] for r in scoped),
        'in_progress': sum(r['group'] == 'existing' for r in scoped),
        'without_applications': sum(r['active_count'] > 0 and r['linked_active_applications'] == 0 for r in scoped),
        'existing_checks_without_tasks': sum(r['existing_check_without_task'] for r in scoped)}
    search = options.get('search', '').strip().casefold()
    filtered = [r for r in scoped if (not search or search in (r['name'] + ' ' + r['code']).casefold())
        and all(not options.get(k) or r[k] == options[k] for k in ('state', 'reason', 'group'))]
    size, page = options['size'], options['page']
    return {'read_only': True, 'can_launch': False, 'snapshot_at': datetime.now(timezone.utc).isoformat(),
        'counts': counters, 'items': filtered[(page-1)*size:page*size], 'total': len(filtered),
        'page': page, 'size': size, 'pages': max(1, (len(filtered)+size-1)//size),
        'states': STATES, 'reasons': REASONS}
