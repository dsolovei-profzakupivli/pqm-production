"""Isolated execution transport and fourth-job state. Never imports application startup."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import base64
import background_jobs
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import threading
import urllib.request
import urllib.parse
import uuid
from zoneinfo import ZoneInfo
from pathlib import Path

KYIV = ZoneInfo('Europe/Kyiv')
JOB = 'google_writer'
CONTRACT = 'pqm-mirror-datetime-v1'
IDENTITIES = {
    'PROD': ('1TPR8GjoKeiWIlMJkXKpSM2X4rJrq8hIlFqMBn5kzyzurRbZPD_GZQOd6',
             '1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA', 'pqmProdExecution'),
    'SANDBOX': ('1Ht0jL2xQc3hsd6uWKui4uA6o1z2Oe_BAUbZq8HTXcw6C1Kpyi7JxNtmQ',
                '1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww', 'pqmSandboxExecution'),
}
# Execution API requires every scope of the existing project, not just the writer.
PROJECT_SCOPES = frozenset({
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/script.external_request',
    'https://www.googleapis.com/auth/script.scriptapp',
    'https://www.googleapis.com/auth/script.container.ui',
    'https://www.googleapis.com/auth/userinfo.email',
})
RENDER_SECRET_DIR = Path('/etc/secrets')


def _credential_mode_allowed(mode, *, render_managed):
    """Private local files are 0600/0400; only Render's secret mount may be 0640."""
    permissions = stat.S_IMODE(mode)
    return permissions in (0o600, 0o400) or (render_managed and permissions == 0o640)


def _is_render_secret_path(path, secret_dir=None):
    secret_dir = Path(secret_dir or RENDER_SECRET_DIR)
    candidate = Path(os.path.abspath(os.fspath(path)))
    root = Path(os.path.abspath(os.fspath(secret_dir)))
    if candidate.parent != root or candidate.name in ('', '.', '..'):
        return False
    try:
        root_stat = os.lstat(root)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            return False
        # Reject a symlinked parent component as well as a symlinked credential file.
        if root.parent != root and stat.S_ISLNK(os.lstat(root.parent).st_mode):
            return False
    except OSError:
        return False
    return True


def _open_regular_nofollow(path, flags):
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(os.fspath(path), flags | nofollow | cloexec)
    try:
        opened = os.fstat(fd)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or stat.S_ISLNK(named.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError('Credential file identity rejected')
        return fd, opened
    except Exception:
        os.close(fd)
        raise


def _render_secret_mount_open(root):
    """Open the trusted, read-only Render Secret Files mount without following links."""
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    directory = getattr(os, 'O_DIRECTORY', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    root_fd = os.open(os.fspath(root), os.O_RDONLY | directory | nofollow | cloexec)
    try:
        opened = os.fstat(root_fd)
        named = os.lstat(root)
        if (not stat.S_ISDIR(opened.st_mode) or stat.S_ISLNK(named.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino) or
                not os.path.ismount(root) or
                not (os.statvfs(root).f_flag & getattr(os, 'ST_RDONLY', 1))):
            raise ValueError('Render Secret Files mount is not trusted')
        if root.parent != root and stat.S_ISLNK(os.lstat(root.parent).st_mode):
            raise ValueError('Render Secret Files parent is not trusted')
        return root_fd, opened
    except Exception:
        os.close(root_fd)
        raise


def _render_secret_target_parts(target, root):
    """Accept only a canonical target path contained beneath the mounted secret dir."""
    root_text = os.path.abspath(os.fspath(root))
    target_text = os.fspath(target)
    if os.path.isabs(target_text):
        if any(part in ('.', '..') for part in target_text.split(os.sep)):
            raise ValueError('Render Secret File target path is not canonical')
        normalized = os.path.normpath(target_text)
        try:
            if os.path.commonpath((root_text, normalized)) != root_text:
                raise ValueError('Render Secret File target escapes mount')
        except ValueError:
            raise ValueError('Render Secret File target escapes mount') from None
        relative = os.path.relpath(normalized, root_text)
    else:
        relative = target_text
    parts = relative.split(os.sep)
    if (not relative or relative in ('.', '..') or
            any(part in ('', '.', '..') for part in parts) or
            any('\\' in part or '\x00' in part for part in parts)):
        raise ValueError('Render Secret File target path is not canonical')
    return parts


def _open_render_secret_target(root_fd, parts):
    """Open each target component relative to pinned directory FDs, never following links."""
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    directory = getattr(os, 'O_DIRECTORY', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    directory_fds = []
    current_fd = root_fd
    directory_ids = []
    try:
        for part in parts[:-1]:
            named = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if not stat.S_ISDIR(named.st_mode) or stat.S_ISLNK(named.st_mode):
                raise ValueError('Nested Render Secret File symlink rejected')
            child_fd = os.open(part, os.O_RDONLY | directory | nofollow | cloexec,
                               dir_fd=current_fd)
            opened = os.fstat(child_fd)
            if (not stat.S_ISDIR(opened.st_mode) or
                    (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
                os.close(child_fd)
                raise ValueError('Render Secret File directory changed while opening')
            directory_fds.append(child_fd)
            directory_ids.append((opened.st_dev, opened.st_ino))
            current_fd = child_fd
        named = os.stat(parts[-1], dir_fd=current_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or stat.S_ISLNK(named.st_mode):
            raise ValueError('Render Secret File target must be a regular file')
        target_fd = os.open(parts[-1], os.O_RDONLY | nofollow | cloexec, dir_fd=current_fd)
        opened = os.fstat(target_fd)
        if (not stat.S_ISREG(opened.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            os.close(target_fd)
            raise ValueError('Render Secret File target changed while opening')
        return target_fd, opened, directory_fds, tuple(directory_ids)
    except Exception:
        for fd in reversed(directory_fds):
            os.close(fd)
        raise


def _read_bounded_fd(fd, limit):
    chunks = []
    remaining = limit
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_render_secret_symlink(path):
    """Read one Render-managed link, pinning and rechecking both link and target identity."""
    root = Path(os.path.abspath(os.fspath(RENDER_SECRET_DIR)))
    candidate = Path(os.path.abspath(os.fspath(path)))
    if not _is_render_secret_path(candidate, root) or os.name == 'nt':
        raise ValueError('Credential symlink is not a Render Secret File')
    root_fd, root_before = _render_secret_mount_open(root)
    target_fd = None
    directory_fds = []
    try:
        link_name = candidate.name
        link_before = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISLNK(link_before.st_mode):
            raise ValueError('Render Secret File link changed before reading')
        target_text = os.readlink(link_name, dir_fd=root_fd)
        parts = _render_secret_target_parts(target_text, root)
        target_fd, target_before, directory_fds, directory_ids = _open_render_secret_target(root_fd, parts)
        if (target_before.st_dev != root_before.st_dev or
                not _credential_mode_allowed(target_before.st_mode, render_managed=True)):
            raise ValueError('Render Secret File target permissions are not allowed')
        raw = _read_bounded_fd(target_fd, 65537)
        target_after = os.fstat(target_fd)
        if (len(raw) > 65536 or len(raw) != target_before.st_size or
                (target_before.st_dev, target_before.st_ino, target_before.st_size,
                 target_before.st_mtime_ns, target_before.st_ctime_ns) !=
                (target_after.st_dev, target_after.st_ino, target_after.st_size,
                 target_after.st_mtime_ns, target_after.st_ctime_ns)):
            raise ValueError('Render Secret File target changed while reading')
        link_after = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if ((link_before.st_dev, link_before.st_ino) != (link_after.st_dev, link_after.st_ino) or
                not stat.S_ISLNK(link_after.st_mode) or
                os.readlink(link_name, dir_fd=root_fd) != target_text):
            raise ValueError('Render Secret File link changed while reading')
        target_check_fd, target_check, check_fds, check_ids = _open_render_secret_target(root_fd, parts)
        try:
            if ((target_after.st_dev, target_after.st_ino) !=
                    (target_check.st_dev, target_check.st_ino) or directory_ids != check_ids):
                raise ValueError('Render Secret File target identity changed while reading')
        finally:
            os.close(target_check_fd)
            for fd in reversed(check_fds):
                os.close(fd)
        root_after = os.fstat(root_fd)
        root_named_after = os.lstat(root)
        if ((root_before.st_dev, root_before.st_ino) != (root_after.st_dev, root_after.st_ino) or
                (root_after.st_dev, root_after.st_ino) !=
                (root_named_after.st_dev, root_named_after.st_ino) or
                not os.path.ismount(root) or
                not (os.statvfs(root).f_flag & getattr(os, 'ST_RDONLY', 1))):
            raise ValueError('Render Secret Files mount changed while reading')
        return raw, target_before
    finally:
        if target_fd is not None:
            os.close(target_fd)
        for fd in reversed(directory_fds):
            os.close(fd)
        os.close(root_fd)


def _private_credential_copy(raw):
    """Atomically stage bytes in a process-private ephemeral directory (0600 file)."""
    temp_root = Path(tempfile.gettempdir())
    root_stat = os.lstat(temp_root)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise ValueError('Private temporary root rejected')
    directory = Path(tempfile.mkdtemp(prefix='pqm-execution-oauth-', dir=temp_root))
    temporary = directory / 'credential.tmp'
    final = directory / 'credential.json'
    try:
        os.chmod(directory, 0o700)
        directory_stat = os.lstat(directory)
        if (not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode) or
                (hasattr(os, 'getuid') and directory_stat.st_uid != os.getuid()) or
                stat.S_IMODE(directory_stat.st_mode) != 0o700):
            raise ValueError('Private temporary directory rejected')
        fd = os.open(os.fspath(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, final)
        fd, copied = _open_regular_nofollow(final, os.O_RDONLY)
        try:
            if (stat.S_IMODE(copied.st_mode) != 0o600 or
                    (hasattr(os, 'getuid') and copied.st_uid != os.getuid())):
                raise ValueError('Private temporary credential rejected')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                staged = stream.read(65537)
            if staged != raw or len(staged) > 65536:
                raise ValueError('Private credential copy verification failed')
            return staged
        finally:
            os.close(fd)
    finally:
        for path in (temporary, final):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(directory)
        except OSError:
            # Never follow or recursively remove an unexpected replacement.
            pass


def _load_execution_credential(path):
    render_managed = _is_render_secret_path(path)
    if os.name != 'nt' and render_managed and stat.S_ISLNK(os.lstat(path).st_mode):
        raw, before = _read_render_secret_symlink(path)
        render_symlink = True
    else:
        fd, before = _open_regular_nofollow(path, os.O_RDONLY)
        try:
            if os.name != 'nt' and not _credential_mode_allowed(before.st_mode, render_managed=render_managed):
                raise ValueError('Credential permissions are not private')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(65537)
            after = os.fstat(fd)
            named_after = os.lstat(path)
            if (len(raw) > 65536 or len(raw) != before.st_size or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                    stat.S_ISLNK(named_after.st_mode) or
                    (after.st_dev, after.st_ino) != (named_after.st_dev, named_after.st_ino)):
                raise ValueError('Credential file changed while reading')
        finally:
            os.close(fd)
        render_symlink = False
    if os.name != 'nt' and (render_symlink or stat.S_IMODE(before.st_mode) == 0o640):
        if not render_managed:
            raise ValueError('Group-readable credential is not a Render Secret File')
        raw = _private_credential_copy(raw)
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Credential JSON object required')
    return value


class ExecutionConfigurationError(ValueError):
    pass


class ExecutionOutcomeUnknown(RuntimeError):
    """Never retry automatically: a transport error can follow committed writes."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ExecutionOutcomeUnknown('Execution redirect rejected; reconcile before another Apply')


def transport_open(request, timeout, environment, deployment_id=None):
    """SANDBOX requests use the existing process guard, never a generic bypass."""
    sandbox = os.getenv('PQM_SANDBOX', '').lower() in ('1', 'true')
    if environment == 'SANDBOX' or sandbox:
        if environment != 'SANDBOX':
            raise ExecutionConfigurationError('Execution environment isolation rejected')
        import sandbox_runtime
        script, sheet, _ = IDENTITIES['SANDBOX']
        return sandbox_runtime.execution_open(request, timeout=timeout,
            environment=environment, script_id=script, spreadsheet_id=sheet,
            deployment_id=deployment_id or os.getenv('PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID', ''))
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


class DedicatedTokenProvider:
    """One environment-specific user OAuth credential. No authorization flow or service account."""
    def __init__(self, environment, path, project_id, *, opener=None, clock=None):
        self.environment, self.path, self.project_id = environment, path, project_id
        self.opener = opener or (lambda request, timeout: transport_open(request, timeout, self.environment))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cached = None

    def __call__(self, environment):
        if environment != self.environment or not self.path or not self.project_id:
            raise ExecutionConfigurationError('Dedicated execution credential identity absent')
        if self.cached and self.cached['expires_at'] - self.clock().timestamp() > 400:
            return self.cached
        try:
            value = _load_execution_credential(self.path)
            if (value.get('environment') != environment or value.get('gcp_project_id') != self.project_id or
                    value.get('type') == 'service_account' or
                    not PROJECT_SCOPES.issubset(set(value.get('scopes', [])))):
                raise ValueError('Credential attestation rejected')
            if float(value.get('expires_at', 0)) - self.clock().timestamp() > 400 and value.get('access_token'):
                self.cached = value
                return value
            if not all(value.get(k) for k in ('client_id','client_secret','refresh_token')):
                raise ValueError('Authorized refresh credential absent')
            payload = urllib.parse.urlencode({k:value[k] for k in ('client_id','client_secret','refresh_token')} |
                                             {'grant_type':'refresh_token'}).encode()
            request = urllib.request.Request('https://oauth2.googleapis.com/token',data=payload,method='POST',
                                             headers={'Content-Type':'application/x-www-form-urlencoded'})
            with self.opener(request,timeout=30) as response:
                result = json.loads(response.read(65536).decode())
            scopes = set(result.get('scope','').split()) if result.get('scope') else set(value['scopes'])
            if not result.get('access_token') or int(result.get('expires_in',0)) <= 400 or not PROJECT_SCOPES.issubset(scopes):
                raise ValueError('Refresh did not preserve required scopes/lifetime')
            self.cached = {**value,'access_token':result['access_token'],'scopes':sorted(scopes),
                           'expires_at':self.clock().timestamp()+int(result['expires_in'])}
            return self.cached
        except Exception:
            raise ExecutionConfigurationError('Dedicated execution OAuth credential unavailable') from None


class ExecutionClient:
    def __init__(self, environment, deployment_id, shared_secret, token_provider, *,
                 configured=False, opener=None, clock=None):
        self.environment = environment
        self.deployment_id = deployment_id
        self.shared_secret = shared_secret
        self.token_provider = token_provider
        self.configured = configured
        self.opener = opener or (lambda request, timeout: transport_open(request, timeout, self.environment, self.deployment_id))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self):
        if (not self.configured or self.environment not in IDENTITIES or
                not re.fullmatch(r'[A-Za-z0-9_-]{20,256}', str(self.deployment_id or '')) or
                not isinstance(self.shared_secret, str) or len(self.shared_secret) < 32):
            raise ExecutionConfigurationError('Execution channel not independently configured and attested')

    def invoke(self, action, request_id, actor, *, trigger='manual', digest=None,
               manual_authorized=False):
        manual_override = (manual_authorized is True and trigger == 'manual' and
                           isinstance(actor, str) and bool(actor.strip()))
        if background_jobs.disabled() and not manual_override:
            raise ExecutionConfigurationError('Background jobs disabled')
        self.validate()
        if action not in {'preview', 'apply'} or trigger not in {'manual', 'scheduled'}:
            raise ValueError('Unsupported execution action')
        if not re.fullmatch(r'[0-9a-f]{32}', request_id) or not actor or len(actor) > 128:
            raise ValueError('Invalid execution identity')
        if action == 'apply' and not re.fullmatch(r'[0-9a-f]{64}', str(digest or '')):
            raise ValueError('Reviewed Preview digest required')
        script, sheet, function = IDENTITIES[self.environment]
        issued = int(self.clock().timestamp())
        message = {'environment':self.environment, 'scriptId':script, 'spreadsheetId':sheet,
                   'contract':CONTRACT, 'action':action, 'requestId':request_id,
                   'actor':actor, 'trigger':trigger, 'issuedAt':issued, 'expiresAt':issued+300,
                   'expectedDigest':digest}
        raw = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        signature = base64.urlsafe_b64encode(hmac.new(self.shared_secret.encode(), raw.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        token = self.token_provider(self.environment)
        if (token.get('environment') != self.environment or
                not PROJECT_SCOPES.issubset(set(token.get('scopes', []))) or
                float(token.get('expires_at', 0)) - self.clock().timestamp() <= 400 or
                not token.get('access_token')):
            raise ExecutionConfigurationError('Dedicated OAuth token identity, scopes or lifetime invalid')
        body = {'function':function, 'devMode':False,
                'parameters':[{'payload':raw, 'signature':signature}]}
        # Current Google reference names this path parameter deploymentId.
        request = urllib.request.Request(
            'https://script.googleapis.com/v1/scripts/' + self.deployment_id + ':run',
            data=json.dumps(body).encode(), method='POST',
            headers={'Authorization':'Bearer '+token['access_token'], 'Content-Type':'application/json'})
        try:
            with self.opener(request, timeout=390) as response:
                data = json.loads(response.read(1024*1024).decode())
        except Exception:
            raise ExecutionOutcomeUnknown('Execution outcome unknown; no automatic retry') from None
        if data.get('done') is not True or 'error' in data:
            raise ExecutionOutcomeUnknown('Execution did not return a verified completion; reconciliation required')
        result = data.get('response', {}).get('result', {})
        if (not isinstance(result, dict) or result.get('environment') != self.environment or
                result.get('scriptId') != script or result.get('spreadsheetId') != sheet or
                result.get('contract') != CONTRACT or result.get('requestId') != request_id):
            raise ExecutionOutcomeUnknown('Execution response identity mismatch; reconciliation required')
        if action == 'preview' and not re.fullmatch(r'[0-9a-f]{64}', str(result.get('digest', ''))):
            raise ExecutionOutcomeUnknown('Invalid Preview receipt')
        # Return only technical receipts/counters; never remote errors, stack traces or secrets.
        safe = {key:result.get(key) for key in ('environment','scriptId','spreadsheetId','contract','requestId','status','digest')}
        counters = result.get('counts', {})
        if not isinstance(counters, dict) or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 or v != int(v) for v in counters.values()):
            raise ExecutionOutcomeUnknown('Invalid execution counters')
        safe['counts'] = {k:int(v) for k,v in counters.items() if k in {'append','update','conflict','error','remaining_safe','batches','skipped'}}
        return safe


def migrate(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS google_writer_settings(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),
        hour INTEGER NOT NULL DEFAULT 7 CHECK(hour BETWEEN 0 AND 23),
        minute INTEGER NOT NULL DEFAULT 0 CHECK(minute BETWEEN 0 AND 59),
        revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '');
      INSERT OR IGNORE INTO google_writer_settings(singleton) VALUES(1);
      CREATE TABLE IF NOT EXISTS google_writer_settings_audit(
        id INTEGER PRIMARY KEY, revision INTEGER UNIQUE NOT NULL, before_json TEXT NOT NULL,
        after_json TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS google_writer_runs(
        request_id TEXT PRIMARY KEY, environment TEXT NOT NULL, trigger TEXT NOT NULL,
        actor TEXT NOT NULL, revision INTEGER NOT NULL, started_at TEXT NOT NULL,
        finished_at TEXT, status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}');
      CREATE UNIQUE INDEX IF NOT EXISTS ix_google_writer_single_lane
        ON google_writer_runs(environment) WHERE status IN ('running','outcome_unknown');
    ''')


def settings(con):
    try:
        row = con.execute('SELECT enabled,hour,minute,revision FROM google_writer_settings WHERE singleton=1').fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc).lower(): raise
        row = None
    return dict(zip(('enabled','hour','minute','revision'),row)) if row else {'enabled':0,'hour':7,'minute':0,'revision':0}


def specification(payload):
    if (set(payload) != {'enabled','hour','minute'} or type(payload['enabled']) is not bool or
            type(payload['hour']) is not int or not 0 <= payload['hour'] <= 23 or
            type(payload['minute']) is not int or not 0 <= payload['minute'] <= 59):
        raise ValueError('Expected enabled boolean, hour 0–23, minute 0–59')
    return dict(payload)


def next_slot(config, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Aware scheduler clock required')
    current = now.astimezone(timezone.utc)
    day = current.astimezone(KYIV).date()
    for offset in range(8):
        wall = datetime.combine(day+timedelta(days=offset), datetime.min.time()).replace(hour=config['hour'],minute=config['minute'])
        candidates = sorted({wall.replace(tzinfo=KYIV,fold=f).astimezone(timezone.utc) for f in (0,1)
                             if wall.replace(tzinfo=KYIV,fold=f).astimezone(timezone.utc).astimezone(KYIV).replace(tzinfo=None)==wall})
        # Gap: skip that day's missing slot. Fold: use only the first occurrence.
        if candidates and candidates[0] > current: return candidates[0]
    raise ValueError('No future schedule slot')


def preview_settings(con, payload, now=None):
    after = specification(payload)
    return {'before':settings(con), 'after':after,
            'next_run':next_slot(after,now).astimezone(KYIV).isoformat(), 'timezone':'Europe/Kyiv'}


def save_settings(con, payload, expected_revision, actor, now=None):
    after = specification(payload)
    if type(expected_revision) is not int or not actor: raise ValueError('Revision and actor required')
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    before = settings(con)
    result = con.execute('''UPDATE google_writer_settings SET enabled=?,hour=?,minute=?,revision=revision+1,updated_at=?,actor=?
      WHERE singleton=1 AND revision=?''', (int(after['enabled']),after['hour'],after['minute'],stamp,actor,expected_revision))
    if result.rowcount != 1: raise RuntimeError('Schedule revision conflict')
    con.execute('INSERT INTO google_writer_settings_audit(revision,before_json,after_json,actor,occurred_at) VALUES(?,?,?,?,?)',
                (expected_revision+1,json.dumps(before),json.dumps(after),actor,stamp))
    return settings(con)


def claim_run(path, environment, request_id, actor, trigger, revision=None, now=None,
              manual_authorized=False):
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'claimed': False, 'status': 'background_jobs_disabled'}
    if environment not in IDENTITIES or trigger not in {'manual','scheduled'} or not re.fullmatch('[0-9a-f]{32}',request_id):
        raise ValueError('Invalid run identity')
    if not Path(path).is_file(): raise ValueError('Existing execution database required')
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT environment,actor,trigger,status,result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old[:3] != (environment,actor,trigger): raise PermissionError('Run identity reuse rejected')
            return {'claimed':False,'status':old[3],'result':json.loads(old[4])}
        config = settings(con)
        if trigger == 'scheduled' and (not config['enabled'] or revision != config['revision']):
            return {'claimed':False,'status':'schedule_changed'}
        try:
            con.execute('INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,started_at,status) VALUES(?,?,?,?,?,?,?)',
                        (request_id,environment,trigger,actor,config['revision'],(now or datetime.now(timezone.utc)).isoformat(),'running'))
        except sqlite3.IntegrityError:
            return {'claimed':False,'status':'another_run_or_unknown_outcome'}
        return {'claimed':True,'status':'running'}


def finish_run(path, request_id, status, result):
    if status not in {'complete','partial','failed_safe','outcome_unknown'}: raise ValueError('Unknown run status')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute("UPDATE google_writer_runs SET status=?,finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (status,datetime.now(timezone.utc).isoformat(),json.dumps(result),request_id))


def execute_claimed(path, client, request_id, actor, *, trigger='manual', digest=None,
                    guard=lambda:True, manual_authorized=False):
    """One common writer for manual and scheduled calls, no automatic retry."""
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'status': 'BACKGROUND_JOBS_DISABLED'}
    try:
        if not guard(): raise ExecutionConfigurationError('Execution guard changed before preview')
        if digest is None:
            digest = client.invoke('preview',request_id,actor,trigger=trigger,
                                   manual_authorized=manual_override)['digest']
        if (background_jobs.disabled() and not manual_override) or not guard():
            raise ExecutionConfigurationError('Execution guard changed before Apply')
        result = client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,
                               manual_authorized=manual_override)
        status = 'complete' if result['status']=='COMPLETE' else 'partial' if result['status'] in {'COMPLETE_WITH_CONFLICTS','PARTIAL_SAFE_OPERATIONS_REMAIN'} else 'outcome_unknown'
        finish_run(path,request_id,status,result)
        return result
    except ExecutionConfigurationError:
        finish_run(path,request_id,'failed_safe',{'status':'CONFIGURATION_REJECTED'})
        return {'status':'CONFIGURATION_REJECTED'}
    except Exception:
        finish_run(path,request_id,'outcome_unknown',{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'})
        return {'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'}


def status(path, environment, *, available=False, running=False, heartbeat=None, now=None):
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        config = settings(con)
        try:
            con.row_factory=sqlite3.Row
            rows=[dict(row) for row in con.execute('''SELECT request_id,trigger,actor,revision,started_at,finished_at,status,result_json
              FROM google_writer_runs WHERE environment=? ORDER BY started_at DESC LIMIT 20''',(environment,))]
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower(): raise
            rows=[]
    for row in rows: row['result']=json.loads(row.pop('result_json'))
    last=rows[0] if rows else {}
    blocked=any(row['status'] in {'running','outcome_unknown'} for row in rows)
    # Unknown/active lanes are queried separately: an older hold must not be hidden by log limits.
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        try: blocked=bool(con.execute("SELECT 1 FROM google_writer_runs WHERE environment=? AND status IN ('running','outcome_unknown')",(environment,)).fetchone())
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower(): raise
    enabled=bool(config['enabled'] and available and running and not blocked)
    return {'job':JOB,'enabled':enabled,'configured_enabled':bool(config['enabled']),'hour':config['hour'],'minute':config['minute'],
            'revision':config['revision'],'timezone':'Europe/Kyiv','schedule':f"Щодня о {config['hour']:02}:{config['minute']:02}",
            'next_run':next_slot(config,now).astimezone(KYIV).isoformat() if enabled else None,
            'registered':running,'running':running,'heartbeat_at':heartbeat,'manageable':True,
            'configuration_source':'runtime','last_started_at':last.get('started_at'),'last_finished_at':last.get('finished_at'),
            'last_status':last.get('status','never'),'blocked':blocked,'channel_ready':available,'runs':rows}


class Scheduler:
    """Fourth job only. No catch-up, no alterations to existing scheduler registry or leases."""
    def __init__(self,path,environment,client_factory,guard,*,clock=None):
        self.path,self.environment,self.client_factory,self.guard=path,environment,client_factory,guard
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.wakeup=threading.Event();self.stop=threading.Event();self.mutex=threading.Lock()
        self.thread=None;self.heartbeat=None

    def start(self):
        if background_jobs.disabled():
            return False
        with self.mutex:
            if self.thread and self.thread.is_alive():
                self.wakeup.set();return False
            with closing(sqlite3.connect(self.path,timeout=5)) as con: config=settings(con)
            if not config['enabled'] or not self.guard(): return False
            self.stop.clear();self.wakeup.clear()
            self.thread=threading.Thread(target=self.loop,name='pqm-google-writer-scheduler',daemon=True)
            self.thread.start();return True

    def reschedule(self):
        self.wakeup.set()
        return self.start()

    def loop(self):
        target=None;revision=None
        while not self.stop.is_set() and not background_jobs.disabled():
            self.heartbeat=self.clock().isoformat()
            try:
                with closing(sqlite3.connect(self.path,timeout=5)) as con: config=settings(con)
                if not config['enabled'] or not self.guard(): return
                if target is None or config['revision'] != revision:
                    target=next_slot(config,self.clock());revision=config['revision']
                remaining=(target-self.clock().astimezone(timezone.utc)).total_seconds()
                if remaining>0:
                    self.wakeup.wait(min(remaining,30));self.wakeup.clear();continue
                # One stable slot identity across processes/restarts; revisions cannot produce duplicate Apply.
                run_id=hashlib.sha256((self.environment+':'+target.isoformat()).encode()).hexdigest()[:32]
                claimed=claim_run(self.path,self.environment,run_id,'scheduler','scheduled',revision,self.clock())
                if claimed['claimed'] and self.guard():
                    def current_guard():
                        with closing(sqlite3.connect(self.path,timeout=5)) as check:
                            latest=settings(check)
                        return not background_jobs.disabled() and self.guard() and bool(latest['enabled']) and latest['revision']==revision
                    execute_claimed(self.path,self.client_factory(),run_id,'scheduler',trigger='scheduled',guard=current_guard)
                elif claimed['claimed']:
                    finish_run(self.path,run_id,'failed_safe',{'status':'SAFETY_GUARD_CHANGED'})
                target=next_slot(config,self.clock())
            except Exception:
                # Do not repeat an uncertain cloud execution. Configuration/storage faults stop this listener.
                return


def preview_ticket(client,request_id,actor,digest):
    value={'environment':client.environment,'request_id':request_id,'actor':actor,'digest':digest,
           'expires_at':int(client.clock().timestamp())+300}
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    signature=hmac.new(client.shared_secret.encode(),b'PQM-PREVIEW-TICKET:'+raw,hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+base64.urlsafe_b64encode(signature).decode().rstrip('=')


def verify_ticket(client,ticket,actor):
    try:
        client.validate()
        encoded,signed=ticket.split('.')
        raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        signature=base64.urlsafe_b64decode(signed+'='*(-len(signed)%4))
        if not hmac.compare_digest(signature,hmac.new(client.shared_secret.encode(),b'PQM-PREVIEW-TICKET:'+raw,hashlib.sha256).digest()):
            raise ValueError('Ticket signature mismatch')
        value=json.loads(raw)
        if (value['environment']!=client.environment or value['actor']!=actor or
                value['expires_at']<client.clock().timestamp() or
                not re.fullmatch('[0-9a-f]{32}',value['request_id']) or
                not re.fullmatch('[0-9a-f]{64}',value['digest'])):
            raise ValueError('Ticket context mismatch')
        return value
    except Exception:
        raise ValueError('Reviewed Preview ticket is invalid or expired') from None
