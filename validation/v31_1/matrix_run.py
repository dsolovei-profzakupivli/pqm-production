"""Sequential comparable load cases; only owned external temporary trees."""
import os,sys,tempfile,subprocess,zipfile,json
import hashlib
from pathlib import Path
from run_local import stage,ROOT,validate_paths

cases=[(100,'plain',0),(5000,'plain',0),(15227,'plain',0),(30000,'plain',0),
    (100,'plain',3),(5000,'plain',2),(100,'mixed',0),(5000,'mixed',0),(100,'managers',0)]
results=[]
selection=set(filter(None,os.environ.get('PQM_V311_MATRIX_CASES','').split(',')))
for n,mode,history in cases:
    if selection and f'{n}:{mode}:{history}' not in selection:continue
    for variant in os.environ.get('PQM_V311_MATRIX_VARIANTS','baseline,previous,optimized').split(','):
        with tempfile.TemporaryDirectory(prefix='pqm-v311-matrix-') as folder:
            target=Path(folder)/'runtime';target.mkdir();stage(target,baseline=variant=='baseline')
            if variant=='previous':
                with zipfile.ZipFile(ROOT/'evidence/V31_1_previous_candidate.zip') as archive:
                    for name in ('server.py','edr_sync_v2.py','sandbox_edr_review.py','operational_tasks.py',
                            'edr_monitoring_projection.py','edr_sync_comparison.py','edr_sync_identity.py'):
                        (target/name).write_bytes(archive.read(name))
            if variant=='previous':
                with zipfile.ZipFile(ROOT/'validation/v31_1/baseline_v31.zip') as pinned_baseline:
                    (target/'nazk_workflow.py').write_bytes(pinned_baseline.read('nazk_workflow.py'))
            suffix=('_registry' if os.environ.get('PQM_V311_REGISTRY_ROWS')=='1' else '')+('_concurrent' if os.environ.get('PQM_V311_CONCURRENT_READS') else '')
            name=f'V311_matrix_{n}_{mode}_{history}_{variant}{suffix}.json'
            pins={p:hashlib.sha256((target/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in (
                'server.py','edr_sync_v2.py','edr_sync_comparison.py','edr_monitoring_projection.py','edr_sync_identity.py','operational_tasks.py','sandbox_edr_review.py','nazk_workflow.py')}
            (ROOT/'evidence'/(name+'.runtime-sha256.json')).write_text(json.dumps(pins,indent=2))
            env={**os.environ,'PQM_V311_TEMP':folder,'PQM_V311_SOURCE_ROOT':str(ROOT),
                'PYTHONDONTWRITEBYTECODE':'1','PQM_V311_BASELINE':'1' if variant=='baseline' else '0',
                'PQM_V311_VARIANT':variant,'PQM_V311_ROWS':str(n),'PQM_V311_MODE':mode,
                'PQM_V311_HISTORY':str(history),'PQM_V311_RESULT':name}
            print('START',n,mode,history,variant,flush=True)
            r=subprocess.run([sys.executable,'-B','-X','utf8','validation/v31_1/measure.py'],cwd=target,env=env)
            results.append({'rows':n,'mode':mode,'history':history,'variant':variant,'exit_code':r.returncode})
            (ROOT/'evidence'/os.environ.get('PQM_V311_MATRIX_INDEX','V311_MATRIX_INDEX.json')).write_text(json.dumps(results,indent=2))
            if r.returncode:print('CASE FAILED; recorded, no automatic retry.',flush=True)
print('MATRIX COMPLETE',len(results),flush=True)
