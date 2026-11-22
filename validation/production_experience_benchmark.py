"""Same 10,240 synthetic search admissions: baseline vs bounded queue sizes."""
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from validation.production_memory_benchmark import rss
import runtime_experience

def run(limit):
    executor=ThreadPoolExecutor(max_workers=2)
    counts=Counter();timings=[];starts={};lock=threading.Lock();active=peak_active=0
    pending=set();pending_lock=threading.Lock()
    def work(sid):
        nonlocal active,peak_active
        with lock:active+=1;peak_active=max(peak_active,active)
        time.sleep(.0005)  # Synthetic upstream latency; not a prediction for Prozorro.
        with lock:
            counts[sid]+=1;timings.append((time.perf_counter()-starts.pop(sid))*1000);active-=1
    if limit:
        queue=runtime_experience.ExperienceQueue(executor,work,limit=limit,batch=32,pending=pending)
        enqueue=queue.enqueue
    else:
        queue=None
        with zipfile.ZipFile(ROOT/'validation/fixtures/production_memory_parent_a53234f.zip') as archive:
            source=archive.read('server.py').decode('utf-8-sig')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='enqueue_contract_experience_search')
        def batch(ids):
            try:
                for sid in ids:work(sid)
            finally:
                with pending_lock:pending.difference_update(ids)
        namespace=dict(SANDBOX_MODE=False,CONTRACT_EXPERIENCE_PENDING=pending,
                       CONTRACT_EXPERIENCE_PENDING_LOCK=pending_lock,
                       CONTRACT_EXPERIENCE_EXECUTOR=executor,contract_experience_worker=batch)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<pinned-baseline-enqueue>','exec'),namespace)
        enqueue=namespace['enqueue_contract_experience_search']
    gc.collect();before=rss();samples=[];stop=threading.Event()
    def monitor():
        while not stop.is_set():
            samples.append((len(pending),rss()['rss_bytes']))
            stop.wait(.005)
    monitor_thread=threading.Thread(target=monitor);monitor_thread.start()
    producer_seconds=[]
    def producer(n):
        begin=time.perf_counter()
        for batch in range(40):
            ids=[f'{n}:{batch}:{i}' for i in range(64)]
            with lock:
                now=time.perf_counter()
                starts.update((sid,now) for sid in ids)
            enqueue(ids)
        producer_seconds.append(time.perf_counter()-begin)
    begin=time.perf_counter()
    producers=[threading.Thread(target=producer,args=(n,)) for n in range(4)]
    for thread in producers:thread.start()
    for thread in producers:
        thread.join(60)
        if thread.is_alive():raise AssertionError('Producer starvation')
    deadline=time.monotonic()+60
    while pending:
        if time.monotonic()>deadline:raise AssertionError('Work did not drain')
        time.sleep(.005)
    seconds=time.perf_counter()-begin
    state=queue.snapshot() if queue else {'owned':len(pending)}
    if queue:queue.close()
    executor.shutdown(wait=True);stop.set();monitor_thread.join()
    assert len(counts)==10240 and set(counts.values())=={1}
    return dict(limit=limit,rows=len(counts),peak_active=peak_active,queue=state,
                pending_peak=max(n for n,_ in samples),peak_rss_delta=max(n for _,n in samples)-before['rss_bytes'],
                after_rss_delta=rss()['rss_bytes']-before['rss_bytes'],seconds=seconds,
                throughput=len(counts)/seconds,producer_seconds=producer_seconds,
                latency_ms={'p50':statistics.median(timings),'p95':sorted(timings)[int(len(timings)*.95)-1]},
                limitations='Real executor and baseline admission. Synthetic 0.5ms search; no DB or HTTP. Equal per-ID validation/latency instrumentation in both variants.')

if __name__=='__main__':
    if len(sys.argv)>1:print(json.dumps(run(int(sys.argv[1]))))
    else:
        results=[json.loads(subprocess.check_output([sys.executable,'-B',__file__,str(limit)],text=True))
                 for repeat in range(3) for limit in [0,64,128,256]]
        (ROOT/'evidence/QUEUE_BENCHMARK.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(json.dumps(results,indent=2))
