"""Parameterized read-only audit filtering; no schema or index management."""
from contextlib import closing
from datetime import date,datetime,time as day_time,timedelta
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo


def read(db_path, params):
    def value(key):
        text=str(params.get(key,[''])[0] or '').strip()
        if len(text)>500:raise ValueError('Занадто довгий фільтр журналу')
        return text
    page=max(1,int(value('page') or 1));size=min(200,max(1,int(value('size') or 100)))
    conditions=[];args=[]
    search=value('search')
    if search:
        columns=['submission_id','changed_by','field_name','old_value','new_value']
        conditions.append('('+ ' OR '.join('INSTR(CASEFOLD(COALESCE('+c+",'')),?)>0" for c in columns)+')')
        args.extend([search.casefold()]*len(columns))
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
    with closing(sqlite3.connect(Path(db_path).resolve(strict=True).as_uri()+'?mode=ro',uri=True,timeout=5)) as con:
        con.row_factory=sqlite3.Row
        con.create_function('CASEFOLD',1,lambda x:str(x or '').casefold(),deterministic=True)
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        deadline=time.monotonic()+10
        con.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        total=int(con.execute('SELECT COUNT(*) FROM audit_log'+where,args).fetchone()[0])
        rows=[dict(row) for row in con.execute('SELECT * FROM audit_log'+where+' ORDER BY id DESC LIMIT ? OFFSET ?',[*args,size,(page-1)*size])]
    return dict(items=rows,total=total,page=page,pages=max(1,(total+size-1)//size),size=size)
