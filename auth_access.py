"""Additive WEB-compatible accounts and centrally registered LOCAL/WEB permissions."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone

def stamp():
    return datetime.now(timezone.utc).isoformat()

# key, module, label, officer default, GET/non-mutating or mutation, route pattern
PERMISSIONS = [
 ('applications.read','Реєстр заявок','Перегляд заявок',True,False,r'/api/(?:applications(?:/.*)?|document-check-jobs/.*|protocol/files/.*|stats|application-history|application-profiles(?:/.*)?|frameworks|supplier-options)'),
 ('applications.edit','Реєстр заявок','Редагування заявки та зауважень',True,True,r'/api/applications/[^/]+(?:/remark-selections)?'),
 ('applications.check','Реєстр заявок','Перевірка документів / НАЗК',True,True,r'/api/applications/[^/]+/(?:verify-documents(?:/start)?|nazk-control)'),
 ('profiles.edit','Реєстр заявок','Особисті профілі',True,True,r'/api/application-profiles(?:/[^/]+)?'),
 ('protocol.generate','Реєстр заявок','Формування протоколів',True,True,r'/api/protocol/(?:readiness|generate)'),
 ('prozorro.update','Реєстр заявок','Оновлення Prozorro',False,True,r'/api/(?:sync|frameworks/refresh)'),
 ('suppliers.read','База постачальників','Перегляд постачальників',True,False,r'/api/(?:suppliers-registry|supplier-profile/.*|supplier-procurements/.*)'),
 ('suppliers.note','База постачальників','Спільна примітка',True,True,r'/api/suppliers/[^/]+/note'),
 ('suppliers.nazk','База постачальників','Перевірка НАЗК',True,True,r'/api/suppliers/[^/]+/nazk-check'),
 ('appeals.read','Звернення','Перегляд звернень',True,False,r'/api/violation-reports(?:/.*)?'),
 ('appeals.review','Звернення','Розгляд і протокол',True,True,r'/api/violation-reports/[^/]+/(?:review(?:/complete)?|protocol/generate|documents/.*)'),
 ('appeals.update','Звернення','Оновлення звернень',False,True,r'/api/violation-reports/sync'),
 ('work.read','Робота УО','Перегляд робочої черги',True,False,r'/api/uo-work-queue'),
 ('frameworks.read','Відбори','Перегляд відборів',True,False,r'/api/(?:framework-analytics(?:/.*)?|admin/frameworks|admin/officers)'),
 ('remarks.read','Довідники','Перегляд конструктора зауважень',True,False,r'/api/remarks-catalog'),
 ('remarks.edit','Довідники','Керування пунктами зауважень',False,True,r'/api/remarks-catalog(?:/[^/]+)?'),
 ('references.read','Довідники','Перегляд реєстрів',True,False,r'/api/(?:reference-status|nazk-registry|amcu-registry|references|nazk|amcu)(?:/.*)?'),
 ('references.update','Довідники','Оновлення та імпорт реєстрів',False,True,r'/api/(?:nazk-registry|amcu-registry|references|nazk|amcu)(?:/.*)?'),
 ('bids.read','Bids','Перегляд статусу',True,False,r'/api/bids-sync-status'),
 ('bids.update','Bids','Запуск оновлення',False,True,r'/api/bids-sync'),
 ('admin.manage','Адміністрування','Користувачі, ролі та системні налаштування',False,True,r'/api/admin/.*'),
 ('admin.read','Адміністрування','Перегляд адміністрування',False,False,r'/api/(?:admin/.*|audit)'),
]
BY_KEY={p[0]:p for p in PERMISSIONS}

def migrate(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS auth_users (
      username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','officer','viewer')),
      officer_id INTEGER REFERENCES authorized_officers(id),active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL,created_by TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_auth_users_officer ON auth_users(officer_id)
      WHERE officer_id IS NOT NULL AND active=1;
    CREATE TABLE IF NOT EXISTS user_preferences (
      username TEXT PRIMARY KEY,display_name TEXT NOT NULL DEFAULT '',
      start_view TEXT NOT NULL DEFAULT 'applications',color_scheme TEXT NOT NULL DEFAULT 'system',
      density TEXT NOT NULL DEFAULT 'comfortable',presence_status TEXT NOT NULL DEFAULT 'working',updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS auth_roles (
      code TEXT PRIMARY KEY,label TEXT NOT NULL,base_role TEXT NOT NULL CHECK(base_role IN ('admin','officer','viewer')),
      active INTEGER NOT NULL DEFAULT 1,protected INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,updated_by TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS auth_role_permissions (
      role_code TEXT NOT NULL REFERENCES auth_roles(code),permission_key TEXT NOT NULL,
      allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),updated_at TEXT NOT NULL,updated_by TEXT NOT NULL,
      PRIMARY KEY(role_code,permission_key));
    CREATE TABLE IF NOT EXISTS auth_user_roles (
      username TEXT PRIMARY KEY REFERENCES auth_users(username),role_code TEXT NOT NULL REFERENCES auth_roles(code),
      updated_at TEXT NOT NULL,updated_by TEXT NOT NULL);
    ''')
    if 'last_seen_at' not in {r[1] for r in con.execute('PRAGMA table_info(auth_users)')}:
        con.execute('ALTER TABLE auth_users ADD COLUMN last_seen_at TEXT')
    if 'presence_status' not in {r[1] for r in con.execute('PRAGMA table_info(user_preferences)')}:
        con.execute("ALTER TABLE user_preferences ADD COLUMN presence_status TEXT NOT NULL DEFAULT 'working'")
    for code,label in [('admin','Адміністратор'),('officer','УО'),('viewer','Перегляд')]:
        con.execute('INSERT OR IGNORE INTO auth_roles VALUES (?,?,?,1,1,?,?)',(code,label,code,stamp(),'bootstrap schema'))

def accounts(con, configured):
    out=dict(configured)
    for row in con.execute('SELECT username,password_hash,role,officer_id,active FROM auth_users'):
        out[row['username']]={'secret':row['password_hash'],'role':row['role'],'officer_id':row['officer_id'],'active':bool(row['active'])}
    return out

def effective(con, username, base):
    row=con.execute('SELECT r.* FROM auth_user_roles u JOIN auth_roles r ON r.code=u.role_code WHERE u.username=?',(username,)).fetchone()
    if row and (not row['active'] or row['base_role']!=base):
        return {'code':row['code'],'base_role':base,'active':False,'permissions':{}}
    code=row['code'] if row else base
    overrides={r['permission_key']:bool(r['allowed']) for r in con.execute('SELECT permission_key,allowed FROM auth_role_permissions WHERE role_code=?',(code,))}
    rights={key:(True if base=='admin' else False if base=='viewer' and mutation else overrides.get(key,default if base=='officer' else not mutation and default)) for key,module,label,default,mutation,pattern in PERMISSIONS}
    return {'code':code,'base_role':base,'active':True,'permissions':rights}

def permission_key(method,path):
    if method=='GET' and re.fullmatch(r'/api/applications/[^/]+/verify-documents/start',path):
        return 'applications.check'
    mutation=method in {'POST','PATCH','PUT','DELETE'}
    return next((key for key,module,label,default,m,p in PERMISSIONS if m==mutation and re.fullmatch(p,path)),None)

def hash_password(value):
    if len(value)<10:raise ValueError('Пароль має містити щонайменше 10 символів')
    salt=secrets.token_bytes(16)
    return 'pbkdf2_sha256:260000:'+salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',value.encode(),salt,260000).hex()

def verify_password(value,stored):
    try:
        _,rounds,salt,digest=stored.split(':')
        rounds=int(rounds)
        if not 10000<=rounds<=2000000:return False
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',value.encode(),bytes.fromhex(salt),rounds).hex(),digest)
    except (ValueError,TypeError):return False

def roles_payload(con):
    roles=[]
    for row in con.execute('SELECT * FROM auth_roles ORDER BY protected DESC,label'):
        item=dict(row)
        overrides={r['permission_key']:bool(r['allowed']) for r in con.execute('SELECT * FROM auth_role_permissions WHERE role_code=?',(row['code'],))}
        item['permissions']={p[0]:True if row['base_role']=='admin' else False if row['base_role']=='viewer' and p[4] else overrides.get(p[0],p[3]) for p in PERMISSIONS}
        roles.append(item)
    return {'roles':roles,'functions':[{'key':k,'module':m,'label':l,'mutation':mut} for k,m,l,d,mut,p in PERMISSIONS]}

def save_role(con,payload,user):
    code=str(payload.get('code') or '').strip()
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,48}',code):raise ValueError('Некоректний код ролі')
    base=payload.get('base_role');label=str(payload.get('label') or '').strip()
    if base not in {'admin','officer','viewer'} or not label:raise ValueError('Оберіть базову роль і назву')
    old=con.execute('SELECT * FROM auth_roles WHERE code=?',(code,)).fetchone()
    if old and old['base_role']!=base:raise ValueError('Базову роль існуючої ролі змінювати не можна')
    active=bool(payload.get('active',True))
    if (old and old['protected'] or base=='admin') and not active:raise ValueError('Захищену роль не можна вимкнути')
    if not active and con.execute('SELECT 1 FROM auth_user_roles WHERE role_code=?',(code,)).fetchone():raise ValueError('Спочатку перепризначте користувачів цієї ролі')
    rights=payload.get('permissions',{})
    if not isinstance(rights,dict) or any(k not in BY_KEY or not isinstance(v,bool) for k,v in rights.items()):raise ValueError('Некоректні повноваження')
    if base=='viewer' and any(v and BY_KEY[k][4] for k,v in rights.items()):raise ValueError('Перегляд не може змінювати дані')
    if base!='admin' and any(v and k.startswith('admin.') for k,v in rights.items()):raise ValueError('Керування адміністративним доступом потребує базової ролі Адміністратор')
    if base=='admin' and any(not v for v in rights.values()):raise ValueError('Адміністративний доступ захищений від блокування')
    con.execute('INSERT INTO auth_roles VALUES (?,?,?, ?,0,?,?) ON CONFLICT(code) DO UPDATE SET label=excluded.label,active=excluded.active,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(code,label,base,int(active),stamp(),user))
    for key,value in rights.items():
        con.execute('INSERT INTO auth_role_permissions VALUES (?,?,?,?,?) ON CONFLICT(role_code,permission_key) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(code,key,int(value),stamp(),user))

def users_payload(con):
    return {'items':[dict(r) for r in con.execute('''SELECT u.username,u.role,u.officer_id,u.active,
      p.display_name,COALESCE(a.role_code,u.role) role_code FROM auth_users u
      LEFT JOIN user_preferences p ON p.username=u.username LEFT JOIN auth_user_roles a ON a.username=u.username ORDER BY u.username''')]}

def save_user(con,payload,actor,configured):
    name=str(payload.get('username') or '').strip()
    if not name or len(name)>100:raise ValueError('Вкажіть логін')
    old=con.execute('SELECT * FROM auth_users WHERE username=?',(name,)).fetchone()
    if not old and name in configured:raise ValueError('Цей логін керується environment; автоматичне перенесення заборонене')
    role=con.execute('SELECT * FROM auth_roles WHERE code=? AND active=1',(payload.get('role_code'),)).fetchone()
    if not role:raise ValueError('Оберіть чинну роль')
    active=bool(payload.get('active',True));base=role['base_role'];officer=payload.get('officer_id') or None
    if base=='officer' and not con.execute('SELECT 1 FROM authorized_officers WHERE id=? AND active=1',(officer,)).fetchone():raise ValueError('Оберіть активну УО')
    if base!='officer':officer=None
    if name==actor and (not active or base!='admin'):raise ValueError('Не можна заблокувати власний адміністративний доступ')
    if old and old['role']=='admin' and old['active'] and (not active or base!='admin'):
        remaining=accounts(con,configured);remaining.pop(name,None)
        if not any(a['role']=='admin' and a.get('active',True) for a in remaining.values()):raise ValueError('Не можна вимкнути останнього адміністратора')
    password=payload.get('password')
    secret=hash_password(password) if password else old['password_hash'] if old else None
    if not secret:raise ValueError('Вкажіть початковий пароль')
    con.execute('''INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by)
      VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role,officer_id=excluded.officer_id,active=excluded.active,updated_at=excluded.updated_at''',(name,secret,base,officer,int(active),stamp(),stamp(),actor))
    con.execute('INSERT INTO auth_user_roles VALUES (?,?,?,?) ON CONFLICT(username) DO UPDATE SET role_code=excluded.role_code,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(name,role['code'],stamp(),actor))
    con.execute('INSERT INTO user_preferences(username,display_name,updated_at) VALUES (?,?,?) ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,updated_at=excluded.updated_at',(name,str(payload.get('display_name') or ''),stamp()))
