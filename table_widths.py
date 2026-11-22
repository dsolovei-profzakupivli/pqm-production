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
        try:
            value=json.loads(row['widths_json'])
            result[row['table_key']]=value if isinstance(value,dict) else {}
        except (TypeError,ValueError): result[row['table_key']]={}
    return result

def save(con,table_key,widths,user,visible=None,order=None,columns=None):
    key=str(table_key or '').strip()
    if not key or len(key)>120: raise ValueError('Некоректний ключ таблиці')
    if widths is not None and not isinstance(widths,dict): raise ValueError('Ширини мають бути об’єктом')
    row=con.execute('SELECT widths_json FROM system_table_widths WHERE table_key=?',(key,)).fetchone()
    try: clean=json.loads(row['widths_json']) if row else {}
    except (TypeError,ValueError): clean={}
    if not isinstance(clean,dict): clean={}
    clean={str(k):v for k,v in clean.items()}
    for k,v in dict(widths or {}).items():
        name=str(k).strip()
        if not name or name.startswith('__'): continue
        clean[name]=max(40,min(1200,int(v)))
    if visible is not None:
        if not isinstance(visible,list): raise ValueError('Видимі колонки мають бути списком')
        clean['__visible__']=_unique_keys(visible,'видимих колонок')
    if order is not None:
        if not isinstance(order,list): raise ValueError('Порядок колонок має бути списком')
        clean['__order__']=_unique_keys(order,'порядку колонок')
    if columns is not None:
        if not isinstance(columns,list): raise ValueError('Перелік колонок має бути списком')
        clean['__columns__']=_unique_keys(columns,'переліку колонок')
    con.execute('''INSERT INTO system_table_widths VALUES (?,?,?,?) ON CONFLICT(table_key) DO UPDATE SET
      widths_json=excluded.widths_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
      (key,json.dumps(clean,ensure_ascii=False,sort_keys=True),datetime.now(timezone.utc).isoformat(),user))
    return clean

def _unique_keys(values,label):
    result=[];seen=set()
    for value in values:
        item=str(value or '').strip()
        if not item or len(item)>160: raise ValueError(f'Некоректний ключ у {label}')
        if item in seen: raise ValueError(f'Повтор колонки у {label}')
        seen.add(item);result.append(item)
    if len(result)>300: raise ValueError(f'Забагато колонок у {label}')
    return result

def reset(con,table_key):
    con.execute('DELETE FROM system_table_widths WHERE table_key=?',(str(table_key or '').strip(),))
