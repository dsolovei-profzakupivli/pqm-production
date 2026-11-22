"""Parameterized read-only audit filtering; no schema or index management."""
from contextlib import closing
from datetime import date,datetime,time as day_time,timedelta
from pathlib import Path
import sqlite3
import time
import threading
from zoneinfo import ZoneInfo


class AuditResourceError(Exception):
    status=503
    code='audit_resource_limit'

class AuditSuperseded(AuditResourceError):
    status=409
    code='audit_superseded'

_scopes={}
_scope_lock=threading.Lock()

def _scope(actor, params):
    client=str(params.get('client_id',[''])[0])
    if not client:return None,None
    if len(client)>80 or not all(c.isalnum() or c in '-_' for c in client):raise ValueError('Невірний ідентифікатор пошуку')
    sequence=int(params.get('request_id',['0'])[0])
    if not 0<sequence<2**53:raise ValueError('Невірний номер пошуку')
    key=(str(actor),client)
    with _scope_lock:
        now=time.monotonic()
        for old,state in list(_scopes.items()):
            if now-state[2]>600 and state[1] is None:_scopes.pop(old,None)
        previous=_scopes.get(key)
        if previous and sequence<=previous[0]:raise AuditSuperseded('Пошук замінено новішим запитом')
        if previous and previous[1]:previous[1].set()
        cancel=params.get('cancel',[''])[0]=='1'
        event=None if cancel else threading.Event()
        _scopes[key]=(sequence,event,now)
    return key,event

def read(db_path, params, *, actor='local'):
    def value(key):
        text=str(params.get(key,[''])[0] or '').strip()
        if len(text)>500:raise ValueError('Занадто довгий фільтр журналу')
        return text
    page=max(1,int(value('page') or 1));size=min(200,max(1,int(value('size') or 100)))
    conditions=[];args=[]
    search=value('search')
    if search:
        columns=['submission_id','changed_by','field_name','old_value','new_value']
        conditions.append('AUDIT_MATCH(?,'+','.join(columns)+')=1')
        args.append(search.casefold())
    for key,column in [('user','changed_by'),('field','field_name')]:
        if value(key):
            conditions.append(column+'=?');args.append(value(key))
    start,end=value('date_from'),value('date_to')
    for stamp in (start,end):
        if stamp and date.fromisoformat(stamp).isoformat()!=stamp:raise ValueError('Невірна дата журналу')
    if start and end and start>end:raise ValueError('Дата «Від» пізніша за «До»')
    # User calendar days are Kyiv days, including DST; stored UTC instants stay intact.
    if start:
        conditions.append('julianday(changed_at)>=julianday(?)')
        args.append(datetime.combine(date.fromisoformat(start),day_time(),ZoneInfo('Europe/Kyiv')).isoformat())
    if end:
        conditions.append('julianday(changed_at)<julianday(?)')
        args.append(datetime.combine(date.fromisoformat(end)+timedelta(days=1),day_time(),ZoneInfo('Europe/Kyiv')).isoformat())
    where=' WHERE '+' AND '.join(conditions) if conditions else ''
    key,event=_scope(actor,params)
    if params.get('cancel',[''])[0]=='1':return {'cancelled':True}
    deadline=time.monotonic()+10
    try:
        with closing(sqlite3.connect(Path(db_path).resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=5)) as con:
            con.row_factory=sqlite3.Row
            con.create_function('AUDIT_MATCH',6,lambda needle,*values:int(any(needle in str(x or '').casefold() for x in values)),deterministic=True)
            con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
            con.set_progress_handler(lambda:int(bool(event and event.is_set()) or time.monotonic()>deadline),1000)
            if event and event.is_set():raise AuditSuperseded('Пошук замінено новішим запитом')
            if where:
                # Materialize IDs only: evaluate Unicode matching once per row.
                # The LEFT JOIN retains the exact total even on an empty/out-of-range page.
                result=con.execute('WITH matches AS MATERIALIZED (SELECT id FROM audit_log'+where+'), '
                    'totals AS (SELECT COUNT(*) AS matched_total FROM matches), '
                    'selected AS (SELECT id FROM matches ORDER BY id DESC LIMIT ? OFFSET ?) '
                    'SELECT totals.matched_total,a.* FROM totals LEFT JOIN selected ON 1=1 '
                    'LEFT JOIN audit_log a ON a.id=selected.id ORDER BY a.id DESC',
                    [*args,size,(page-1)*size]).fetchall()
                total=int(result[0]['matched_total'])
                rows=[{k:row[k] for k in row.keys() if k!='matched_total'} for row in result if row['id'] is not None]
            else:
                total=int(con.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0])
                rows=[dict(row) for row in con.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?',[size,(page-1)*size])]
            if event and event.is_set():raise AuditSuperseded('Пошук замінено новішим запитом')
            if time.monotonic()>deadline:raise AuditResourceError('Пошук перевищив доступний ресурс. Уточніть фільтри та повторіть спробу.')
    except sqlite3.OperationalError as exc:
        if event and event.is_set():raise AuditSuperseded('Пошук замінено новішим запитом') from exc
        if str(exc)=='interrupted' and time.monotonic()>deadline:
            raise AuditResourceError('Пошук перевищив доступний ресурс. Уточніть фільтри та повторіть спробу.') from exc
        if 'locked' in str(exc) or 'busy' in str(exc):raise AuditResourceError('Журнал тимчасово зайнятий. Повторіть спробу пізніше.') from exc
        raise
    finally:
        if key:
            with _scope_lock:
                current=_scopes.get(key)
                if current and current[1] is event:_scopes[key]=(current[0],None,time.monotonic())
    return dict(items=rows,total=total,page=page,pages=max(1,(total+size-1)//size),size=size)
