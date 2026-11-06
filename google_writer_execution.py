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
from execution_digest import is_canonical_sha256_b64url
from execution_apply_contract import checkpoint_apply_enabled

KYIV = ZoneInfo('Europe/Kyiv')
JOB = 'google_writer'
CONTRACT = 'pqm-mirror-datetime-v1'
PREVIEW_PLAN_TTL_SECONDS = 300
PREVIEW_DETAIL_MAX_BYTES = 750_000
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
_PARTIAL_RECONCILIATION_FIRST_FINGERPRINT = '9be34ff2df1e661346176eeb'
_PARTIAL_RECONCILIATION_SECOND_FINGERPRINT = '18a4aba10c1c13ab3bf59f56'
_PARTIAL_RECONCILIATION_FIRST_EVIDENCE = {
    'initial_plan': {'append': 451, 'update': 2, 'conflict': 2},
    'verified_append_rows': 50,
    'append_value_mismatches': 0,
    'duplicate_rows': 0,
    'routing_mismatches': 0,
    'protected_cell_mutations': 0,
    'date_only_format_exceptions': 12,
    'date_only_format_exceptions_approved': True,
    'updates_disposition': 'RECOMPUTE_WITH_NEW_PREVIEW',
}
_PARTIAL_RECONCILIATION_SECOND_EVIDENCE = {
    'initial_plan': {'append': 401, 'update': 2, 'conflict': 2},
    'verified_append_rows': 50,
    'verified_append_by_tab': {'ФОП': 46, 'ЮО': 4},
    'append_value_mismatches': 0,
    'duplicate_rows': 0,
    'routing_mismatches': 0,
    'protected_cell_mutations': 0,
    'formula_a_v1_2_matches': 50,
    'date_only_midnight_matches': 14,
    'blank_source_sheet_blank_rows': 36,
    'blank_sheet_source_date_state': {'empty_string': 36},
    'blank_sheet_source_precision_state': {'missing': 36},
    'required_diagnostic': 'pqm_sandbox_second_partial_apply_read_only_v3',
    'updates_disposition': 'UNVERIFIED_NO_HISTORIC_PLAN',
}
PARTIAL_RECONCILIATION_PROFILES = {
    _PARTIAL_RECONCILIATION_FIRST_FINGERPRINT: {
        'evidence': _PARTIAL_RECONCILIATION_FIRST_EVIDENCE,
        'result_counts': {
            'verified_append_rows': 50,
            'unverified_original_updates': 2,
            'accepted_date_only_formats': 12,
        },
    },
    _PARTIAL_RECONCILIATION_SECOND_FINGERPRINT: {
        'evidence': _PARTIAL_RECONCILIATION_SECOND_EVIDENCE,
        'result_counts': {
            'verified_append_rows': 50,
            'unverified_original_updates': 2,
            'verified_date_only_rows': 14,
            'blank_source_sheet_blank_rows': 36,
        },
    },
}
# Backward-compatible aliases for the first reconciliation profile.
PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT = _PARTIAL_RECONCILIATION_FIRST_FINGERPRINT
PARTIAL_RECONCILIATION_EVIDENCE = _PARTIAL_RECONCILIATION_FIRST_EVIDENCE


def partial_reconciliation_profile(request_fingerprint):
    """Return a fixed, Sandbox-only evidence profile; never accept caller-defined evidence."""
    return PARTIAL_RECONCILIATION_PROFILES.get(request_fingerprint)


RENDER_SECRET_DIR = Path('/etc/secrets')
RENDER_SECRET_VERSION_POINTER = '..data'
RENDER_SECRET_VERSION_DIR_RE = re.compile(r'\.\.[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}\.[0-9]+')


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
    """Read a direct secret link or Render's pinned ..data/versioned-dir projection."""
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
        version_pointer_before = None
        version_pointer_text = None
        versioned_target = target_text == f'{RENDER_SECRET_VERSION_POINTER}/{link_name}'
        if versioned_target:
            version_pointer_before = os.stat(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd,
                                             follow_symlinks=False)
            if not stat.S_ISLNK(version_pointer_before.st_mode):
                raise ValueError('Render Secret version pointer is not a symlink')
            version_pointer_text = os.readlink(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd)
            if (not RENDER_SECRET_VERSION_DIR_RE.fullmatch(version_pointer_text) or
                    '/' in version_pointer_text or '\\' in version_pointer_text):
                raise ValueError('Render Secret version pointer target rejected')
            parts = [version_pointer_text, link_name]
        else:
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
        if versioned_target:
            version_pointer_after = os.stat(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd,
                                            follow_symlinks=False)
            if ((version_pointer_before.st_dev, version_pointer_before.st_ino) !=
                    (version_pointer_after.st_dev, version_pointer_after.st_ino) or
                    not stat.S_ISLNK(version_pointer_after.st_mode) or
                    os.readlink(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd) != version_pointer_text):
                raise ValueError('Render Secret version pointer changed while reading')
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


class ExecutionPreflightError(ExecutionConfigurationError):
    """Known rejection before the Apps Script Execution API was called."""


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

    def invoke(self, action, request_id, actor, *, trigger='manual', digest=None, plan_scope='ALL',
               manual_authorized=False, reconciliation_id=None,
               request_fingerprint=None, evidence=None, chunk_index=0,
               expected_checkpoint_digest=None):
        manual_override = (manual_authorized is True and trigger == 'manual' and
                           isinstance(actor, str) and bool(actor.strip()))
        if background_jobs.disabled() and not manual_override:
            raise ExecutionConfigurationError('Background jobs disabled')
        self.validate()
        if action not in {'preview', 'apply', 'resume_check', 'reconcile_partial'} or trigger not in {'manual', 'scheduled'}:
            raise ValueError('Unsupported execution action')
        if not re.fullmatch(r'[0-9a-f]{32}', request_id) or not actor or len(actor) > 128:
            raise ValueError('Invalid execution identity')
        if action == 'apply' and not is_canonical_sha256_b64url(digest):
            raise ValueError('Reviewed Preview digest required')
        if action == 'apply' and (plan_scope not in {'ALL','APPEND_ONLY'} or
                (self.environment != 'SANDBOX' and plan_scope != 'ALL')):
            raise ValueError('Unsupported Apply scope for this environment')
        checkpoint_apply = action == 'apply' and checkpoint_apply_enabled(self.environment)
        if action == 'apply' and plan_scope == 'APPEND_ONLY' and not checkpoint_apply:
            raise ExecutionConfigurationError('APPEND_ONLY requires the Sandbox checkpoint protocol')
        checkpoint_protocol = (checkpoint_apply_enabled(self.environment) and action=='apply') or (
            self.environment=='SANDBOX' and checkpoint_apply_enabled(self.environment) and action=='resume_check')
        if action == 'resume_check' and (not checkpoint_protocol or trigger!='manual' or
                manual_override is not True or plan_scope!='APPEND_ONLY' or
                not is_canonical_sha256_b64url(digest) or
                not is_canonical_sha256_b64url(expected_checkpoint_digest)):
            raise ValueError('Sandbox APPEND_ONLY resume preflight is invalid')
        if checkpoint_apply and (type(chunk_index) is not int or not 0 <= chunk_index <= 499):
            raise ValueError('Invalid Apply checkpoint index')
        if checkpoint_protocol and action == 'apply' and self.environment=='SANDBOX':
            if (type(chunk_index) is not int or not 0 <= chunk_index <= 499 or
                    (chunk_index == 0 and expected_checkpoint_digest is not None) or
                    (chunk_index > 0 and not is_canonical_sha256_b64url(expected_checkpoint_digest))):
                raise ValueError('Apply checkpoint receipt binding is required')
        evidence_digest = None
        reconciliation_profile = None
        if action == 'reconcile_partial':
            if trigger != 'manual' or manual_override is not True:
                raise ValueError('Partial reconciliation is manual-admin only')
            reconciliation_profile = partial_reconciliation_profile(request_fingerprint)
            if (not isinstance(reconciliation_id, str) or
                    not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id) or
                    reconciliation_profile is None or
                    evidence != reconciliation_profile['evidence']):
                raise ValueError('Partial reconciliation evidence or identity rejected')
            evidence_raw = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            evidence_digest = base64.urlsafe_b64encode(
                hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode('ascii').rstrip('=')
        script, sheet, function = IDENTITIES[self.environment]
        issued = int(self.clock().timestamp())
        message = {'environment':self.environment, 'scriptId':script, 'spreadsheetId':sheet,
                   'contract':CONTRACT, 'action':action, 'requestId':request_id,
                   'actor':actor, 'trigger':trigger, 'issuedAt':issued, 'expiresAt':issued+300,
                   'expectedDigest':digest}
        if checkpoint_protocol:
            message['chunkIndex'] = chunk_index
            if self.environment=='SANDBOX': message['planScope'] = plan_scope
            if expected_checkpoint_digest is not None:
                message['expectedCheckpointDigest'] = expected_checkpoint_digest
        if action == 'reconcile_partial':
            message.update(reconciliationId=reconciliation_id,
                           requestFingerprint=request_fingerprint,
                           evidence=evidence, evidenceDigest=evidence_digest)
        raw = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        signature = base64.urlsafe_b64encode(hmac.new(self.shared_secret.encode(), raw.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        try:
            token = self.token_provider(self.environment)
            if (token.get('environment') != self.environment or
                    not PROJECT_SCOPES.issubset(set(token.get('scopes', []))) or
                    float(token.get('expires_at', 0)) - self.clock().timestamp() <= 400 or
                    not token.get('access_token')):
                raise ValueError('OAuth token preflight rejected')
            body = {'function':function, 'devMode':False,
                    'parameters':[{'payload':raw, 'signature':signature}]}
            # Current Google reference names this path parameter deploymentId.
            request = urllib.request.Request(
                'https://script.googleapis.com/v1/scripts/' + self.deployment_id + ':run',
                data=json.dumps(body).encode(), method='POST',
                headers={'Authorization':'Bearer '+token['access_token'], 'Content-Type':'application/json'})
        except Exception:
            raise ExecutionPreflightError('Execution preflight rejected; Apps Script was not called') from None
        try:
            with self.opener(request, timeout=390) as response:
                data = json.loads(response.read(1024*1024).decode())
        except ExecutionConfigurationError:
            raise ExecutionPreflightError('Execution transport preflight rejected; Apps Script was not called') from None
        except Exception:
            if action == 'resume_check':
                raise ExecutionPreflightError('Read-only checkpoint preflight unavailable; no write was requested') from None
            raise ExecutionOutcomeUnknown('Execution outcome unknown; no automatic retry') from None
        if data.get('done') is not True or 'error' in data:
            if action == 'resume_check':
                raise ExecutionPreflightError('Read-only checkpoint preflight rejected; no write was requested')
            raise ExecutionOutcomeUnknown('Execution did not return a verified completion; reconciliation required')
        result = data.get('response', {}).get('result', {})
        if (not isinstance(result, dict) or result.get('environment') != self.environment or
                result.get('scriptId') != script or result.get('spreadsheetId') != sheet or
                result.get('contract') != CONTRACT or result.get('requestId') != request_id):
            if action == 'resume_check':
                raise ExecutionPreflightError('Read-only checkpoint identity rejected; no write was requested')
            raise ExecutionOutcomeUnknown('Execution response identity mismatch; reconciliation required')
        if action == 'preview' and not is_canonical_sha256_b64url(result.get('digest')):
            raise ExecutionOutcomeUnknown('Invalid Preview receipt')
        plan_details = None
        if action == 'preview' and self.environment == 'SANDBOX':
            plan_details = result.get('planDetails')
            if (not isinstance(plan_details,dict) or plan_details.get('version') != 1 or
                    plan_details.get('environment') != 'SANDBOX' or
                    plan_details.get('plan_digest') != result.get('digest') or
                    not is_canonical_sha256_b64url(plan_details.get('append_only_digest')) or
                    not isinstance(plan_details.get('appends'),list) or
                    not isinstance(plan_details.get('updates'),list) or
                    not isinstance(plan_details.get('conflicts'),list) or
                    not isinstance(plan_details.get('errors'),list) or
                    not isinstance(plan_details.get('counts'),dict)):
                raise ExecutionOutcomeUnknown('Invalid Sandbox Preview detail receipt')
            if (len(plan_details['appends']) != int(result.get('counts',{}).get('append',-1)) or
                    len(plan_details['updates']) != int(result.get('counts',{}).get('update',-1)) or
                    len(plan_details['conflicts']) != int(result.get('counts',{}).get('conflict',-1)) or
                    len(plan_details['errors']) != int(result.get('counts',{}).get('error',-1)) or
                    any(plan_details['counts'].get(key)!=result.get('counts',{}).get(key)
                        for key in ('append','update','conflict','error'))):
                raise ExecutionOutcomeUnknown('Sandbox Preview detail counts mismatch')
            if len(json.dumps(plan_details,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')) > 750_000:
                raise ExecutionOutcomeUnknown('Sandbox Preview detail payload exceeds safe bound')
        if action == 'apply' and checkpoint_apply_enabled(self.environment):
            if (result.get('digest') != digest or type(result.get('chunkIndex')) is not int or
                    result.get('chunkIndex') != chunk_index or
                    type(result.get('nextChunk')) is not int or result.get('nextChunk') != chunk_index + 1 or
                    type(result.get('more')) is not bool or
                    (self.environment=='SANDBOX' and not is_canonical_sha256_b64url(result.get('checkpointDigest'))) or
                    result.get('phase') not in {'append','update'} or
                    result.get('status') not in {'APPLY_CHUNK_VERIFIED','COMPLETE','COMPLETE_WITH_CONFLICTS'} or
                    (self.environment == 'SANDBOX' and result.get('planScope') != plan_scope) or
                    (result.get('status') == 'APPLY_CHUNK_VERIFIED') != result.get('more')):
                raise ExecutionOutcomeUnknown('Invalid Apply checkpoint receipt')
        resume_details = None
        if action == 'resume_check':
            resume_details = result.get('planDetails')
            counts = result.get('counts', {})
            if (result.get('status')!='RESUME_READY' or result.get('digest')!=digest or
                    result.get('planScope')!='APPEND_ONLY' or result.get('chunkIndex')!=chunk_index or
                    result.get('nextChunk')!=chunk_index or
                    result.get('checkpointDigest')!=expected_checkpoint_digest or
                    not isinstance(resume_details,dict) or resume_details.get('version')!=1 or
                    resume_details.get('environment')!='SANDBOX' or
                    resume_details.get('plan_digest')!=digest or
                    not is_canonical_sha256_b64url(resume_details.get('remaining_plan_digest')) or
                    not isinstance(resume_details.get('appends'),list) or not resume_details['appends'] or
                    resume_details.get('updates')!=[] or
                    not isinstance(resume_details.get('conflicts'),list) or
                    not isinstance(resume_details.get('errors'),list) or
                    counts.get('append')!=len(resume_details['appends']) or counts.get('update')!=0 or
                    counts.get('append')<=0):
                raise ExecutionPreflightError('Read-only checkpoint receipt rejected; no write was requested')
        if action == 'reconcile_partial' and (
                result.get('status') != 'RECONCILED_PARTIAL' or
                result.get('reconciliationId') != reconciliation_id or
                result.get('requestFingerprint') != request_fingerprint or
                result.get('evidenceDigest') != evidence_digest or
                not is_canonical_sha256_b64url(result.get('digest'))):
            raise ExecutionOutcomeUnknown('Invalid partial reconciliation receipt')
        # Return only technical receipts/counters; never remote errors, stack traces or secrets.
        safe = {key:result.get(key) for key in ('environment','scriptId','spreadsheetId','contract','requestId','status','digest')}
        counters = result.get('counts', {})
        if not isinstance(counters, dict) or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 or v != int(v) for v in counters.values()):
            raise ExecutionOutcomeUnknown('Invalid execution counters')
        safe['counts'] = {k:int(v) for k,v in counters.items() if k in {'append','update','conflict','error','remaining_safe','batches','skipped'}}
        if action == 'apply' and checkpoint_apply_enabled(self.environment):
            safe.update(chunkIndex=chunk_index,nextChunk=result['nextChunk'],more=result['more'],phase=result.get('phase'))
            if self.environment == 'SANDBOX':
                safe['planScope'] = plan_scope
                safe['checkpointDigest'] = result['checkpointDigest']
        if action == 'resume_check':
            safe.update(planScope='APPEND_ONLY',chunkIndex=chunk_index,nextChunk=result['nextChunk'],
                        checkpointDigest=result['checkpointDigest'],planDetails=resume_details)
        if action == 'preview' and plan_details is not None:
            safe['planDetails'] = plan_details
        if action == 'reconcile_partial':
            safe.update(reconciliationId=reconciliation_id,
                        requestFingerprint=request_fingerprint,
                        evidenceDigest=evidence_digest)
        return safe


def request_id_fingerprint(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
        raise ValueError('Invalid request identity')
    return hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:24]


def _preview_details_raw(details):
    return json.dumps(details,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _preview_details_digest(details):
    return base64.urlsafe_b64encode(hashlib.sha256(_preview_details_raw(details).encode('utf-8')).digest()).decode('ascii').rstrip('=')


def store_preview_plan(path, request_id, actor, details, *, now=None):
    """Persist one immutable Sandbox Preview snapshot for read-only inspection and scoped tickets."""
    if (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id) or
            not isinstance(actor,str) or not actor.strip() or len(actor)>128 or
            not isinstance(details,dict) or details.get('environment')!='SANDBOX' or
            details.get('version')!=1 or not is_canonical_sha256_b64url(details.get('plan_digest')) or
            not is_canonical_sha256_b64url(details.get('append_only_digest')) or
            not isinstance(details.get('appends'),list) or not isinstance(details.get('updates'),list) or
            not isinstance(details.get('conflicts'),list) or not isinstance(details.get('errors'),list) or
            not isinstance(details.get('counts'),dict)):
        raise ValueError('Sandbox Preview snapshot rejected')
    counts=details['counts']
    append_columns={'A','B','C','D','E','F','H','I','L'}
    update_columns={'C','D','E','F','H','I','L'}
    if (any(type(counts.get(key)) is not int or counts.get(key)<0
            for key in ('append','update','conflict','error')) or
            counts.get('append')!=len(details['appends']) or counts.get('update')!=len(details['updates']) or
            counts.get('conflict')!=len(details['conflicts']) or counts.get('error')!=len(details['errors']) or
            any(not isinstance(item,dict) or item.get('operation')!='APPEND' or
                not isinstance(item.get('cells'),list) or
                any(not isinstance(cell,dict) or cell.get('column') not in append_columns for cell in item['cells']) or
                not any(cell.get('column')=='A' and cell.get('formula') is True for cell in item['cells'])
                for item in details['appends']) or
            any(not isinstance(item,dict) or item.get('operation')!='UPDATE' or
                not isinstance(item.get('cells'),list) or
                any(not isinstance(cell,dict) or cell.get('column') not in update_columns for cell in item['cells'])
                for item in details['updates'])):
        raise ValueError('Sandbox Preview snapshot operations or counts mismatch')
    raw=_preview_details_raw(details)
    if len(raw.encode('utf-8'))>PREVIEW_DETAIL_MAX_BYTES:
        raise ValueError('Sandbox Preview snapshot exceeds safe storage bound')
    digest=_preview_details_digest(details)
    stamp=int((now or datetime.now(timezone.utc)).timestamp())
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('DELETE FROM google_writer_preview_plans WHERE expires_at<=?',(stamp,))
        try:
            con.execute('''INSERT INTO google_writer_preview_plans(
                request_id,environment,actor,plan_digest,append_only_digest,details_digest,details_json,created_at,expires_at)
                VALUES(?,'SANDBOX',?,?,?,?,?,?,?)''',
                (request_id,actor,details['plan_digest'],details['append_only_digest'],digest,raw,stamp,
                 stamp+PREVIEW_PLAN_TTL_SECONDS))
        except sqlite3.IntegrityError:
            raise ValueError('Sandbox Preview request identity already has a snapshot') from None
    return {'details_digest':digest,'expires_at':stamp+PREVIEW_PLAN_TTL_SECONDS}


def load_preview_plan(path, request_id, actor, plan_digest, *, details_digest=None, now=None):
    if (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id) or
            not isinstance(actor,str) or not is_canonical_sha256_b64url(plan_digest) or
            (details_digest is not None and not is_canonical_sha256_b64url(details_digest))):
        raise ValueError('Sandbox Preview snapshot identity rejected')
    stamp=int((now or datetime.now(timezone.utc)).timestamp())
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        con.row_factory=sqlite3.Row
        row=con.execute('''SELECT environment,actor,plan_digest,append_only_digest,details_digest,details_json,expires_at
            FROM google_writer_preview_plans WHERE request_id=?''',(request_id,)).fetchone()
    if (not row or row['environment']!='SANDBOX' or row['actor']!=actor or
            row['plan_digest']!=plan_digest or row['expires_at']<=stamp or
            (details_digest is not None and row['details_digest']!=details_digest)):
        raise ValueError('Sandbox Preview snapshot missing, stale or unauthorized')
    try: details=json.loads(row['details_json'])
    except (TypeError,json.JSONDecodeError): raise ValueError('Sandbox Preview snapshot invalid') from None
    if (_preview_details_digest(details)!=row['details_digest'] or
            details.get('plan_digest')!=row['plan_digest'] or
            details.get('append_only_digest')!=row['append_only_digest']):
        raise ValueError('Sandbox Preview snapshot integrity mismatch')
    return {'details':details,'details_digest':row['details_digest'],
            'plan_digest':row['plan_digest'],'append_only_digest':row['append_only_digest'],
            'expires_at':row['expires_at']}


def validate_preview_plan_scope(snapshot, ticket):
    """Fail-closed binding check shared by full and APPEND_ONLY Sandbox Apply routes."""
    if not isinstance(snapshot,dict) or not isinstance(ticket,dict):
        raise ValueError('Sandbox Preview scope rejected')
    details=snapshot.get('details')
    counts=details.get('counts') if isinstance(details,dict) else None
    appends=details.get('appends') if isinstance(details,dict) else None
    updates=details.get('updates') if isinstance(details,dict) else None
    if (not isinstance(details,dict) or not isinstance(counts,dict) or
            not isinstance(appends,list) or not isinstance(updates,list) or
            details.get('environment')!='SANDBOX' or
            details.get('version')!=1 or snapshot.get('plan_digest')!=details.get('plan_digest') or
            ticket.get('environment')!='SANDBOX' or ticket.get('parent_digest')!=snapshot.get('plan_digest') or
            ticket.get('details_digest')!=snapshot.get('details_digest') or
            counts.get('append')!=len(appends) or counts.get('update')!=len(updates)):
        raise ValueError('Sandbox Preview scope binding mismatch')
    scope=ticket.get('scope')
    if scope=='ALL':
        if ticket.get('digest')!=snapshot.get('plan_digest'):
            raise ValueError('Full Preview digest mismatch')
        return {'scope':'ALL','append':len(appends),'update':len(updates),
                'conflict':counts.get('conflict',0),'error':counts.get('error',0)}
    if scope!='APPEND_ONLY' or ticket.get('digest')!=snapshot.get('append_only_digest'):
        raise ValueError('APPEND_ONLY Preview digest mismatch')
    if (not isinstance(appends,list) or
            any(not isinstance(item,dict) or item.get('operation')!='APPEND' or
                not isinstance(item.get('cells'),list) or
                not any(isinstance(cell,dict) and cell.get('column')=='A' and cell.get('formula') is True
                        for cell in item['cells']) for item in appends)):
        raise ValueError('APPEND_ONLY snapshot contains an invalid operation')
    # UPDATEs remain visible in the parent detail snapshot but are deliberately
    # excluded from the scoped operation count and are never sent to Apps Script.
    return {'scope':'APPEND_ONLY','append':len(appends),'update':0,
            'conflict':counts.get('conflict',0),'error':counts.get('error',0)}


def _reconciliation_time(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Aware reconciliation clock required')
    return value.astimezone(timezone.utc).isoformat()


def prepare_partial_reconciliation(path, environment, reconciliation_id,
                                   request_fingerprint, actor, *, now=None):
    """Persist a fail-closed reconciliation intent without releasing the unknown-run hold."""
    if environment != 'SANDBOX':
        raise PermissionError('Partial reconciliation is Sandbox-only')
    if (not isinstance(reconciliation_id, str) or
            not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id) or
            partial_reconciliation_profile(request_fingerprint) is None or
            not isinstance(actor, str) or not actor.strip() or len(actor) > 128):
        raise ValueError('Partial reconciliation identity rejected')
    reconciliation_profile = partial_reconciliation_profile(request_fingerprint)
    evidence = reconciliation_profile['evidence']
    stamp = _reconciliation_time(now)
    evidence_raw = json.dumps(evidence, ensure_ascii=False,
                              sort_keys=True, separators=(',', ':'))
    evidence_digest = base64.urlsafe_b64encode(
        hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode('ascii').rstrip('=')
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory = sqlite3.Row
        known = con.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                            ('table', 'google_writer_run_reconciliations')).fetchone()
        if not known:
            raise RuntimeError('Reconciliation storage is not initialized')
        existing = con.execute('''SELECT reconciliation_id,request_id,environment,actor,
                                         request_fingerprint,evidence_digest,evidence_json,state
                                  FROM google_writer_run_reconciliations
                                  WHERE request_fingerprint=? OR reconciliation_id=?''',
                               (request_fingerprint, reconciliation_id)).fetchall()
        if existing:
            if len(existing) != 1:
                raise RuntimeError('Conflicting reconciliation history exists')
            prior = existing[0]
            if (prior['reconciliation_id'],prior['environment'],prior['actor'],
                    prior['request_fingerprint'],prior['evidence_digest'],prior['evidence_json']) != (
                    reconciliation_id,'SANDBOX',actor,request_fingerprint,
                    evidence_digest,evidence_raw):
                raise RuntimeError('Existing reconciliation does not match this retry')
            if prior['state'] not in {'prepared','reconciled_partial'}:
                raise RuntimeError('Reconciliation history is in an unknown state')
            run = con.execute('''SELECT status,result_json FROM google_writer_runs
                                 WHERE request_id=? AND environment='SANDBOX' ''',
                              (prior['request_id'],)).fetchone()
            if prior['state'] == 'prepared':
                unknown = con.execute('''SELECT request_id,status,result_json FROM google_writer_runs
                                         WHERE environment='SANDBOX' AND status='outcome_unknown' ''').fetchall()
                running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
                if (not run or run['status'] != 'outcome_unknown' or
                        run['result_json'] != '{"status": "OUTCOME_UNKNOWN_HOLD_NO_RETRY"}' or
                        len(unknown) != 1 or unknown[0]['request_id'] != prior['request_id'] or running):
                    raise RuntimeError('Prepared reconciliation no longer matches the blocked run')
            elif (not run or run['status'] != 'partial' or
                    json.loads(run['result_json']).get('reconciliation_id') != reconciliation_id):
                raise RuntimeError('Completed reconciliation conflicts with SQLite run state')
            return {'request_id': prior['request_id'], 'reconciliation_id': reconciliation_id,
                    'request_fingerprint': request_fingerprint, 'evidence_digest': evidence_digest,
                    'evidence': evidence, 'state': prior['state'], 'idempotent': True}
        unknown = con.execute('''SELECT request_id,environment,trigger,actor,revision,started_at,
                                      finished_at,status,result_json
                                 FROM google_writer_runs
                                 WHERE environment='SANDBOX' AND status='outcome_unknown'
                                 ORDER BY started_at''').fetchall()
        running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if len(unknown) != 1 or running != 0:
            raise RuntimeError('Sandbox run state is not uniquely reconcilable')
        row = unknown[0]
        if request_id_fingerprint(row['request_id']) != request_fingerprint:
            raise PermissionError('Sandbox request fingerprint mismatch')
        if row['trigger'] != 'manual' or row['result_json'] != '{"status": "OUTCOME_UNKNOWN_HOLD_NO_RETRY"}':
            raise RuntimeError('Sandbox run record does not match the confirmed partial-run contract')
        con.execute('''INSERT INTO google_writer_run_reconciliations(
                         reconciliation_id,request_id,environment,actor,request_fingerprint,
                         evidence_digest,evidence_json,state,prepared_at,original_status,
                         original_result_json,original_actor,original_trigger,original_revision,original_started_at)
                       VALUES(?,?,?,?,?,?,?,'prepared',?,?,?,?,?,?,?)''',
                    (reconciliation_id,row['request_id'],'SANDBOX',actor,request_fingerprint,
                     evidence_digest,evidence_raw,stamp,row['status'],row['result_json'],
                     row['actor'],row['trigger'],row['revision'],row['started_at']))
        return {'request_id': row['request_id'], 'reconciliation_id': reconciliation_id,
                'request_fingerprint': request_fingerprint, 'evidence_digest': evidence_digest,
                'evidence': evidence,
                'state': 'prepared', 'idempotent': False}


def finalize_partial_reconciliation(path, reconciliation_id, actor, receipt, *, now=None):
    """Release the SQLite hold only after a verified Apps Script reconciliation receipt."""
    if not isinstance(reconciliation_id, str) or not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id):
        raise ValueError('Invalid reconciliation identity')
    stamp = _reconciliation_time(now)
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory = sqlite3.Row
        audit = con.execute('SELECT * FROM google_writer_run_reconciliations WHERE reconciliation_id=?',
                            (reconciliation_id,)).fetchone()
        if not audit or audit['environment'] != 'SANDBOX' or audit['actor'] != actor:
            raise PermissionError('Reconciliation audit identity mismatch')
        required = {
            'environment': 'SANDBOX', 'scriptId': IDENTITIES['SANDBOX'][0],
            'spreadsheetId': IDENTITIES['SANDBOX'][1], 'contract': CONTRACT,
            'requestId': audit['request_id'], 'status': 'RECONCILED_PARTIAL',
            'reconciliationId': reconciliation_id,
            'requestFingerprint': audit['request_fingerprint'],
            'evidenceDigest': audit['evidence_digest']
        }
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k,v in required.items()) or not is_canonical_sha256_b64url(receipt.get('digest')):
            raise PermissionError('Apps Script reconciliation receipt mismatch')
        if audit['state'] == 'reconciled_partial':
            run = con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment=?',
                              (audit['request_id'],'SANDBOX')).fetchone()
            if (not run or run['status'] != 'partial' or
                    json.loads(run['result_json']).get('reconciliation_id') != reconciliation_id):
                raise RuntimeError('Completed reconciliation history conflicts with run state')
            return {'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,'idempotent':True}
        if audit['state'] != 'prepared':
            raise RuntimeError('Reconciliation is not prepared')
        run = con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment=?',
                          (audit['request_id'],'SANDBOX')).fetchone()
        if (not run or run['status'] != 'outcome_unknown' or
                run['result_json'] != audit['original_result_json']):
            raise RuntimeError('Original unknown run changed after preparation')
        running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if running:
            raise RuntimeError('A Sandbox run is active during reconciliation')
        con.execute('''UPDATE google_writer_runs SET status='partial',finished_at=?,result_json=?
                       WHERE request_id=? AND environment='SANDBOX' AND status='outcome_unknown'
                         AND result_json=?''',
                    (stamp,json.dumps({'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,
                                       'evidence_digest':audit['evidence_digest'],
                                       'original_status':'outcome_unknown'},sort_keys=True),
                     audit['request_id'],audit['original_result_json']))
        if con.execute('SELECT changes()').fetchone()[0] != 1:
            raise RuntimeError('Sandbox unknown-run compare-and-set failed')
        con.execute('''UPDATE google_writer_run_reconciliations
                       SET state='reconciled_partial',finished_at=?,apps_script_receipt_json=?
                       WHERE reconciliation_id=? AND state='prepared' ''',
                    (stamp,json.dumps(receipt,sort_keys=True,separators=(',',':')),reconciliation_id))
        if con.execute('SELECT changes()').fetchone()[0] != 1:
            raise RuntimeError('Reconciliation history compare-and-set failed')
        return {'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,'idempotent':False}


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
      CREATE TABLE IF NOT EXISTS google_writer_run_reconciliations(
        reconciliation_id TEXT PRIMARY KEY CHECK(length(reconciliation_id)=32),
        request_id TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=24),
        evidence_digest TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('prepared','reconciled_partial')),
        prepared_at TEXT NOT NULL,
        finished_at TEXT,
        original_status TEXT NOT NULL,
        original_result_json TEXT NOT NULL,
        original_actor TEXT NOT NULL,
        original_trigger TEXT NOT NULL,
        original_revision INTEGER NOT NULL,
        original_started_at TEXT NOT NULL,
        apps_script_receipt_json TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE IF NOT EXISTS google_writer_preview_plans(
        request_id TEXT PRIMARY KEY CHECK(length(request_id)=32),
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        plan_digest TEXT NOT NULL CHECK(length(plan_digest)=43),
        append_only_digest TEXT NOT NULL CHECK(length(append_only_digest)=43),
        details_digest TEXT NOT NULL CHECK(length(details_digest)=43),
        details_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_google_writer_preview_plans_expiry
        ON google_writer_preview_plans(expires_at);
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
              manual_authorized=False, plan_scope='ALL', plan_digest=None, details_digest=None):
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'claimed': False, 'status': 'background_jobs_disabled'}
    if environment not in IDENTITIES or trigger not in {'manual','scheduled'} or not re.fullmatch('[0-9a-f]{32}',request_id):
        raise ValueError('Invalid run identity')
    if (plan_scope not in {'ALL','APPEND_ONLY'} or
            (environment != 'SANDBOX' and plan_scope != 'ALL') or
            (plan_digest is not None and not is_canonical_sha256_b64url(plan_digest))):
        raise ValueError('Invalid run plan scope')
    if not Path(path).is_file(): raise ValueError('Existing execution database required')
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT environment,actor,trigger,status,result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old[:3] != (environment,actor,trigger): raise PermissionError('Run identity reuse rejected')
            try: prior_meta=json.loads(old[4] or '{}')
            except (TypeError,json.JSONDecodeError): prior_meta={}
            if (prior_meta.get('plan_scope', 'ALL') != plan_scope or
                    (plan_digest is not None and prior_meta.get('plan_digest') not in (None,plan_digest))):
                raise PermissionError('Run plan scope or digest reuse rejected')
            return {'claimed':False,'status':old[3],'result':json.loads(old[4])}
        if environment=='SANDBOX':
            resumable=con.execute("SELECT request_id,actor,result_json FROM google_writer_runs WHERE environment='SANDBOX' AND status='partial'").fetchall()
            for candidate in resumable:
                try: saved=json.loads(candidate[2] or '{}')
                except (TypeError,json.JSONDecodeError): saved={}
                if (saved.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                        saved.get('plan_scope')=='APPEND_ONLY' and
                        not saved.get('outcome_unknown') and not saved.get('attempted_chunk')):
                    return {'claimed':False,'status':'append_only_resume_required'}
        config = settings(con)
        if trigger == 'scheduled' and (not config['enabled'] or revision != config['revision']):
            return {'claimed':False,'status':'schedule_changed'}
        try:
            if environment=='SANDBOX' and details_digest is not None and not is_canonical_sha256_b64url(details_digest):
                raise ValueError('Invalid Preview detail digest')
            initial_result=(json.dumps({'plan_scope':plan_scope,'plan_digest':plan_digest,
                'details_digest':details_digest},sort_keys=True)
                if environment=='SANDBOX' else '{}')
            con.execute('INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,started_at,status,result_json) VALUES(?,?,?,?,?,?,?,?)',
                        (request_id,environment,trigger,actor,config['revision'],(now or datetime.now(timezone.utc)).isoformat(),'running',initial_result))
        except sqlite3.IntegrityError:
            return {'claimed':False,'status':'another_run_or_unknown_outcome'}
        return {'claimed':True,'status':'running'}


def load_append_only_resume_candidate(path, request_id, actor):
    if not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or not actor:
        raise ValueError('Invalid continuation identity')
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        row=con.execute('''SELECT environment,actor,trigger,status,result_json FROM google_writer_runs
          WHERE request_id=?''',(request_id,)).fetchone()
    if not row or row[0]!='SANDBOX' or row[1]!=actor or row[2]!='manual' or row[3]!='partial':
        raise ValueError('No resumable Sandbox APPEND_ONLY run')
    try: progress=json.loads(row[4] or '{}')
    except (TypeError,json.JSONDecodeError): raise ValueError('Saved continuation checkpoint is invalid') from None
    if (not isinstance(progress,dict) or progress.get('status')!='HALTED_AFTER_VERIFIED_CHECKPOINTS' or
            progress.get('plan_scope')!='APPEND_ONLY' or progress.get('outcome_unknown') or
            progress.get('attempted_chunk') is not None or type(progress.get('next_chunk')) is not int or
            progress['next_chunk']<1 or progress.get('last_verified_chunk')!=progress['next_chunk']-1 or
            progress.get('checkpoint_digest') is None or
            not is_canonical_sha256_b64url(progress.get('checkpoint_digest')) or
            not is_canonical_sha256_b64url(progress.get('plan_digest')) or
            not isinstance(progress.get('verified_totals'),dict) or
            type(progress['verified_totals'].get('append')) is not int or
            progress['verified_totals']['append']<1 or
            progress['verified_totals'].get('update')!=0):
        raise ValueError('Saved continuation checkpoint is incomplete or uncertain')
    return {'request_id':request_id,'actor':actor,'plan_digest':progress['plan_digest'],
            'next_chunk':progress['next_chunk'],'checkpoint_digest':progress['checkpoint_digest'],
            'verified_totals':progress['verified_totals'],'details_digest':progress.get('details_digest')}


def claim_append_only_resume(path, candidate, *, now=None):
    request_id=candidate.get('request_id') if isinstance(candidate,dict) else None
    actor=candidate.get('actor') if isinstance(candidate,dict) else None
    if (not isinstance(candidate,dict) or not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not actor or not is_canonical_sha256_b64url(candidate.get('plan_digest')) or
            not is_canonical_sha256_b64url(candidate.get('checkpoint_digest')) or
            type(candidate.get('next_chunk')) is not int or candidate['next_chunk']<1):
        raise ValueError('Invalid APPEND_ONLY resume claim')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT environment,actor,trigger,status,result_json FROM google_writer_runs WHERE request_id=?",
                        (request_id,)).fetchone()
        if not row or row[:4]!=('SANDBOX',actor,'manual','partial'):
            return {'claimed':False,'status':'resume_state_changed'}
        active=con.execute("SELECT request_id FROM google_writer_runs WHERE environment='SANDBOX' AND status IN ('running','outcome_unknown') AND request_id<>? LIMIT 1",
                           (request_id,)).fetchone()
        if active:
            return {'claimed':False,'status':'another_run_or_unknown_outcome'}
        try: progress=json.loads(row[4] or '{}')
        except (TypeError,json.JSONDecodeError): return {'claimed':False,'status':'resume_checkpoint_invalid'}
        if (progress.get('status')!='HALTED_AFTER_VERIFIED_CHECKPOINTS' or
                progress.get('plan_scope')!='APPEND_ONLY' or progress.get('outcome_unknown') or
                progress.get('next_chunk')!=candidate['next_chunk'] or
                progress.get('plan_digest')!=candidate['plan_digest'] or
                progress.get('checkpoint_digest')!=candidate['checkpoint_digest']):
            return {'claimed':False,'status':'resume_checkpoint_changed'}
        progress=progress|{'status':'APPEND_ONLY_RESUME_CLAIMED',
                           'resume_attempts':int(progress.get('resume_attempts',0))+1,
                           'resume_claimed_at':(now or datetime.now(timezone.utc)).isoformat()}
        updated=con.execute("UPDATE google_writer_runs SET status='running',finished_at=NULL,result_json=? WHERE request_id=? AND status='partial'",
                            (json.dumps(progress,sort_keys=True),request_id))
        if updated.rowcount!=1: return {'claimed':False,'status':'resume_claim_race'}
    return {'claimed':True,'status':'running'}


def finish_run(path, request_id, status, result):
    if status not in {'complete','partial','failed_safe','outcome_unknown'}: raise ValueError('Unknown run status')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute("UPDATE google_writer_runs SET status=?,finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (status,datetime.now(timezone.utc).isoformat(),json.dumps(result),request_id))


def checkpoint_run(path, request_id, step_result):
    """Persist only a remotely verified chunk receipt while the run remains held."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        if not row or row[0] != 'running':
            raise RuntimeError('Apply checkpoint no longer owns its run')
        previous=json.loads(row[1] or '{}')
        totals=previous.get('verified_totals',{'append':0,'update':0,'batches':0})
        for key in ('append','update','batches'):
            totals[key]=int(totals.get(key,0))+int(step_result.get('counts',{}).get(key,0))
        if (not is_canonical_sha256_b64url(step_result.get('checkpointDigest')) or
                step_result.get('planScope')!=previous.get('plan_scope','ALL') or
                (previous.get('plan_scope')=='APPEND_ONLY' and step_result.get('counts',{}).get('update',0)!=0)):
            raise RuntimeError('Apply checkpoint receipt was incomplete or outside its plan scope')
        progress={'status':'APPLY_PROGRESS_CHECKPOINTED','next_chunk':step_result['nextChunk'],
                  'last_verified_chunk':step_result['chunkIndex'],'last_phase':step_result.get('phase'),
                  'last_step_counts':step_result.get('counts',{}),'verified_totals':totals,
                  'plan_digest':step_result.get('digest'), 'plan_scope':previous.get('plan_scope','ALL'),
                  'checkpoint_digest':step_result['checkpointDigest'],
                  'details_digest':previous.get('details_digest'),
                  'resume_attempts':int(previous.get('resume_attempts',0))}
        con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=? AND status='running'",
                    (json.dumps(progress,sort_keys=True),request_id))


def hold_unknown_run(path, request_id, *, attempted_chunk, digest, checkpoint_digest=None):
    """Retain verified local checkpoints while holding an ambiguous remote step."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        if not row or row[0] != 'running':
            raise RuntimeError('Apply outcome hold no longer owns its run')
        previous=json.loads(row[1] or '{}')
        if not isinstance(previous,dict): previous={}
        held=previous|{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY',
            'outcome_unknown':True,'attempted_chunk':attempted_chunk,'plan_digest':digest,
            'attempted_checkpoint_digest':checkpoint_digest}
        con.execute("UPDATE google_writer_runs SET status='outcome_unknown',finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (datetime.now(timezone.utc).isoformat(),json.dumps(held,sort_keys=True),request_id))


def finish_partial_after_checkpoints(path, request_id, *, verified_chunks, next_chunk, digest):
    """Stop safely after verified work while retaining its durable progress record."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        if not row or row[0] != 'running':
            raise RuntimeError('Apply partial completion no longer owns its run')
        previous=json.loads(row[1] or '{}')
        if not isinstance(previous,dict): previous={}
        stopped=previous|{'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS',
            'verified_chunks':verified_chunks,'next_chunk':next_chunk,'plan_digest':digest}
        con.execute("UPDATE google_writer_runs SET status='partial',finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (datetime.now(timezone.utc).isoformat(),json.dumps(stopped,sort_keys=True),request_id))


def execute_claimed(path, client, request_id, actor, *, trigger='manual', digest=None,
                    guard=lambda:True, manual_authorized=False, plan_scope='ALL',
                    start_chunk=0, checkpoint_digest=None, max_append_chunks=4):
    """One common writer for manual and scheduled calls, no automatic retry."""
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'status': 'BACKGROUND_JOBS_DISABLED'}
    verified_steps=0
    chunk_index=start_chunk
    try:
        if not guard(): raise ExecutionConfigurationError('Execution guard changed before preview')
        if digest is None:
            digest = client.invoke('preview',request_id,actor,trigger=trigger,
                                   manual_authorized=manual_override)['digest']
        if not checkpoint_apply_enabled(getattr(client,'environment',None)):
            if (background_jobs.disabled() and not manual_override) or not guard():
                raise ExecutionConfigurationError('Execution guard changed before Apply')
            result=client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,
                                 manual_authorized=manual_override)
            status='complete' if result['status']=='COMPLETE' else 'partial' if result['status'] in {
                'COMPLETE_WITH_CONFLICTS','PARTIAL_SAFE_OPERATIONS_REMAIN'} else 'outcome_unknown'
            finish_run(path,request_id,status,result)
            return result
        while True:
            if (background_jobs.disabled() and not manual_override) or not guard():
                raise ExecutionConfigurationError('Execution guard changed before next Apply checkpoint')
            result = client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,
                                   plan_scope=plan_scope,manual_authorized=manual_override,chunk_index=chunk_index,
                                   expected_checkpoint_digest=checkpoint_digest)
            if result['status']=='APPLY_CHUNK_VERIFIED':
                checkpoint_run(path,request_id,result)
                verified_steps+=1
                chunk_index=result['nextChunk']
                checkpoint_digest=result['checkpointDigest']
                if plan_scope=='APPEND_ONLY' and verified_steps>=max_append_chunks and result['more']:
                    finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                        next_chunk=chunk_index,digest=digest)
                    return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                            'next_chunk':chunk_index,'checkpoint_digest':checkpoint_digest}
                continue
            status = 'complete' if result['status']=='COMPLETE' else 'partial'
            finish_run(path,request_id,status,result)
            return result
    except ExecutionPreflightError:
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL'})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL'}
    except ExecutionConfigurationError:
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL'})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL'}
    except ValueError:
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL'})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL'}
    except Exception:
        hold_unknown_run(path,request_id,attempted_chunk=chunk_index,digest=digest,
                         checkpoint_digest=checkpoint_digest)
        return {'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'}


def status(path, environment, *, available=False, running=False, heartbeat=None, actor=None, now=None):
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
    active_blocked=any(row['status'] in {'running','outcome_unknown'} for row in rows)
    # Unknown/active lanes are queried separately: an older hold must not be hidden by log limits.
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        try:
            active_blocked=bool(con.execute("SELECT 1 FROM google_writer_runs WHERE environment=? AND status IN ('running','outcome_unknown')",(environment,)).fetchone())
            resumable_rows=con.execute("SELECT request_id,actor,result_json FROM google_writer_runs WHERE environment='SANDBOX' AND status='partial'").fetchall() if environment=='SANDBOX' else []
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower(): raise
            resumable_rows=[]
    resumable=[]
    for request_id,run_actor,raw_result in resumable_rows:
        try: progress=json.loads(raw_result or '{}')
        except (TypeError,json.JSONDecodeError): progress={}
        if (progress.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                progress.get('plan_scope')=='APPEND_ONLY' and not progress.get('outcome_unknown') and
                progress.get('attempted_chunk') is None and type(progress.get('next_chunk')) is int and
                is_canonical_sha256_b64url(progress.get('checkpoint_digest'))):
            resumable.append((request_id,run_actor))
    resume_available=any(run_actor==actor for _,run_actor in resumable) if actor else bool(resumable)
    blocked=active_blocked or bool(resumable)
    for row in rows:
        row['resume_available']=any(request_id==row['request_id'] and run_actor==actor
                                    for request_id,run_actor in resumable) if actor else False
    enabled=bool(config['enabled'] and available and running and not blocked)
    return {'job':JOB,'enabled':enabled,'configured_enabled':bool(config['enabled']),'hour':config['hour'],'minute':config['minute'],
            'revision':config['revision'],'timezone':'Europe/Kyiv','schedule':f"Щодня о {config['hour']:02}:{config['minute']:02}",
            'next_run':next_slot(config,now).astimezone(KYIV).isoformat() if enabled else None,
            'registered':running,'running':running,'heartbeat_at':heartbeat,'manageable':True,
            'configuration_source':'runtime','last_started_at':last.get('started_at'),'last_finished_at':last.get('finished_at'),
            'last_status':last.get('status','never'),'blocked':blocked,'active_blocked':active_blocked,
            'resume_available':resume_available,'channel_ready':available,'runs':rows}


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


def preview_ticket(client,request_id,actor,digest,*,plan_scope='ALL',parent_digest=None,details_digest=None):
    if plan_scope not in {'ALL','APPEND_ONLY'}:
        raise ValueError('Invalid Preview plan scope')
    if client.environment!='SANDBOX' and (plan_scope!='ALL' or parent_digest is not None or details_digest is not None):
        raise ValueError('Scoped Preview tickets are Sandbox-only')
    if plan_scope=='APPEND_ONLY' and (
            not is_canonical_sha256_b64url(parent_digest) or
            not is_canonical_sha256_b64url(details_digest) or
            not is_canonical_sha256_b64url(digest)):
        raise ValueError('Append-only ticket binding is incomplete')
    value={'environment':client.environment,'request_id':request_id,'actor':actor,'digest':digest,
           'expires_at':int(client.clock().timestamp())+300}
    if client.environment=='SANDBOX' and details_digest is not None:
        if not is_canonical_sha256_b64url(details_digest) or not is_canonical_sha256_b64url(parent_digest or digest):
            raise ValueError('Sandbox Preview detail binding is invalid')
        value.update(scope=plan_scope,parent_digest=parent_digest or digest,details_digest=details_digest)
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
                not is_canonical_sha256_b64url(value['digest'])):
            raise ValueError('Ticket context mismatch')
        scope=value.get('scope','ALL')
        if scope not in {'ALL','APPEND_ONLY'} or (client.environment!='SANDBOX' and scope!='ALL'):
            raise ValueError('Ticket scope mismatch')
        if 'details_digest' in value and (
                client.environment!='SANDBOX' or
                not is_canonical_sha256_b64url(value.get('details_digest')) or
                not is_canonical_sha256_b64url(value.get('parent_digest'))):
            raise ValueError('Ticket detail binding mismatch')
        if scope=='APPEND_ONLY' and 'details_digest' not in value:
            raise ValueError('Append-only ticket lacks detail binding')
        value['scope']=scope
        return value
    except Exception:
        raise ValueError('Reviewed Preview ticket is invalid or expired') from None


def append_only_resume_ticket(client, request_id, actor, digest, next_chunk,
                              checkpoint_digest, details_digest):
    if (client.environment!='SANDBOX' or not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not actor or len(actor)>128 or not is_canonical_sha256_b64url(digest) or
            type(next_chunk) is not int or not 1<=next_chunk<=499 or
            not is_canonical_sha256_b64url(checkpoint_digest) or
            not is_canonical_sha256_b64url(details_digest)):
        raise ValueError('Append-only continuation ticket binding is invalid')
    issued=int(client.clock().timestamp())
    value={'environment':'SANDBOX','request_id':request_id,'actor':actor,'trigger':'manual',
           'action':'resume_append_only','scope':'APPEND_ONLY','digest':digest,
           'next_chunk':next_chunk,'checkpoint_digest':checkpoint_digest,
           'details_digest':details_digest,'issued_at':issued,'expires_at':issued+300}
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode('utf-8')
    signature=hmac.new(client.shared_secret.encode(),b'PQM-APPEND-RESUME-TICKET:'+raw,hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+base64.urlsafe_b64encode(signature).decode().rstrip('=')


def verify_append_only_resume_ticket(client, ticket, actor):
    try:
        client.validate()
        if client.environment!='SANDBOX' or not isinstance(ticket,str) or len(ticket)>8192:
            raise ValueError('scope rejected')
        encoded,signed=ticket.split('.')
        raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        signature=base64.urlsafe_b64decode(signed+'='*(-len(signed)%4))
        expected=hmac.new(client.shared_secret.encode(),b'PQM-APPEND-RESUME-TICKET:'+raw,hashlib.sha256).digest()
        if not hmac.compare_digest(signature,expected): raise ValueError('signature rejected')
        value=json.loads(raw)
        now=client.clock().timestamp()
        if (not isinstance(value,dict) or value.get('environment')!='SANDBOX' or
                value.get('actor')!=actor or value.get('trigger')!='manual' or
                value.get('action')!='resume_append_only' or value.get('scope')!='APPEND_ONLY' or
                not re.fullmatch(r'[0-9a-f]{32}',value.get('request_id','')) or
                not is_canonical_sha256_b64url(value.get('digest')) or
                not is_canonical_sha256_b64url(value.get('checkpoint_digest')) or
                not is_canonical_sha256_b64url(value.get('details_digest')) or
                type(value.get('next_chunk')) is not int or not 1<=value['next_chunk']<=499 or
                type(value.get('issued_at')) is not int or type(value.get('expires_at')) is not int or
                value['issued_at']>now+30 or value['expires_at']<now or
                value['expires_at']-value['issued_at']>300):
            raise ValueError('ticket context rejected')
        return value
    except Exception:
        raise ValueError('APPEND_ONLY continuation ticket is invalid or expired') from None
