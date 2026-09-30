"""Additive schema and explicit presentation-only seed installation."""
import argparse,json,os,sqlite3,sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--db',required=True)
parser.add_argument('--apply-navigation',action='store_true',help='Apply authoritative LOCAL presentation settings')
args=parser.parse_args()
path=Path(args.db).resolve()
if not path.is_file():raise SystemExit('Existing WEB database required; restore/create separately')
os.environ.update(PQM_DB_PATH=str(path),PQM_DATA_DIR=str(path.parent),PQM_RELEASE_SCHEMA_ONLY='1',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0',PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_BIDS_UPDATE='0',PQM_BIDS_MODE='disabled',PQM_ENABLE_BROWSER='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_POWERBI='0')
import server,navigation_settings,scheduler_runtime
server.init_db()
server.init_reference_tables(path)
with sqlite3.connect(path) as con:
 scheduler_runtime.migrate(con)
 con.row_factory=sqlite3.Row
 con.execute('PRAGMA foreign_keys=ON')
 if args.apply_navigation:
  seed=json.loads((Path(__file__).parent/'config/navigation.release.json').read_text(encoding='utf-8'))
  navigation_settings.install_release_seed(con,seed,preserve_existing=server.SANDBOX_MODE)
 integrity=[r[0] for r in con.execute('PRAGMA integrity_check')]
 violations=con.execute('PRAGMA foreign_key_check').fetchall()
 if integrity!=['ok'] or violations:raise RuntimeError('SQLite validation failed; stop deployment and inspect backup')
print('Additive schema / selected presentation seeds: OK; SQLite integrity OK; FK=0')
