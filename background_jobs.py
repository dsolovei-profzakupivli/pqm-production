"""Process execution interlock; never reads or changes persisted job settings."""
import os
from pathlib import Path


def _state_path():
    if os.environ.get('PQM_SANDBOX') != '1':
        return None
    data, db = os.environ.get('PQM_DATA_DIR'), os.environ.get('PQM_DB_PATH')
    if not data or not db:
        return None
    root=Path(data).resolve()
    if Path(db).resolve() != root/'pqm_sandbox.sqlite3':
        return None
    return root/'.pqm-background-jobs-disabled'


def status():
    locked=os.environ.get('PQM_DISABLE_BACKGROUND_JOBS', '').strip().lower() in {'1','true','yes','on'}
    try:path=_state_path()
    except (OSError,RuntimeError,ValueError):
        return {'disabled':True,'environment_locked':locked,'persisted':False,'can_disable':False,'state_error':True}
    persisted=False
    if path is not None:
        try:
            path.lstat()  # Presence is the interlock; never follow/read a link.
            persisted=True
        except FileNotFoundError:
            pass
        except OSError:
            persisted=True  # Uncertain state fails closed.
    return {'disabled':locked or persisted,'environment_locked':locked,
            'persisted':persisted,'can_disable':path is not None and not (locked or persisted)}


def disable_sandbox():
    if os.environ.get('PQM_SANDBOX') != '1':
        raise PermissionError('SANDBOX only')
    import sandbox_runtime
    sandbox_runtime.attest_internal_target(Path(os.environ['PQM_DB_PATH']),require_operational=False)
    path=_state_path()
    if path is None:
        raise PermissionError('SANDBOX persistent storage is not attested')
    # Atomic, monotonic publication: even an empty marker blocks every process.
    # No overwrite, migration, job setting update or deletion is performed.
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        return status()
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name!='nt':
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    return status()


def disabled():
    return status()['disabled']
