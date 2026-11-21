"""Exact Sandbox-only bridge for the existing official EDS adapter."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = 'https://api-sign.prozorro.gov.ua/verify_data_internal'
MAX_RESPONSE = 40 * 1024 * 1024
_SLOTS = threading.BoundedSemaphore(2)
_NETWORK_SLOTS = threading.BoundedSemaphore(2)
_launch = threading.local()
TRANSPORT = Path(__file__).resolve().parent / 'tools/prozorro_eds_adapter/sandbox-transport.mjs'
ADAPTER = TRANSPORT.with_name('verify-signature.mjs')


def permitted_process(event, args):
    expected = getattr(_launch, 'expected', None)
    return (os.getenv('PQM_SANDBOX') == '1' and event == 'subprocess.Popen'
            and expected is not None and (args[0] == expected[0][0] or (os.name == 'nt' and args[0] is None))
            and (args[1] == subprocess.list2cmdline(expected[0]) if isinstance(args[1], str)
                 else tuple(args[1]) == expected[0]) and args[2] == expected[1]
            and args[3] == expected[2])


def validate_sign_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid signature URL')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Signature must use public HTTPS')
    rows = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not rows or any(not ipaddress.ip_address(row[4][0]).is_global for row in rows):
        raise ValueError('Signature must use a public address')
    return value


def validate_verification_request(url, method, data):
    if url != ENDPOINT or method != 'POST' or not data or len(data) > 16384:
        raise RuntimeError('Unapproved EDS request')
    payload = json.loads(data)
    if not isinstance(payload, dict) or set(payload) != {'sign_url'}:
        raise RuntimeError('Unapproved EDS request fields')
    return payload['sign_url']


@contextmanager
def verification_open(request, timeout):
    import sandbox_runtime as policy
    validate_verification_request(request.full_url, request.get_method(), request.data)
    if getattr(policy._egress, 'active', False):
        raise RuntimeError('Nested EDS scope is not allowed')
    policy._egress.active = True
    policy._egress.reference_host = 'api-sign.prozorro.gov.ua'
    policy._egress.eds_verify = True
    policy._egress.addresses = set()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), policy._NoGoogleRedirect())
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error  # The official adapter classifies the unchanged error response.
        with response:
            yield response
    finally:
        policy._egress.active = False
        policy._egress.reference_host = None
        policy._egress.eds_verify = False
        policy._egress.addresses = set()


class Bridge(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    def __init__(self, sign_url, timeout):
        super().__init__(('127.0.0.1', 0), BridgeHandler)
        self.token = secrets.token_urlsafe(32)
        self.sign_url, self.timeout = sign_url, timeout
        self.claim = threading.Lock()
        self.used = False


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.connection.settimeout(self.server.timeout)
        if (self.path != '/verify' or self.headers.get('X-PQM-EDS-Bridge') != self.server.token
                or self.headers.get('Transfer-Encoding')):
            self.send_error(403); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('Invalid body length')
            data = self.rfile.read(length)
            if validate_verification_request(ENDPOINT, 'POST', data) != self.server.sign_url:
                raise ValueError('Signature identity changed')
            with self.server.claim:
                if self.server.used:
                    raise ValueError('One verification per bridge')
                self.server.used = True
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
            authorization = self.headers.get('X-PQM-EDS-Authorization', '')
            if not authorization.startswith('Basic ') or len(authorization) > 1024:
                raise ValueError('Invalid verification authentication')
            headers['Authorization'] = authorization
            request = urllib.request.Request(ENDPOINT, data=data, headers=headers, method='POST')
            if not _NETWORK_SLOTS.acquire(timeout=self.server.timeout):
                raise TimeoutError('EDS transport busy')
            try:
                with verification_open(request, self.server.timeout) as response:
                    body = response.read(MAX_RESPONSE + 1)
                    if len(body) > MAX_RESPONSE:
                        raise ValueError('EDS response too large')
                    status = response.status
            finally:
                _NETWORK_SLOTS.release()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        except Exception:
            self.send_error(502, 'EDS verification transport unavailable')


def run_adapter(node, adapter, sign_url, timeout):
    import sandbox_runtime as policy
    policy.validate_environment()
    adapter, node = Path(adapter).resolve(), Path(node).resolve()
    if adapter != ADAPTER.resolve() or not adapter.is_file() or not node.is_file():
        raise RuntimeError('Unapproved EDS executable or adapter')
    # URL DNS validation is itself confined to a checked public-read scope.
    parsed = urllib.parse.urlsplit(sign_url)
    policy.validate_public_read_request(sign_url, 'GET')
    if getattr(policy._egress, 'active', False):
        raise RuntimeError('Nested EDS validation scope')
    policy._egress.active = True
    policy._egress.reference_host = parsed.hostname
    policy._egress.addresses = set()
    try:
        validate_sign_url(sign_url)
    finally:
        policy._egress.active = False; policy._egress.reference_host = None
        policy._egress.addresses = set()
    if not _SLOTS.acquire(timeout=timeout):
        raise subprocess.TimeoutExpired('sandbox EDS admission', timeout)
    try:
        with tempfile.TemporaryDirectory(prefix='pqm-sandbox-eds-') as temporary:
            bridge = Bridge(sign_url, timeout)
            thread = threading.Thread(target=bridge.serve_forever, daemon=True, name='pqm-eds-bridge')
            try:
                thread.start()
            except BaseException:
                bridge.server_close()
                raise
            environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8',
                'PQM_EDS_BRIDGE_URL': 'http://127.0.0.1:%s/verify' % bridge.server_address[1],
                'PQM_EDS_BRIDGE_TOKEN': bridge.token,
                'PQM_EDS_TIMEOUT_MS': str(max(1000, (timeout - 2) * 1000))}
            if os.name == 'nt' and os.getenv('SystemRoot'):
                environment['SystemRoot'] = os.environ['SystemRoot']
            command = (str(node), '--max-old-space-size=256', '--import', TRANSPORT.resolve().as_uri(), str(adapter))
            _launch.expected = (command, temporary, environment)
            try:
                return subprocess.run(list(command), input=json.dumps({'signUrl': sign_url}),
                    text=True, encoding='utf-8', capture_output=True, timeout=timeout,
                    cwd=temporary, env=environment, check=False)
            finally:
                _launch.expected = None
                bridge.shutdown(); bridge.server_close(); thread.join(timeout=2)
    finally:
        _SLOTS.release()
