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
  for item in seed['icons']:
   parsed=navigation_settings.stored_icon(item)
   old=con.execute('SELECT name,svg FROM navigation_icons WHERE icon_key=?',(item['icon_key'],)).fetchone()
   if old is None or tuple(old)!=(item['name'],item['svg']):
    con.execute('INSERT INTO navigation_icons(icon_key,name,svg,updated_at,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(icon_key) DO UPDATE SET name=excluded.name,svg=excluded.svg,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(item['icon_key'],item['name'],item['svg'],'2026-09-10','release seed'))
  navigation_settings.validate(seed['navigation'],navigation_settings.ICON_KEYS|{r[0] for r in con.execute('SELECT icon_key FROM navigation_icons')})
  encoded=json.dumps(seed['navigation'],ensure_ascii=False,separators=(',',':'))
  current=con.execute('SELECT overrides_json FROM navigation_settings WHERE id=1').fetchone()
  if current is None or json.loads(current[0])!=seed['navigation']:
   con.execute('INSERT INTO navigation_settings(id,overrides_json,updated_at,updated_by) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET overrides_json=excluded.overrides_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(encoded,'2026-09-10','release seed'))
 integrity=[r[0] for r in con.execute('PRAGMA integrity_check')]
 violations=con.execute('PRAGMA foreign_key_check').fetchall()
 if integrity!=['ok'] or violations:raise RuntimeError('SQLite validation failed; stop deployment and inspect backup')
print('Additive schema / selected presentation seeds: OK; SQLite integrity OK; FK=0')
