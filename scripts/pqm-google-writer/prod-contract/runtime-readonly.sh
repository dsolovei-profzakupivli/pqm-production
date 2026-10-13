python3 -B - <<'PY'
import os,json,sqlite3
from pathlib import Path
assert os.getenv('RENDER_SERVICE_ID')=='srv-da7vmitg1s2s73fim0p0','STOP: service'
assert os.getenv('PQM_SANDBOX','').lower() not in ('1','true'),'STOP: SANDBOX'
assert os.getenv('RENDER_GIT_COMMIT')=='ec1147a26bdbe264e65cd31d8960e8980a1872af','STOP: changed PROD SHA'
p=Path(os.environ['PQM_DB_PATH']).resolve(strict=True)
assert p==Path('/var/data/pqm_test_20260831.sqlite3'),'STOP: DB path'
c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5)
c.row_factory=sqlite3.Row
try:
 c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
 tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 def query(sql):return [dict(r) for r in c.execute(sql)]
 flags={k:os.getenv(k) for k in ('PQM_ENV','PQM_SAFE_MODE','PQM_ENABLE_GOOGLE','PQM_SANDBOX_EDR_GOOGLE')}
 override=query("SELECT enabled,updated_at FROM runtime_feature_settings WHERE feature_key='google_integration'") if 'runtime_feature_settings' in tables else []
 env=os.getenv('PQM_ENABLE_GOOGLE')
 default=os.getenv('PQM_ENV','').lower() not in ('test','test_web','web','production')
 configured=bool(override[0]['enabled']) if override else (env.lower() in ('1','true','yes','on') if env is not None else default)
 safe=os.getenv('PQM_SAFE_MODE','').lower() in ('1','true','yes','on')
 ledger='supplier_edr_verification_events' in tables
 coverage=query('''SELECT COUNT(*) profiles,
 SUM(CASE WHEN TRIM(COALESCE(edr_checked_at,''))<>'' THEN 1 ELSE 0 END) dated_profiles,
 SUM(CASE WHEN TRIM(COALESCE(edr_checked_at,''))<>'' AND EXISTS
 (SELECT 1 FROM supplier_edr_verification_events e WHERE e.supplier_code=p.supplier_code
 AND e.event_type IN ('google_clarity','google_clarity_profile','legacy_google_registry')
 AND e.occurred_at=p.edr_checked_at) THEN 1 ELSE 0 END) exact_matching_dated_profiles
 FROM supplier_edr_profiles p''') if ledger and 'supplier_edr_profiles' in tables else 'NOT_VERIFIED'
 events=query('SELECT event_type,COUNT(*) events,COUNT(DISTINCT supplier_code) suppliers,MAX(created_at) last_created_at FROM supplier_edr_verification_events GROUP BY event_type') if ledger else []
 dup=c.execute('SELECT COUNT(*) FROM (SELECT 1 FROM supplier_edr_verification_events GROUP BY supplier_code,event_type,occurred_at,source,snapshot_hash HAVING COUNT(*)>1)').fetchone()[0] if ledger else 'NOT_VERIFIED'
 runs=query("SELECT started_at,finished_at,status,processed,inserted,updated,CASE WHEN COALESCE(error,'')<>'' THEN 1 ELSE 0 END has_error FROM supplier_edr_sync_log ORDER BY id DESC LIMIT 5") if 'supplier_edr_sync_log' in tables else []
 print(json.dumps({'DEPLOYED_SHA':os.getenv('RENDER_GIT_COMMIT'),'FLAGS':flags,
 'GOOGLE_CONFIGURED_ENABLED':configured,'GOOGLE_EFFECTIVE_ENABLED_FROM_PERSISTED_POLICY':configured and not safe,
 'GOOGLE_SETTING_OVERRIDE':override,'LEDGER_COVERAGE':coverage,'EVENT_COUNTS':events,
 'DUPLICATE_LEDGER_IDENTITIES':dup,'LAST_SYNC_RESULTS':runs,
 'PROCESS_SYNC_RUNNING':'NOT_VERIFIED_FROM_SEPARATE_SHELL','DB_WRITES':0},ensure_ascii=False,indent=2))
finally:c.close()
PY
