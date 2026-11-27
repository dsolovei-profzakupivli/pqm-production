"""Same synthetic 15,227-row workload in separate baseline/candidate processes."""
import gc
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import ctypes
from fixtures import server,sync,reset,supplier,row,snapshot,DATA
import sandbox_edr_review

con=reset();n=int(os.environ.get('PQM_V311_ROWS','15227'))
baseline=os.environ['PQM_V311_BASELINE']=='1'
variant=os.environ.get('PQM_V311_VARIANT','baseline' if baseline else 'candidate')
mode=os.environ.get('PQM_V311_MODE','plain');history=int(os.environ.get('PQM_V311_HISTORY','0'))
registry_rows=os.environ.get('PQM_V311_REGISTRY_ROWS','0')=='1'
nazk_rows=int(os.environ.get('PQM_V311_NAZK_ROWS','0'))
target=Path(os.environ['PQM_V311_SOURCE_ROOT'])/'evidence'
def rss():
    if os.name != 'nt':
        return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong),
            *[(name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
            'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):raise ctypes.WinError()
    return counters.WorkingSetSize
peak=[rss()];stop=threading.Event()
def sample():
    while not stop.wait(.02):peak[0]=max(peak[0],rss())
thread=threading.Thread(target=sample,daemon=True);thread.start()
queries=[0]
def trace(sql):
    if sql.lstrip().upper().startswith(('SELECT','WITH','PRAGMA')):queries[0]+=1
result={'variant':variant,'rows':n,'mode':mode,'history_per_supplier':history,'registry_rows':n if registry_rows else 0,'cycles':[]}
try:
    values=[];expected_ready=expected_events=0
    for i in range(n):
        code=str(i+1).zfill(8);manager='СТАРИЙ КЕРІВНИК' if mode=='managers' else ''
        supplier(con,code,active=True,manager=manager)
        if registry_rows:
            con.execute("""INSERT INTO supplier_registry_summary(supplier_code,supplier_name,
                qualifications_count,active_count,frameworks_count,refreshed_at) VALUES(?,'ПРИКЛАД',1,1,1,'fixture')""",(code,))
        if mode=='managers':
            con.execute("""INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,
                is_current,source,created_at,updated_at) VALUES(?,?,?,1,'ЄДР','2026-09-01','2026-09-01')""",
                (code,manager,server.normalize_manager_name(manager)))
        for h in range(history):
            con.execute("""INSERT INTO supplier_edr_verification_events(supplier_code,event_type,occurred_at,
                officer,source,snapshot_hash,snapshot_json,created_at) VALUES(?,'manual_edr',?,'Тестова УО SANDBOX',
                'synthetic history',?,'{"edr_status":"Зареєстровано"}','fixture')""",
                (code,f'2026-08-{h+1:02d}',code+'-history-'+str(h)))
        args={'manager':('НОВИЙ КЕРІВНИК' if i%2 else manager)} if mode=='managers' else {}
        if mode=='mixed':
            if i%5==0:args.update(checked='2026-09-02T00:00:00+03:00',status='Припинено')
            elif i%5==1:args.update(checked='bad')
            elif i%5==2:args.update(checked='')
            elif i%5==3:args.update(checked='2026-09-02T00:00:00+03:00')
        values.append(row(code,**args))
        expected_ready+=int(mode!='mixed' or i%5 in {3,4})
        expected_events+=int(mode!='mixed' or i%5==4)
    if nazk_rows:
        con.executemany("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES(?,?,'{}')",
            ((f'V311-SYNTH-{i:06d}',f'V311 SYNTHETIC PERSON {i:06d}') for i in range(nazk_rows)))
        result['nazk_registry_rows']=nazk_rows
    con.commit();source=snapshot(*values);del values
    gc.collect();result['fixture_rss_mib']=round(rss()/2**20,2)
    con.set_trace_callback(trace)
    for cycle in range(3):
        queries[0]=0;t=time.perf_counter();plan=sync.build_preview(con,source,sandbox_mode=True)
        core=time.perf_counter()-t
        details=server.supplier_edr_localize_review_details(sandbox_edr_review.details(plan))
        response={'summary':{**plan['summary'],**sandbox_edr_review.summary_additions(plan,details)},
            'state_digest':sync.preview_state_digest(plan),'details':details}
        serialized=json.dumps(response,ensure_ascii=False)
        xlsx=server.supplier_edr_conflict_xlsx(plan) if plan['conflicts'] else b''
        result['cycles'].append({'seconds':round(time.perf_counter()-t,3),'core_seconds':round(core,3),
            'details':len(details),'response_bytes':len(serialized.encode('utf-8')),'xlsx_bytes':len(xlsx),'selects_pragmas':queries[0],
            'ready':plan['summary']['eligible'],'conflicts':len(plan['conflicts']),
            'rss_mib':round(rss()/2**20,2)})
        del plan,details,response,serialized,xlsx;gc.collect()
    for label in ('actual_update','repeat_noop'):
        queries[0]=0;t=time.perf_counter()
        con.execute('BEGIN IMMEDIATE')
        callbacks={}
        if mode=='managers':
            import edr_sync_identity
            functions={k:getattr(server,v) for k,v in {
                'sync_manager':'sync_current_supplier_manager',
                'enrich_manager':'enrich_current_supplier_manager',
                'establish_manager':'establish_current_supplier_manager',
                'reestablish_manager':'reestablish_current_supplier_manager',
                'refresh_manager_controls':'refresh_current_submission_nazk_controls'}.items()}
            functions['reconcile_manager_nazk']=(server.reconcile_supplier_nazk_after_edr_manager_change
                if baseline else server.make_edr_apply_nazk_reconciler())
            callbacks = (functions if baseline else edr_sync_identity.callbacks(con,functions) if hasattr(edr_sync_identity,'callbacks') else {k:edr_sync_identity.callback(v) for k,v in functions.items()})
        counts=sync.apply(con,source,source['source_fingerprint'],confirmed=True,actor='synthetic-load',
            synced_at='2026-11-26T12:00:00+02:00',sandbox_mode=True,**callbacks)
        con.commit()
        result[label]={'seconds':round(time.perf_counter()-t,3),'selects_pragmas':queries[0],
            'inserted':counts['inserted'],'updated_profiles':counts['updated_profiles'],
            'verification_events':counts['verification_events'],'received_suppliers':counts['received_suppliers'],
            'business_updated_profiles':counts.get('business_updated_profiles'),
            'ready_unchanged':counts.get('ready_unchanged')}
        assert counts['received_suppliers']==expected_ready and counts['errors']==0
    assert con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0]==n*history+expected_events
    assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    con.set_trace_callback(None)
    readers=int(os.environ.get('PQM_V311_CONCURRENT_READS','0'))
    if readers:
        from concurrent.futures import ThreadPoolExecutor
        barrier=threading.Barrier(readers)
        def read_parallel(index):
            connection=server.db();count=[0]
            connection.set_trace_callback(lambda sql:count.__setitem__(0,count[0]+int(sql.lstrip().upper().startswith(('SELECT','WITH','PRAGMA')))))
            try:
                barrier.wait(timeout=30);started=time.perf_counter()
                plan=sync.build_preview(connection,source,sandbox_mode=True)
                details=server.supplier_edr_localize_review_details(sandbox_edr_review.details(plan))
                digest=sync.preview_state_digest(plan)
                payload=json.dumps({'summary':plan['summary'],'details':details,'state_digest':digest},ensure_ascii=False)
                return {'seconds':round(time.perf_counter()-started,3),'selects_pragmas':count[0],
                    'json_bytes':len(payload.encode('utf-8')),'digest':digest,'items':len(plan['items'])}
            finally:connection.close()
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=readers) as pool:parallel=list(pool.map(read_parallel,range(readers)))
        assert len({r['digest'] for r in parallel})==1 and all(r['items']==n for r in parallel)
        result['concurrent_reads']={'readers':readers,'wall_seconds':round(time.perf_counter()-started,3),'results':parallel}
    con.close();gc.collect()
    active=0
    for obj in gc.get_objects():
        if isinstance(obj,sqlite3.Connection):
            try:obj.execute('SELECT 1');active+=1
            except sqlite3.ProgrammingError:pass
    result['open_sqlite_connections_after']=active
    result['retained_rss_mib']=round(rss()/2**20,2)
finally:
    stop.set();thread.join();con.close();DATA.cleanup()
result['peak_rss_mib']=round(peak[0]/2**20,2)
name=os.environ.get('PQM_V311_RESULT') or ('V311_measure_baseline.json' if baseline else 'V311_measure_candidate.json')
(target/name).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
