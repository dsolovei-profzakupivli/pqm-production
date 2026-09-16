"""Isolated, fail-closed first sandbox release. Never bootstrap a working WEB DB.

Render Docker command: python sandbox_runtime.py
Only the new pqm-sandbox service is accepted. The first release is read-only
safe mode; changing that policy requires a reviewed code change, not a UI toggle.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
POLICY = {
    'PQM_SANDBOX': '1', 'PQM_ENV': 'test_web', 'PQM_SAFE_MODE': '1',
    'PQM_AUTH_ENABLED': '1', 'PQM_LOCAL_ROLE_IMPERSONATION': '0',
    'PQM_RELEASE_SCHEMA_ONLY': '1', 'PQM_ENABLE_BROWSER': '0',
    'PQM_ENABLE_SCHEDULER': '0', 'PQM_ENABLE_PROZORRO_SCHEDULER': '0',
    'PQM_ENABLE_VIOLATION_SCHEDULER': '0', 'PQM_ENABLE_NAZK_SCHEDULER': '0',
    'PQM_ENABLE_NAZK_WORKFLOW': '0', 'PQM_ENABLE_GOOGLE': '0',
    'PQM_ENABLE_BIDS_UPDATE': '0', 'PQM_ENABLE_POWERBI': '0',
    'PQM_BIDS_MODE': 'disabled',
}
ACCESS_FILE = '.sandbox-initial-access.json'
_guard_installed = False


def validate_environment(env=None):
    env = os.environ if env is None else env
    for key, expected in POLICY.items():
        if env.get(key) != expected:
            raise RuntimeError(f'STOP: sandbox policy requires {key}={expected}')
    data = Path(env.get('PQM_DATA_DIR', '')).resolve()
    db = Path(env.get('PQM_DB_PATH', '')).resolve()
    if db != data / 'pqm_sandbox.sqlite3' or Path(env['PQM_DB_PATH']).is_symlink():
        raise RuntimeError('STOP: sandbox database path mismatch')
    service = env.get('RENDER_SERVICE_ID', '')
    if service:
        if (env.get('RENDER_SERVICE_NAME') != 'pqm-sandbox'
                or service == 'srv-da7vmitg1s2s73fim0p0' or data != Path('/var/data').resolve()):
            raise RuntimeError('STOP: wrong Render service or disk path')
    elif not (env.get('PQM_SANDBOX_LOCAL_FIXTURE') == '1'
              and data.is_relative_to(Path(tempfile.gettempdir()).resolve())
              and data != Path(tempfile.gettempdir()).resolve()):
        raise RuntimeError('STOP: Render sandbox identity or isolated local fixture required')
    for key, child in [('PQM_PROTOCOLS_DIR', 'protocols'), ('PQM_CACHE_DIR', 'cache'),
                       ('PQM_LOG_DIR', 'logs')]:
        if env.get(key) and Path(env[key]).resolve() != data / child:
            raise RuntimeError(f'STOP: sandbox path mismatch: {key}')
    forbidden = {'PQM_USERS_JSON', 'PQM_SUPPLIER_REGISTRY_TOKEN'}
    if any(value for key, value in env.items()
           if key in forbidden or key.startswith('PQM_GOOGLE_OAUTH_')):
        raise RuntimeError('STOP: no inherited accounts, OAuth or integration credentials allowed')
    if (data / 'google_oauth').exists() and any((data / 'google_oauth').iterdir()):
        raise RuntimeError('STOP: sandbox must not contain OAuth files')
    return data, db, service or 'local-synthetic-fixture'


def outbound_audit(event, args):
    # Defense in depth for this Python process. This is not an OS firewall.
    loopback = {'localhost', '127.0.0.1', '::1'}
    if event in {'socket.connect', 'socket.sendto'}:
        address = args[1] if event == 'socket.connect' else args[-1]
        if not isinstance(address, tuple) or address[0] not in loopback:
            raise RuntimeError('Sandbox outbound network is disabled')
    if event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'} and args[0] not in loopback:
        raise RuntimeError('Sandbox external DNS is disabled')
    if event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        raise RuntimeError('Sandbox safe smoke does not launch child processes')


def install_outbound_guard():
    global _guard_installed
    if not _guard_installed:
        socket.getfqdn = lambda name='': name or 'localhost'
        sys.addaudithook(outbound_audit)
        _guard_installed = True


def _verify_existing(db, service):
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as con:
        con.execute('PRAGMA query_only=ON')
        try:
            identity = con.execute('SELECT environment,service_id FROM sandbox_deployment_identity').fetchall()
        except sqlite3.OperationalError as exc:
            raise RuntimeError('STOP: existing database has no sandbox ownership marker') from exc
        if identity != [('sandbox', service)]:
            raise RuntimeError('STOP: sandbox database belongs to another environment/service')
        if con.execute('SELECT COUNT(*) FROM scheduler_job_settings WHERE enabled<>0').fetchone()[0]:
            raise RuntimeError('STOP: sandbox contains enabled scheduler settings')
        if con.execute('SELECT COUNT(*) FROM runtime_feature_settings WHERE enabled<>0').fetchone()[0]:
            raise RuntimeError('STOP: sandbox contains enabled runtime integrations')
        if not con.execute("SELECT 1 FROM auth_users WHERE role='admin' AND active=1").fetchone():
            raise RuntimeError('STOP: sandbox has no active administrator; do not reset accounts')


def bootstrap(server):
    """Create only an absent sandbox DB; repeat startup is a read-only ownership check."""
    data, db, service = validate_environment()
    if os.environ.get('RENDER_SERVICE_ID') and not os.path.ismount(data):
        raise RuntimeError('STOP: persistent sandbox disk is not mounted')
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if db.exists():
        _verify_existing(db, service)
        return {'created': False, 'fixture_applications': 0, 'credentials_written': False}
    # Never reuse an imported DB, a partial init or an old credential delivery.
    if any(p.name != 'lost+found' for p in data.iterdir()):
        raise RuntimeError('STOP: bootstrap requires a new empty sandbox disk')
    previous_db = server.DB_PATH
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    accounts = [('sandbox.admin', 'admin', None), ('sandbox.officer', 'officer', 1),
                ('sandbox.viewer', 'viewer', None)]
    access = {name: secrets.token_urlsafe(24) for name, _, _ in accounts}
    with tempfile.TemporaryDirectory(prefix='.pqm-sandbox-bootstrap-', dir=data) as temp:
        stage = Path(temp)
        stage_db = stage / 'new.sqlite3'
        try:
            server.DB_PATH = stage_db
            server.init_db()
            server.init_reference_tables(stage_db)
            from migrations.additive import plan, verify
            target = json.loads((ROOT / 'migrations/target_schema.json').read_text())
            with server.db() as con:
                steps, blockers = plan(con, target)
                if blockers:
                    raise RuntimeError('STOP: incompatible sandbox schema')
                for sql in steps:
                    con.execute(sql)
                con.execute('CREATE TABLE sandbox_deployment_identity (environment TEXT NOT NULL, service_id TEXT NOT NULL, created_at TEXT NOT NULL)')
                con.execute('INSERT INTO sandbox_deployment_identity VALUES (?,?,?)', ('sandbox', service, stamp))
                con.execute('INSERT INTO authorized_officers(id,full_name,role,active,created_at,updated_at) VALUES (1,?,?,1,?,?)',
                            ('Тестова УО SANDBOX', 'УО', stamp, stamp))
                for name, role, officer in accounts:
                    con.execute('INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by) VALUES (?,?,?,?,1,?,?,?)',
                                (name, server.hash_password(access[name]), role, officer, stamp, stamp, 'sandbox bootstrap'))
                for key in server.SCHEDULER_TARGETS:
                    server.scheduler_runtime.save_enabled(con, key, False, 'sandbox bootstrap')
                con.execute("INSERT INTO frameworks(id,pretty_id,dk_code,raw_json,synced_at) VALUES ('sandbox-framework','SANDBOX-TEST-ONLY','00000000-0','{}',?)", (stamp,))
                con.execute("INSERT INTO framework_officers(framework_id,officer,synced_at) VALUES ('sandbox-framework','Тестова УО SANDBOX',?)", (stamp,))
                for name, status in [('pending', 'pending'), ('admitted', 'active'), ('rejected', 'unsuccessful')]:
                    sid, qid = 'sandbox-' + name, 'sandbox-q-' + name
                    con.execute('INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES (?,?,?,?,?,?,?,?)',
                                (sid, 'sandbox-framework', 'СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК — НЕ РОБОЧІ ДАНІ', '00000000', stamp, qid, '{}', stamp))
                    con.execute('INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,?,?,?,?,?)',
                                (qid, 'sandbox-framework', sid, status, '{}', stamp))
                    con.execute('INSERT INTO application_fields(submission_id,protocol_officer) VALUES (?,?)', (sid, 'Тестова УО SANDBOX'))
                verify(con)
            con.close()
            # Consolidate only our disposable new DB before publishing it.
            with sqlite3.connect(stage_db) as con:
                con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                con.execute('PRAGMA journal_mode=DELETE')
            con.close()
            _verify_existing(stage_db, service)
            secret = stage / ACCESS_FILE
            fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'scope': 'pqm-sandbox only', 'created_at': stamp, 'accounts': access}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            # Link is exclusive (unlike rename/replace), so an existing target cannot be overwritten.
            shutil.copytree(ROOT / 'templates', data / 'templates')
            os.link(secret, data / ACCESS_FILE)
            os.chmod(stage_db, 0o600)
            os.link(stage_db, db)
        finally:
            server.DB_PATH = previous_db
    return {'created': True, 'fixture_applications': 3, 'credentials_written': True}


def decorate_html(raw):
    text = raw.decode('utf-8')
    text = text.replace('<head>', '<head><meta name="robots" content="noindex,nofollow,noarchive">', 1)
    text = text.replace('<body>', '<body><aside id="sandboxWarning" role="note" style="position:fixed;bottom:0;left:0;right:0;z-index:100000;background:#fff3cd;color:#583d00;padding:8px 16px;text-align:center;font:600 14px system-ui;border-top:2px solid #d29b00">SANDBOX · ТЕСТОВІ ДАНІ · SAFE MODE — зміни та зовнішні оновлення вимкнено</aside>', 1)
    text = text.replace('PQM · WEB TEST</em>', 'PQM · SANDBOX</em>', 1)
    return text.encode('utf-8')


def main():
    validate_environment()
    install_outbound_guard()
    import server
    result = bootstrap(server)
    print('PQM SANDBOX bootstrap:', json.dumps(result), flush=True)
    server.main()


if __name__ == '__main__':
    main()
