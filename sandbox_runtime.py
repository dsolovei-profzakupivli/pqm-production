"""Isolated, fail-closed first sandbox release. Never bootstrap a working WEB DB.

Render Docker command: python sandbox_runtime.py
Only the owned pqm-sandbox service is accepted. Safe mode remains enabled;
explicit flags allow reviewed local edits and GET-only Prozorro import,
including an independently opted-in scheduler, never production destinations.
"""
from __future__ import annotations

import datetime
from contextlib import closing
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import sandbox_documents
import sandbox_amcu
import sandbox_nazk

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
_egress = threading.local()
PROZORRO_HOST = 'public-api.prozorro.gov.ua'
_original_getaddrinfo = socket.getaddrinfo


def validate_environment(env=None):
    env = os.environ if env is None else env
    for key, expected in POLICY.items():
        if env.get(key) != expected:
            raise RuntimeError(f'STOP: sandbox policy requires {key}={expected}')
    if env.get('PQM_SANDBOX_EDITS', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_EDITS must be 0 or 1')
    if env.get('PQM_SANDBOX_DOCUMENTS', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_DOCUMENTS must be 0 or 1')
    if env.get('PQM_SANDBOX_AMCU_READ', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_AMCU_READ must be 0 or 1')
    if env.get('PQM_SANDBOX_NAZK_READ', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_NAZK_READ must be 0 or 1')
    if env.get('PQM_SANDBOX_PROZORRO_READ', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_PROZORRO_READ must be 0 or 1')
    if env.get('PQM_SANDBOX_PROZORRO_SCHEDULER', '0') not in {'0', '1'}:
        raise RuntimeError('STOP: PQM_SANDBOX_PROZORRO_SCHEDULER must be 0 or 1')
    if (env.get('PQM_SANDBOX_PROZORRO_SCHEDULER') == '1'
            and env.get('PQM_SANDBOX_PROZORRO_READ') != '1'):
        raise RuntimeError('STOP: sandbox scheduler requires the restricted Prozorro transport')
    data = Path(env.get('PQM_DATA_DIR', '')).resolve()
    db = Path(env.get('PQM_DB_PATH', '')).resolve()
    if db != data / 'pqm_sandbox.sqlite3' or Path(env['PQM_DB_PATH']).is_symlink():
        raise RuntimeError('STOP: sandbox database path mismatch')
    service = env.get('RENDER_SERVICE_ID', '')
    if service:
        if (env.get('RENDER_SERVICE_NAME') != 'pqm-sandbox'
                or service == 'srv-da7vmitg1s2s73fim0p0' or data != Path('/var/data').resolve()):
            raise RuntimeError('STOP: wrong Render service or disk path')
        if env.get('PQM_SANDBOX_PROZORRO_READ') == '1' and service != 'srv-dalfd77f3r2c7392uub0':
            raise RuntimeError('STOP: Prozorro testing requires the approved sandbox service')
        if env.get('PQM_SANDBOX_DOCUMENTS') == '1' and service != 'srv-dalfd77f3r2c7392uub0':
            raise RuntimeError('STOP: document testing requires the approved sandbox service')
        if env.get('PQM_SANDBOX_AMCU_READ') == '1' and service != 'srv-dalfd77f3r2c7392uub0':
            raise RuntimeError('STOP: AMCU testing requires the approved sandbox service')
        if env.get('PQM_SANDBOX_NAZK_READ') == '1' and service != 'srv-dalfd77f3r2c7392uub0':
            raise RuntimeError('STOP: NAZK testing requires the approved sandbox service')
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


def local_edits_enabled():
    return os.environ.get('PQM_SANDBOX') == '1' and os.environ.get('PQM_SANDBOX_EDITS', '0') == '1'


def prozorro_read_enabled():
    return os.environ.get('PQM_SANDBOX') == '1' and os.environ.get('PQM_SANDBOX_PROZORRO_READ', '0') == '1'


def prozorro_scheduler_enabled():
    return prozorro_read_enabled() and os.environ.get('PQM_SANDBOX_PROZORRO_SCHEDULER', '0') == '1'


def prozorro_catchup_delay(db_path, moment):
    """Read-only restart decision: None=skip, 0=due, positive=retry delay.

    Never steal a live lease. An orphan expires after the existing 180s TTL;
    retrying here avoids waiting an extra hour after an interrupted deploy.
    A single manual framework import is not a successful automatic full run.
    """
    def parse(value):
        if not value:
            return None
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=datetime.timezone.utc) if parsed.tzinfo is None else parsed
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        lease = con.execute("SELECT lease_until FROM scheduler_job_leases WHERE job_key='prozorro'").fetchone()
        state = con.execute("SELECT last_status,last_trigger,last_finished_at FROM scheduler_job_state WHERE job_key='prozorro'").fetchone()
    if lease:
        remaining = (parse(lease[0]) - moment).total_seconds()
        if remaining > 0:
            return min(30, remaining)
    if state and state[0] != 'running' and state[1] in {'scheduled', 'startup_catchup'}:
        finished = parse(state[2])
        if finished and (moment - finished).total_seconds() < 3600:
            return None
    return 0


def manual_sync_allowed(method, path):
    # This does not grant a role permission; normal auth/RBAC still applies.
    return prozorro_read_enabled() and method == 'POST' and path == '/api/sync'


def validate_prozorro_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != PROZORRO_HOST
            or parsed.username or parsed.password or parsed.fragment
            or not re.fullmatch(r'/api/2\.5/(?:frameworks(?:/[a-zA-Z0-9_-]+(?:/(?:submissions|qualifications))?)?|agreements/[a-zA-Z0-9_-]+/contracts)', parsed.path)
            or any(key != 'offset' for key in urllib.parse.parse_qs(parsed.query, keep_blank_values=True))):
        raise RuntimeError('Sandbox permits only public read-only Prozorro framework endpoints')


def _restricted_getaddrinfo(host, port, *args, **kwargs):
    if getattr(_egress, 'active', False):
        if host != PROZORRO_HOST or port not in (443, '443'):
            raise RuntimeError('Sandbox DNS destination is not approved')
        rows = _original_getaddrinfo(host, port, *args, **kwargs)
        if not rows or any(not ipaddress.ip_address(row[4][0]).is_global for row in rows):
            raise RuntimeError('Sandbox rejects non-public Prozorro addresses')
        _egress.addresses = {row[4][0] for row in rows}
        return rows
    return _original_getaddrinfo(host, port, *args, **kwargs)


class _ProzorroRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_prozorro_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_prozorro_json(url):
    """One bounded credential-free HTTPS GET, never a generic egress exception."""
    if not prozorro_read_enabled():
        raise RuntimeError('Sandbox Prozorro read is disabled')
    validate_prozorro_url(url)
    if getattr(_egress, 'active', False):
        raise RuntimeError('Nested sandbox network scope is not supported')
    _egress.active = True
    _egress.addresses = set()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _ProzorroRedirect())
        request = urllib.request.Request(url, headers={'User-Agent': 'PQM-Sandbox/0.1', 'Accept': 'application/json'}, method='GET')
        with opener.open(request, timeout=60) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise RuntimeError('Sandbox Prozorro response exceeds limit')
            result = json.loads(raw)
            if not isinstance(result, dict) or 'data' not in result:
                raise RuntimeError('Sandbox Prozorro response is not an API payload')
            return result
    finally:
        _egress.active = False
        _egress.addresses = set()


def local_edit_allowed(method, path):
    """Allowlist, not a role grant. Normal RBAC/final/history guards still run.

    No imports, document generation, verification, NAZK results, builders,
    refresh or integration controls. Unknown/future routes stay blocked.
    """
    if not local_edits_enabled():
        return False
    routes = {
        'PATCH': (
            r'/api/applications/[A-Za-z0-9_-]+(?:/remark-selections)?',
            r'/api/account', r'/api/admin/users/[A-Za-z0-9._-]+',
            r'/api/admin/officers/\d+', r'/api/application-profiles/[A-Za-z0-9_-]+',
        ),
        'POST': (
            r'/api/account/avatar', r'/api/admin/users',
            r'/api/admin/users/[A-Za-z0-9._-]+/avatar', r'/api/admin/officers',
            r'/api/chats', r'/api/chats/\d+/(?:messages|read)',
            r'/api/application-profiles', r'/api/history-columns',
        ),
        'DELETE': (
            r'/api/account/avatar', r'/api/admin/users/[A-Za-z0-9._-]+(?:/avatar)?',
            r'/api/admin/officers/\d+', r'/api/application-profiles/[A-Za-z0-9_-]+',
        ),
    }
    return any(re.fullmatch(pattern, path) for pattern in routes.get(method, ()))


def outbound_audit(event, args):
    # Defense in depth for this Python process. This is not an OS firewall.
    loopback = {'localhost', '127.0.0.1', '::1'}
    if event in {'socket.connect', 'socket.sendto'}:
        address = args[1] if event == 'socket.connect' else args[-1]
        scoped = (event == 'socket.connect' and prozorro_read_enabled()
                  and getattr(_egress, 'active', False) and isinstance(address, tuple)
                  and address[0] in getattr(_egress, 'addresses', set()) and address[1] == 443)
        if not scoped and (not isinstance(address, tuple) or address[0] not in loopback):
            raise RuntimeError('Sandbox outbound network is disabled')
    if event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'} and args[0] not in loopback:
        if not (event == 'socket.getaddrinfo' and prozorro_read_enabled()
                and getattr(_egress, 'active', False) and args[0] == PROZORRO_HOST):
            raise RuntimeError('Sandbox external DNS is disabled')
    if event == 'urllib.Request' and getattr(_egress, 'active', False):
        validate_prozorro_url(args[0])
        if args[1] is not None or args[3] != 'GET':
            raise RuntimeError('Sandbox external mutations are disabled')
    if event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        if sandbox_nazk.enabled() and sandbox_nazk.permitted_process(event, args):
            return
        if sandbox_amcu.enabled() and sandbox_amcu.permitted_process(event, args):
            return
        if sandbox_documents.enabled() and sandbox_documents.permitted_process(event, args):
            return
        raise RuntimeError('Sandbox safe smoke does not launch child processes')


def install_outbound_guard():
    global _guard_installed
    if not _guard_installed:
        socket.getfqdn = lambda name='': name or 'localhost'
        socket.getaddrinfo = _restricted_getaddrinfo
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


def _bootstrap_snapshot(source, target):
    """Publish a standalone bootstrap DB without switching a shared WAL file.

    Legacy init helpers can retain committed connections until GC. SQLite
    refuses WAL -> DELETE on that file while those connections remain open.
    Backup includes committed WAL data and the unique destination has no other
    connections. This is used only for a new, disposable bootstrap DB.
    """
    if target.exists():
        raise RuntimeError('STOP: bootstrap snapshot destination already exists')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                raise RuntimeError('STOP: bootstrap snapshot is not standalone')
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('STOP: invalid bootstrap snapshot')


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
            # Snapshot only our disposable new DB; never change journal mode
            # on the shared source or rely on init-helper connection GC.
            published_db = stage / 'published.sqlite3'
            _bootstrap_snapshot(stage_db, published_db)
            _verify_existing(published_db, service)
            secret = stage / ACCESS_FILE
            fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'scope': 'pqm-sandbox only', 'created_at': stamp, 'accounts': access}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            # Link is exclusive (unlike rename/replace), so an existing target cannot be overwritten.
            shutil.copytree(ROOT / 'templates', data / 'templates')
            os.link(secret, data / ACCESS_FILE)
            os.chmod(published_db, 0o600)
            os.link(published_db, db)
        finally:
            server.DB_PATH = previous_db
    return {'created': True, 'fixture_applications': 3, 'credentials_written': True}


def decorate_html(raw):
    text = raw.decode('utf-8')
    if os.environ.get('PQM_SANDBOX') == '1':
        text = text.replace('<html', '<html data-pqm-environment="sandbox"', 1)
        text = text.replace('<link rel="icon" href="/assets/pqm-search-icon.png" type="image/png" sizes="192x192">', '')
        text = text.replace('<link rel="icon" href="/assets/pqm-tab-icon.png" type="image/png" sizes="32x32">',
                            '<link rel="icon" href="/assets/pqm-sandbox-tab-inverted.svg?v=1" type="image/svg+xml" sizes="any">')
        theme = (ROOT / 'sandbox_theme.css').read_text(encoding='utf-8')
        text = text.replace('</head>', '<style id="pqmSandboxTheme">' + theme + '</style></head>', 1)
        text = text.replace('</head>', '<script src="/sandbox_contrast.js?v=1" defer></script></head>', 1)
    text = text.replace('<head>', '<head><meta name="robots" content="noindex,nofollow,noarchive">', 1)
    mode = ('ЛОКАЛЬНІ ТЕСТОВІ ЗМІНИ — інтеграції, імпорти та jobs вимкнено'
            if local_edits_enabled() else 'SAFE MODE — зміни та зовнішні оновлення вимкнено')
    if prozorro_read_enabled():
        mode = 'РУЧНИЙ PROZORRO → лише БД SANDBOX · автоматичні jobs та інші інтеграції вимкнено'
    if prozorro_scheduler_enabled():
        mode = 'PROZORRO → лише БД SANDBOX · автоматично щогодини о :05 (Київ) · інші інтеграції вимкнено'
    text = text.replace('<body>', '<body><aside id="sandboxWarning" role="note" style="position:fixed;bottom:0;left:0;right:0;z-index:100000;background:#fff3cd;color:#583d00;padding:8px 16px;text-align:center;font:600 14px system-ui;border-top:2px solid #d29b00">SANDBOX · ТЕСТОВІ ДАНІ · ' + mode + '</aside>', 1)
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
    # server imports this policy too. Keep one audit hook/thread-local scope
    # when the entrypoint itself was loaded as __main__.
    sys.modules['sandbox_runtime'] = sys.modules[__name__]
    main()
