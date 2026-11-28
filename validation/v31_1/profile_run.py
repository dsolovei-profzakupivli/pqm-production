import cProfile,os,pstats,json,gc
from pathlib import Path
from fixtures import reset,supplier,row,snapshot,sync,server,DATA
import sandbox_edr_review
con=reset()
try:
    n=int(os.environ.get('PQM_V311_ROWS','15227'))
    for i in range(n):supplier(con,str(i+1).zfill(8),active=True)
    con.commit();source=snapshot(*(row(str(i+1).zfill(8)) for i in range(n)))
    def work():
        p=sync.build_preview(con,source,sandbox_mode=True)
        d=sandbox_edr_review.details(p)
        return json.dumps({'summary':p['summary'],'details':d,'state_digest':sync.preview_state_digest(p)},ensure_ascii=False)
    label=os.environ.get('PQM_V311_PROFILE_LABEL') or ('baseline' if os.environ['PQM_V311_BASELINE']=='1' else 'candidate')
    out=Path(os.environ['PQM_V311_SOURCE_ROOT'])/'evidence'
    profiler=cProfile.Profile();profiler.runcall(work)
    profiler.dump_stats(str(out/('V311_profile_'+label+'.prof')))
    with (out/('V311_profile_'+label+'.txt')).open('w',encoding='utf-8') as f:
        pstats.Stats(profiler,stream=f).strip_dirs().sort_stats('cumulative').print_stats(55)
        pstats.Stats(profiler,stream=f).strip_dirs().sort_stats('tottime').print_stats(30)
    print('PROFILE',label,'complete',flush=True)
finally:con.close();gc.collect();DATA.cleanup()
