"""Reusable persisted system column widths, independent of personal profiles."""
import json
from datetime import datetime, timezone

def migrate(con):
    con.execute('''CREATE TABLE IF NOT EXISTS system_table_widths (
      table_key TEXT PRIMARY KEY,widths_json TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT NOT NULL,updated_by TEXT NOT NULL)''')

def list_all(con):
    result={}
    for row in con.execute('SELECT table_key,widths_json FROM system_table_widths'):
        try: result[row['table_key']]=json.loads(row['widths_json'])
        except (TypeError,ValueError): result[row['table_key']]={}
    return result

def save(con,table_key,widths,user,visible=None):
    key=str(table_key or '').strip()
    if not key or len(key)>120: raise ValueError('Некоректний ключ таблиці')
    clean={str(k):max(40,min(1200,int(v))) for k,v in dict(widths or {}).items() if str(k).strip()}
    if visible is not None:
        clean['__visible__']=[str(value) for value in visible if str(value).strip()]
    con.execute('''INSERT INTO system_table_widths VALUES (?,?,?,?) ON CONFLICT(table_key) DO UPDATE SET
      widths_json=excluded.widths_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
      (key,json.dumps(clean,ensure_ascii=False,sort_keys=True),datetime.now(timezone.utc).isoformat(),user))
    return clean

def reset(con,table_key):
    con.execute('DELETE FROM system_table_widths WHERE table_key=?',(str(table_key or '').strip(),))
