"""Offline additive migration. Default is read-only plan; never imports PQM/server."""
import argparse
import datetime
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager, closing

@contextmanager
def db_connection(*args, **kwargs):
    with closing(sqlite3.connect(*args, **kwargs)) as con:
        with con:
            yield con


def q(name): return '"'+name.replace('"','""')+'"'
def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def columns(con,name):
    return {r[1]:dict(zip(('cid','name','type','notnull','default','pk'),r)) for r in con.execute('PRAGMA table_info('+q(name)+')')}
def tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
def definitions(sql):
    """Top-level CREATE TABLE clauses, honoring quotes and nested CHECK/defaults."""
    text=sql[sql.index('(')+1:sql.rfind(')')];out=[];start=0;depth=0;quote=None;i=0
    while i<len(text):
        c=text[i]
        if quote:
            if c==quote:
                if i+1<len(text) and text[i+1]==quote:i+=1
                else:quote=None
        elif c in "'\"`":quote=c
        elif c=='[':quote=']'
        elif c=='(':depth+=1
        elif c==')':depth-=1
        elif c==',' and depth==0:out.append(text[start:i].strip());start=i+1
        i+=1
    out.append(text[start:].strip())
    return out
def normalized(sql):
    return re.sub(r'\s+',' ',re.sub(r'\bIF NOT EXISTS\b','',sql,flags=re.I)).strip().rstrip(';')
def plan(con,target):
    present=set(tables(con));steps=[];blockers=[]
    for table in target['tables']:
        name=table['name']
        if name not in present:
            steps.append(table['sql']);continue
        actual=columns(con,name)
        for col in table['columns']:
            if col['name'] in actual:
                old=actual[col['name']]
                if old['type'].upper()!=col['type'].upper() or old['pk']!=col['pk'] or old['notnull']!=col['notnull']:
                    blockers.append('Incompatible column '+name+'.'+col['name'])
                continue
            clauses=[d for d in definitions(table['sql']) if re.match(r'^(?:"'+re.escape(col['name'])+r'"|'+re.escape(col['name'])+r')\s',d)]
            if len(clauses)!=1 or col['pk'] or (col['notnull'] and col['default'] is None) or re.search(r'\bUNIQUE\b',clauses[0],re.I):
                blockers.append('Cannot safely ADD column '+name+'.'+col['name']);continue
            steps.append('ALTER TABLE '+q(name)+' ADD COLUMN '+clauses[0])
        # Preserve foreign-key definitions; missing/mismatched constraints require separate review.
        expected=sqlite3.connect(':memory:')
        try:
            expected.execute(table['sql'])
            old_fk={tuple(r) for r in con.execute('PRAGMA foreign_key_list('+q(name)+')')}
            new_fk={tuple(r) for r in expected.execute('PRAGMA foreign_key_list('+q(name)+')')}
            # Added-column REFERENCES will be created by ADD COLUMN; common fields must agree.
            for fk in new_fk:
                if fk[3] in actual and not any(fk[2:]==old[2:] for old in old_fk):
                    blockers.append('Missing/incompatible FK '+name+'.'+fk[3])
        finally:expected.close()
    for index in target['indexes']:
        row=con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",(index['name'],)).fetchone()
        if row:
            if normalized(row[0] or '')!=normalized(index['sql']):blockers.append('Index name collision '+index['name'])
        else:steps.append(index['sql'])
    return steps,sorted(set(blockers))
def fingerprints(con, fields=None):
    """Commutative row digest of OLD columns; includes auth/chat extras, no values in report."""
    fields=fields or {n:list(columns(con,n)) for n in tables(con)}
    result={}
    for name,cols in fields.items():
        count=0;total=0
        for row in con.execute('SELECT '+','.join(map(q,cols))+' FROM '+q(name)):
            values=[{'blob':v.hex()} if isinstance(v,bytes) else v for v in row]
            h=hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).digest()
            total=(total+int.from_bytes(h,'big'))%(1<<256);count+=1
        result[name]={'count':count,'old_columns_sha256_sum':f'{total:064x}'}
    return fields,result
def verify(con):
    integrity=[r[0] for r in con.execute('PRAGMA integrity_check')]
    fk=con.execute('PRAGMA foreign_key_check').fetchall()
    if integrity!=['ok'] or fk:raise RuntimeError('STOP: integrity/FK failed; no automatic repair')
    return {'integrity':'ok','foreign_key_violations':0}
def migrate(database,target,backup_dir):
    # Caller must stop writes/schedulers. BEGIN IMMEDIATE prevents concurrent DB writers.
    con=sqlite3.connect(database,timeout=10);con.execute('PRAGMA foreign_keys=ON')
    con.execute('BEGIN IMMEDIATE')
    try:
        steps,blockers=plan(con,target)
        if blockers:raise RuntimeError('STOP: '+ '; '.join(blockers))
        verify(con)
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup=backup_dir/('pqm-before-0509-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.sqlite3')
        if backup.exists():raise RuntimeError('Backup already exists')
        # Separate reader backs up the committed state while this connection holds writer lock.
        with db_connection(database.as_uri()+'?mode=ro',uri=True) as reader,db_connection(backup) as dst:reader.backup(dst)
        with db_connection(backup.as_uri()+'?mode=ro',uri=True) as check:verify(check)
        fields,before=fingerprints(con)
        for sql in steps:
            if not re.match(r'^\s*(CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)|ALTER\s+TABLE)',sql,re.I):raise RuntimeError('Non-additive statement')
            con.execute(sql)
        after=fingerprints(con,fields)[1]
        if before!=after:raise RuntimeError('STOP: existing data changed; rolling back')
        checks=verify(con)
        remaining,blockers=plan(con,target)
        if remaining or blockers:raise RuntimeError('Schema verification failed')
        con.commit()
        return {'applied_statements':steps,'existing_data_identical':True,'before':before,'after':after,
          'backup_path':str(backup),'backup_size':backup.stat().st_size,'backup_sha256':sha(backup),**checks}
    except BaseException:
        con.rollback();raise
    finally:con.close()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--confirm-maintenance',action='store_true')
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--schema',type=Path,default=Path(__file__).with_name('target_schema.json'))
    args=parser.parse_args();database=args.db.resolve()
    if not database.is_file():parser.error('Existing WEB database required; never create replacement DB')
    if args.report.exists():parser.error('Report exists; choose a new path')
    target=json.loads(args.schema.read_text(encoding='utf-8'))
    if args.apply:
        if not args.confirm_maintenance or not args.backup_dir:parser.error('Apply requires --confirm-maintenance and --backup-dir')
        report=migrate(database,target,args.backup_dir.resolve())
    else:
        with db_connection(database.as_uri()+'?mode=ro',uri=True) as con:
            steps,blockers=plan(con,target)
            report={'mode':'READ_ONLY_PLAN','statements':steps,'blockers':blockers,'counts':{n:con.execute('SELECT COUNT(*) FROM '+q(n)).fetchone()[0] for n in tables(con)}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report written; keep it private. Blockers:',len(report.get('blockers',[])))
    if report.get('blockers'):raise SystemExit(2)
if __name__=='__main__':main()
