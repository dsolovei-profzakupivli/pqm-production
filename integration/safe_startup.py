"""Call from MERGED WEB startup instead of blindly invoking LOCAL init_db(). No writes."""
import importlib.util,json,sqlite3
from pathlib import Path
from contextlib import contextmanager, closing

@contextmanager
def database(*args, **kwargs):
    with closing(sqlite3.connect(*args, **kwargs)) as con:
        with con:
            yield con


def require_current_schema(db_path, package_root):
    root=Path(package_root)
    spec=importlib.util.spec_from_file_location('pqm_additive',root/'migrations/additive.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=json.loads((root/'migrations/target_schema.json').read_text(encoding='utf-8'))
    path=Path(db_path).resolve()
    if not path.is_file():raise RuntimeError('Existing persistent WEB database missing. STOP.')
    with database(path.as_uri()+'?mode=ro',uri=True) as con:
        steps,blockers=module.plan(con,target)
    if steps or blockers:raise RuntimeError('Run reviewed offline additive migration first; startup cannot repair WEB data.')
