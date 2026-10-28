"""Chat-scoped annotations. Reads never migrate, mark read, or mutate messages."""
from datetime import datetime, timezone
import re

REACTIONS = {'support', 'seen'}
WORK_STATES = {'working', 'done', ''}
FILTERS = {'all', 'unmarked', *REACTIONS, 'working', 'done'}


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def migrate(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS chat_reactions (
      message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
      username TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('support','seen')),
      created_at TEXT NOT NULL,PRIMARY KEY(message_id,username,kind));
    CREATE TABLE IF NOT EXISTS chat_work_state (
      message_id INTEGER PRIMARY KEY REFERENCES chat_messages(id) ON DELETE CASCADE,
      state TEXT NOT NULL CHECK(state IN ('working','done','')),
      username TEXT NOT NULL,changed_at TEXT NOT NULL,version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_work_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
      old_state TEXT NOT NULL,new_state TEXT NOT NULL,username TEXT NOT NULL,
      changed_at TEXT NOT NULL,version INTEGER NOT NULL,UNIQUE(message_id,version));
    CREATE INDEX IF NOT EXISTS ix_chat_work_history_message ON chat_work_history(message_id,id);
    ''')


def member(con, chat_id, username):
    if not con.execute('SELECT 1 FROM chat_members WHERE chat_id=? AND username=?',
                       (chat_id, username)).fetchone():
        raise ChatError('Чат не знайдено', 404)


def marks(con, message_id):
    reactions = [dict(row) for row in con.execute(
        'SELECT kind,username,created_at FROM chat_reactions WHERE message_id=? ORDER BY kind,username',
        (message_id,))]
    state = con.execute('SELECT state,username,changed_at,version FROM chat_work_state WHERE message_id=?',
                        (message_id,)).fetchone()
    return {'reactions': reactions, 'work': dict(state) if state else
            {'state': '', 'username': '', 'changed_at': '', 'version': 0}}


def change(con, chat_id, message_id, username, payload):
    """Explicit desired reaction state; optimistic work versions prevent lost updates."""
    kind = payload.get('kind')
    if not isinstance(kind,str) or kind not in REACTIONS | {'work'}:
        raise ChatError('Невідома позначка')
    if kind in REACTIONS and type(payload.get('active')) is not bool:
        raise ChatError('Потрібен явний стан реакції')
    if kind == 'work' and (not isinstance(payload.get('state'),str) or payload.get('state') not in WORK_STATES or
                           type(payload.get('version')) is not int or payload['version'] < 0):
        raise ChatError('Потрібні стан і версія позначки')
    con.execute('BEGIN IMMEDIATE')
    member(con, chat_id, username)
    if not con.execute('SELECT 1 FROM chat_messages WHERE id=? AND chat_id=?',
                       (message_id, chat_id)).fetchone():
        raise ChatError('Повідомлення не знайдено', 404)
    stamp = datetime.now(timezone.utc).isoformat()
    if kind in REACTIONS:
        if payload['active']:
            con.execute('INSERT OR IGNORE INTO chat_reactions VALUES (?,?,?,?)',
                        (message_id, username, kind, stamp))
        else:
            con.execute('DELETE FROM chat_reactions WHERE message_id=? AND username=? AND kind=?',
                        (message_id, username, kind))
    else:
        current = marks(con, message_id)['work']
        # A repeated identical request is a no-op, including a response lost in transit.
        if current['state'] == payload['state'] and current['username'] == username:
            return marks(con, message_id)
        if current['version'] != payload['version']:
            raise ChatError('Позначку вже змінив інший учасник. Оновіть повідомлення.', 409)
        if current['state'] == payload['state']:
            return marks(con, message_id)
        version = current['version'] + 1
        con.execute('''INSERT INTO chat_work_state VALUES (?,?,?,?,?)
          ON CONFLICT(message_id) DO UPDATE SET state=excluded.state,username=excluded.username,
          changed_at=excluded.changed_at,version=excluded.version''',
                    (message_id, payload['state'], username, stamp, version))
        con.execute('''INSERT INTO chat_work_history
          (message_id,old_state,new_state,username,changed_at,version) VALUES (?,?,?,?,?,?)''',
                    (message_id, current['state'], payload['state'], username, stamp, version))
    return marks(con, message_id)


def select_messages(con, chat_id, username, params):
    member(con, chat_id, username)
    selected = params.get('mark', ['all'])[0]
    if selected not in FILTERS:
        raise ChatError('Невідомий фільтр')
    try:
        page = max(1, int(params.get('page', ['1'])[0]))
    except (ValueError, TypeError):
        raise ChatError('Некоректна сторінка') from None
    where, args = ['m.chat_id=?'], [chat_id]
    query = str(params.get('search', [''])[0]).strip()[:200]
    # Search every message in this chat before pagination. Each query token may
    # match the message body or the structured application linked to it.
    terms = re.findall(r'[^\W_]+(?:-[^\W_]+)*', query, flags=re.UNICODE)
    if query and not terms:
        terms = [query]
    if terms:
        con.create_function('chat_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
        for term in terms[:24]:
            folded = 'chat_casefold(?)'
            where.append(f'''(instr(chat_casefold(m.body),{folded})>0
              OR instr(chat_casefold(m.submission_id),{folded})>0
              OR EXISTS (SELECT 1 FROM submissions s
                LEFT JOIN frameworks f ON f.id=s.framework_id
                WHERE s.id=m.submission_id AND (
                  instr(chat_casefold(s.supplier_code),{folded})>0
                  OR instr(chat_casefold(s.supplier_name),{folded})>0
                  OR instr(chat_casefold(f.dk_code),{folded})>0)))''')
            args.extend([term] * 5)
    if selected in REACTIONS:
        where.append('EXISTS (SELECT 1 FROM chat_reactions r WHERE r.message_id=m.id AND r.kind=?)')
        args.append(selected)
    elif selected in {'working', 'done'}:
        where.append('EXISTS (SELECT 1 FROM chat_work_state w WHERE w.message_id=m.id AND w.state=?)')
        args.append(selected)
    elif selected == 'unmarked':
        where.append('''NOT EXISTS (SELECT 1 FROM chat_reactions r WHERE r.message_id=m.id)
          AND NOT EXISTS (SELECT 1 FROM chat_work_state w WHERE w.message_id=m.id AND w.state<>'')''')
    try:
        before = int(params.get('before', ['0'])[0])
        after = int(params.get('after', ['0'])[0])
        since = int(params.get('since', ['0'])[0])
        known = [int(value) for value in params.get('known', [''])[0].split(',') if value]
        if before < 0 or after < 0 or (before and after) or since < 0 or len(known)>100 or any(value<1 for value in known):
            raise ValueError()
    except (TypeError,ValueError):
        raise ChatError('Некоректний курсор') from None
    clause = ' AND '.join(where)
    total = con.execute(f'SELECT COUNT(*) FROM chat_messages m WHERE {clause}', args).fetchone()[0]
    pages = max(1, (total + 99) // 100)
    page = min(page, pages)
    # Page 1 contains the latest messages, displayed chronologically within each page.
    cursor_clause = clause + (' AND m.id<?' if before else ' AND m.id>?' if after else '')
    cursor_args = [*args, before or after] if before or after else args
    order='ASC' if after else 'DESC'
    rows = con.execute(f'SELECT m.* FROM chat_messages m WHERE {cursor_clause} ORDER BY m.id {order} LIMIT 100 OFFSET ?',
                       (*cursor_args, 0 if before or after else (page - 1) * 100)).fetchall()
    updates = []
    if known:
        updates = con.execute(f"SELECT m.* FROM chat_messages m WHERE {clause} AND m.id IN ({','.join('?'*len(known))})",
                              (*args,*known)).fetchall()
    new_count = con.execute(f'SELECT COUNT(*) FROM chat_messages m WHERE {clause} AND m.id>?',
                            (*args,since)).fetchone()[0] if since else 0
    has_more=bool(after and rows and con.execute(f'SELECT 1 FROM chat_messages m WHERE {clause} AND m.id>? LIMIT 1',(*args,rows[-1]['id'])).fetchone())
    return rows if after else list(reversed(rows)), {'total': total, 'page': page, 'pages': pages,
                                  'new_count':new_count,'known_ids':known,'has_more':has_more}, updates
