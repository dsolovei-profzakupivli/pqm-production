"""Fail-closed V31/V31.1 test-only bridge. No runtime imports or Git dependency."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pins
from routing import CONTRACT, ENTRYPOINTS, MODULES, SUPERSEDED, V31_INFRASTRUCTURE_CONTRACT

ROOT = HERE.parents[1]
ARCHIVE = 'validation/v31_1/baseline_v31.zip'
INVENTORY = 'validation/v31_1/bridge_manifest.json'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def relative(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise RuntimeError('Unsafe package path')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')) or ':' in name:
        raise RuntimeError('Unsafe package path: ' + name)
    return name

def validate_paths(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and temporary destination must be disjoint')
    return source, target

def safe_source(root, name):
    name = relative(name)
    p = Path(root)/name
    if Path(root).resolve() not in p.resolve().parents or p.is_symlink() or not p.is_file():
        raise RuntimeError('Missing or unsafe package dependency: ' + name)
    return p

def inventory(root):
    raw = safe_source(root, INVENTORY).read_bytes().replace(b'\r\n', b'\n')
    if sha(raw) != pins.INVENTORY_SHA256:
        raise RuntimeError('V31.1 inventory SHA mismatch')
    result = json.loads(raw)
    if result.get('contract') != CONTRACT:
        raise RuntimeError('Unknown package contract')
    for key in ('staging_files', 'bridge_files'):
        values = result[key]
        if not values or len(values) != len(set(values)):
            raise RuntimeError('Invalid package inventory')
        for name in values: relative(name)
    return result

def validate_current(root, contract=CONTRACT):
    if contract != CONTRACT:
        raise RuntimeError('Unknown current contract: ' + str(contract))
    raw = safe_source(root, 'validation/v31_1/contract.json').read_bytes().replace(b'\r\n', b'\n')
    if sha(raw) != pins.CONTRACT_SHA256:
        raise RuntimeError('V31.1 runtime contract SHA mismatch')
    result = json.loads(raw)
    if len(result['runtime_lf_sha256']) != 9:
        raise RuntimeError('Incomplete V31.1 runtime contract')
    for name, expected in result['runtime_lf_sha256'].items():
        if sha(safe_source(root, name).read_bytes().replace(b'\r\n', b'\n')) != expected:
            raise RuntimeError('Current V31.1 runtime SHA mismatch: ' + name)
    package = inventory(root)
    for name, expected in package['test_lf_sha256'].items():
        if sha(safe_source(root, name).read_bytes().replace(b'\r\n', b'\n')) != expected:
            raise RuntimeError('V31.1 test infrastructure SHA mismatch: ' + name)
    for name in package['staging_files'] + package['bridge_files']:
        safe_source(root, name)
    return package

def validate_snapshot(root):
    archive = safe_source(root, ARCHIVE)
    if sha(archive.read_bytes()) != pins.ARCHIVE_SHA256:
        raise RuntimeError('V31 snapshot archive SHA mismatch')
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or len(names) > 5000:
            raise RuntimeError('Duplicate or excessive snapshot members')
        if sum(i.file_size for i in infos) > 512*1024*1024:
            raise RuntimeError('Excessive snapshot expansion')
        for i in infos:
            relative(i.filename)
            if i.is_dir() or i.flag_bits & 1 or stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG):
                raise RuntimeError('Unsafe snapshot member')
        index = json.loads(z.read('V31_SNAPSHOT_INDEX.json'))
        if (index.get('commit') != pins.BASELINE or index.get('tree') != pins.BASELINE_TREE
                or z.comment.decode() != pins.BASELINE):
            raise RuntimeError('Wrong V31 snapshot identity')
        external=set(index.get('external',[]))
        if not external.issubset(index['files']):raise RuntimeError('Unknown external snapshot member')
        if set(names) != {'V31_SNAPSHOT_INDEX.json', *(set(index['files'])-external)}:
            raise RuntimeError('Wrong V31 snapshot membership')
        for name, expected in index['files'].items():
            relative(name)
            content=safe_source(root,name).read_bytes() if name in external else z.read(name)
            if sha(content) != expected:
                raise RuntimeError('V31 snapshot member SHA mismatch: ' + name)
    return index

def temporary_base(root):
    """Use an explicitly supplied isolated local temp root when configured."""
    configured=os.environ.get('PQM_V311_TEMP_ROOT')
    base=Path(configured).expanduser().resolve() if configured else Path(tempfile.gettempdir()).resolve()
    root=Path(root).resolve()
    if not base.is_dir():raise RuntimeError('V31.1 temporary root must already exist')
    if base==root or root in base.parents or base in root.parents:
        raise RuntimeError('V31.1 temporary root must be outside and disjoint from the source tree')
    return base

def preflight(root, entrypoint='local', contract=CONTRACT):
    root = Path(root).resolve()
    if entrypoint not in ENTRYPOINTS:
        raise RuntimeError('Unknown Gate entrypoint')
    package = validate_current(root, contract)
    validate_snapshot(root)
    temp = temporary_base(root)
    if shutil.disk_usage(temp).free < 1024**3:
        raise RuntimeError('Insufficient temporary disk space (minimum 1 GiB)')
    return package

@contextmanager
def temporary(root, prefix='pqm-v311-bridge-'):
    base = temporary_base(root)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=base) as folder:
        validate_paths(root, folder)
        yield Path(folder)

def copy_files(root, target, names):
    root, target = validate_paths(root, target)
    for name in sorted(set(names)):
        source = safe_source(root, name)
        dest = target/relative(name)
        if target not in dest.resolve().parents:
            raise RuntimeError('Unsafe staging destination')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)

def references(root, target):
    with zipfile.ZipFile(safe_source(root, ARCHIVE)) as z:
        for name in ('server.py', 'edr_sync_v2.py', 'operational_tasks.py', 'sandbox_edr_review.py', 'nazk_workflow.py'):
            file = Path(target)/'validation/v31_1'/('reference_server.txt' if name=='server.py' else 'reference_'+name+'.txt')
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(z.read(name))

def extract_snapshot(root,target):
    validate_paths(root,target)
    index=validate_snapshot(root)
    with zipfile.ZipFile(safe_source(root,ARCHIVE)) as z:
        for name in index['files']:
            dest=Path(target)/relative(name)
            if Path(target).resolve() not in dest.resolve().parents:raise RuntimeError('Unsafe snapshot destination')
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(safe_source(root,name).read_bytes() if name in index.get('external',[]) else z.read(name))

@contextmanager
def historical_source(root):
    """Pinned data for old source contracts; loaded functional modules stay current."""
    preflight(root)
    with temporary(root) as folder:
        target=folder/'v31';target.mkdir();extract_snapshot(root,target)
        yield target

def stage(root, target, *, baseline=False):
    root, target = validate_paths(root, target)
    package = preflight(root)
    if baseline:
        extract_snapshot(root,target)
        # New test harness only; no historical file or assertion is overwritten.
        copy_files(root, target, package['bridge_files'])
        copy_files(root, target, ('edr_monitoring_projection.py','edr_sync_comparison.py','edr_sync_identity.py'))
    else:
        copy_files(root, target, package['staging_files'] + package['bridge_files'])
    references(root, target)
    return len(package['staging_files'] + package['bridge_files'])

def child_environment(root, folder, evidence, baseline=False):
    allowed = ('PATH','SystemRoot','WINDIR','COMSPEC','TEMP','TMP','LOCALAPPDATA','HOME',
               'NODE_PATH','PQM_NODE','PQM_CHROMIUM','PLAYWRIGHT_BROWSERS_PATH')
    env = {k:os.environ[k] for k in allowed if k in os.environ}
    for key,value in os.environ.items():
        if (key.startswith('PQM_INTEGRATED_V') and key.endswith(('_SNAPSHOT_ARCHIVE','_SNAPSHOT_ARCHIVE_SHA256'))
                or key in {'PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE','PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE_SHA256'}
                or key.startswith('PQM_') and key.endswith('_EVIDENCE')):
            env[key]=value
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',
        PQM_V311_SOURCE_ROOT=str(root),PQM_V311_TEMP=str(folder),
        PQM_V311_EVIDENCE=str(evidence),PQM_V311_BASELINE='1' if baseline else '0')
    if os.environ.get('PQM_V311_TEMP_ROOT'):
        env['PQM_V311_TEMP_ROOT']=str(Path(os.environ['PQM_V311_TEMP_ROOT']).resolve())
    return env

def monitored_command(script):
    # Preserve the existing Release runner's thread-error contract in children.
    bootstrap = """import sys,runpy
from pathlib import Path
from validation.run_local_release import UnhandledThreadExceptionMonitor
monitor=UnhandledThreadExceptionMonitor();monitor.install();code=0
sys.argv=sys.argv[1:];sys.path.insert(0,str(Path(sys.argv[0]).resolve().parent))
try:
    try:runpy.run_path(sys.argv[0],run_name='__main__')
    except SystemExit as exc:
        code=exc.code if isinstance(exc.code,int) else 0 if exc.code is None else 1
finally:
    if not monitor.report():code=1
    monitor.restore()
raise SystemExit(code)
"""
    return [sys.executable,'-B','-X','utf8','-c',bootstrap,str(script)]

def run_script(root, script, *, baseline=False, evidence=None, extra=None):
    evidence = Path(evidence or Path(root)/'evidence').resolve();evidence.mkdir(parents=True,exist_ok=True)
    with temporary(root) as folder:
        target = folder/'runtime';target.mkdir();stage(root,target,baseline=baseline)
        env = child_environment(root,folder,evidence,baseline)
        if extra:env.update(extra)
        command=monitored_command(script)
        result=subprocess.run(command,cwd=target,env=env,check=False)
        if result.returncode:raise RuntimeError('V31.1 test phase failed: '+script)

def historical(root, evidence=None):
    validate_snapshot(root)
    with temporary(root) as folder:
        target=folder/'baseline';target.mkdir();stage(root,target,baseline=True)
        result=subprocess.run([sys.executable,'-B','-m','unittest','-v',
            'test_google_writer_integrated_candidate_integrity_v31',V31_INFRASTRUCTURE_CONTRACT],cwd=target,
            env=child_environment(root,folder,evidence or folder),check=False)
        if result.returncode:raise RuntimeError('Pinned V31 integrity failed')

def phase(root, name, entrypoint='local', evidence=None):
    preflight(root,entrypoint)
    if name=='check':return
    if name=='pin':return historical(root,evidence)
    if name=='python':
        for part in ('pin','superseded','unit','history','routing'):phase(root,part,entrypoint,evidence)
        return
    if name=='superseded':
        return run_script(root,'validation/v31_1/history_run.py',baseline=True,evidence=evidence,
            extra={'PQM_V311_SUPERSEDED_ONLY':'1'})
    scripts={'unit':'test_current.py','history':'history_run.py','browser':'browser.py',
             'routing':'test_bridge.py','profile':'profile_run.py','measure':'measure.py'}
    if name not in scripts:raise RuntimeError('Unknown V31.1 phase: '+str(name))
    return run_script(root,'validation/v31_1/'+scripts[name],evidence=evidence)

def legacy_entry(root, script, arguments):
    """Stage direct historical entrypoints before their unchanged copy helpers run."""
    root=Path(root).resolve();preflight(root)
    if script not in {'validation/document_release_history_v2.py','validation/csv_ui_gate_history.py'}:
        raise RuntimeError('Unknown legacy delegate')
    if not arguments:raise RuntimeError('No legacy test selection')
    token=os.environ.get('PQM_V311_INNER_LEGACY')
    if token is not None:
        expected=str(root)+'|'+script+'|'+pins.INVENTORY_SHA256
        if token!=expected or root.name!='runtime' or not root.parent.name.startswith('pqm-v311-bridge-'):
            raise RuntimeError('Invalid legacy staging ownership')
        staging_parent=Path(os.environ.get('PQM_V311_TEMP') or '').resolve()
        if not staging_parent.is_dir() or staging_parent not in root.parents:
            raise RuntimeError('Legacy delegate is outside owned temporary root')
        os.environ.pop('PQM_V311_INNER_LEGACY')
        return None
    with temporary(root) as folder:
        target=folder/'runtime';target.mkdir();stage(root,target)
        evidence=Path(os.environ.get('PQM_V311_EVIDENCE') or root/'evidence').resolve()
        env=child_environment(target,folder,evidence)
        # The delegated runtime tree is nested under this invocation's temp
        # folder. Give its child bridge a disjoint sibling temp root so the
        # recursive-copy guard remains active without rejecting our own stage.
        delegate_temp=folder.parent.parent/(folder.parent.name+'-delegate-temp')
        delegate_temp.mkdir(exist_ok=True)
        env['PQM_V311_TEMP_ROOT']=str(delegate_temp.resolve())
        env.update(PQM_ENV='test_web',PQM_SANDBOX='0',PQM_AUTH_ENABLED='0',PQM_USERS_JSON='',
            PQM_DATA_DIR=str(folder/'data'),PQM_DB_PATH=str(folder/'data/pqm_sandbox.sqlite3'),
            PQM_TEST_NETWORK_ISOLATION='1',PQM_RELEASE_SCHEMA_ONLY='1',
            PQM_DISABLE_BACKGROUND_JOBS='1',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_SCHEDULER='0',
            PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0')
        env['PYTHONPATH']=str(target/'validation/test_runtime')
        env['PQM_V311_INNER_LEGACY']=str(target)+'|'+script+'|'+pins.INVENTORY_SHA256
        result=subprocess.run([sys.executable,'-B',str(target/script),*arguments],cwd=target,env=env,check=False)
        if result.returncode:raise RuntimeError('Historical delegate test failed: '+script)
        return 0

def route_suite(suite, source, entrypoint='local', *, required=False):
    import unittest
    leaves=[]
    def visit(group):
        for item in group:
            if isinstance(item,unittest.TestSuite):visit(item)
            else:leaves.append(item)
    visit(suite)
    result=[];replaced=False
    for test in leaves:
        module=test.__class__.__module__.rsplit('.',1)[-1]
        if module in {*MODULES,'test_google_writer_integrated_candidate_integrity_v31'} or test.id().endswith(V31_INFRASTRUCTURE_CONTRACT):
            if not replaced:
                result.append(unittest.FunctionTestCase(lambda:phase(source,'python',entrypoint),
                    description='V31.1 exact version routing: current 41+120, historical pin+3, routing negatives'))
                replaced=True
        else:result.append(test)
    if required and not replaced:raise RuntimeError('Missing version-routed tests in full Release suite')
    return unittest.TestSuite(result)

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',choices=ENTRYPOINTS,required=True)
    parser.add_argument('--phase',choices=('check','pin','superseded','unit','history','browser','routing','python'),required=True)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--contract',default=CONTRACT)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args(argv)
    preflight(args.root,args.entrypoint,args.contract)
    phase(args.root,args.phase,args.entrypoint,args.evidence)
    print('V31.1 BRIDGE PASS:',args.entrypoint,args.phase,flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
