"""Opt-in, manual-only sandbox AMCU transport; no database in the worker."""
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

_launch = threading.local()
WORKER = Path(__file__).resolve()


def enabled():
    return os.environ.get('PQM_SANDBOX') == '1' and os.environ.get('PQM_SANDBOX_AMCU_READ') == '1'


def route_allowed(method, path):
    return enabled() and method == 'POST' and path == '/api/amcu-registry/refresh'


def permitted_process(event, args):
    expected = getattr(_launch, 'expected', None)
    return (event == 'subprocess.Popen' and expected is not None
            and args[0] == sys.executable and tuple(args[1]) == expected[0]
            and args[2] == expected[1] and args[3] == expected[2])


def download_rows():
    if not enabled():
        raise RuntimeError('Sandbox AMCU transport is disabled')
    import sandbox_runtime
    sandbox_runtime.validate_environment()
    with tempfile.TemporaryDirectory(prefix='pqm-sandbox-amcu-') as folder:
        command = [sys.executable, '-I', '-B', str(WORKER), '--download']
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        _launch.expected = (tuple(command), folder, environment)
        try:
            process = subprocess.Popen(command, cwd=folder, env=environment,
                                       close_fds=True, start_new_session=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = process.communicate(timeout=300)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise TimeoutError('Sandbox AMCU exceeded 300 seconds; previous registry retained') from exc
        finally:
            _launch.expected = None
        if process.returncode:
            raise RuntimeError('Sandbox AMCU download failed: ' + stderr.decode('utf-8', 'replace')[-500:])
        result = json.loads(stdout)
        if not result.get('rows'):
            raise ValueError('Empty AMCU registry rejected')
        return result['source'], result['rows']


def validate_url(url):
    import reference_directories as ref
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port or parsed.fragment or '%' in parsed.path
            or '..' in parsed.path.split('/')):
        raise ValueError('Unapproved sandbox AMCU URL')
    allowed = url in {ref.AMCU_PAGE, ref.AMCU_OPEN_DATA_API}
    allowed |= (parsed.hostname == 'amcu.gov.ua' and not parsed.query
                and parsed.path.startswith('/static-objects/amcu/')
                and parsed.path.lower().endswith(('.xlsx', '.xls')))
    allowed |= (parsed.hostname == 'data.gov.ua' and not parsed.query
                and parsed.path.startswith(f'/dataset/{ref.AMCU_OPEN_DATA_ID}/resource/')
                and '/download/' in parsed.path and parsed.path.lower().endswith('.xlsx'))
    if not allowed:
        raise ValueError('Unapproved sandbox AMCU source')
    return parsed.hostname


def install_worker_transport():
    """Python audit guard, not an OS filesystem/network sandbox."""
    import reference_directories as ref
    original_dns = socket.getaddrinfo
    state = {'host': None, 'addresses': set(), 'dns': None}

    def audit(event, args):
        if event in {'sqlite3.connect', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
            raise RuntimeError('AMCU worker cannot access databases or launch processes')
        if event in {'socket.connect', 'socket.sendto'}:
            address = args[1] if event == 'socket.connect' else args[-1]
            if (event != 'socket.connect' or not isinstance(address, tuple)
                    or address[0] not in state['addresses'] or address[1] != 443):
                raise RuntimeError('AMCU worker outbound denied')
        if event.startswith('socket.gethost') or event == 'socket.getaddrinfo':
            if event != 'socket.getaddrinfo' or args[0] != state['host']:
                raise RuntimeError('AMCU worker DNS denied')
        if event == 'urllib.Request':
            if validate_url(args[0]) != state['host'] or args[1] is not None or args[3] != 'GET':
                raise RuntimeError('AMCU worker only permits public GET')

    def pinned_dns(host, port, *args, **kwargs):
        if host != state['host'] or port != 443 or state['dns'] is None:
            raise RuntimeError('Unscoped AMCU DNS request')
        return state['dns']

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def fetch(url, timeout=30, max_bytes=None):
        host = validate_url(url)
        limit = min(max_bytes or 4 * 1024 * 1024, ref.AMCU_MAX_BYTES)
        state['host'] = host
        try:
            records = original_dns(host, 443, type=socket.SOCK_STREAM)
            addresses = {row[4][0] for row in records}
            if not addresses or not all(ipaddress.ip_address(ip).is_global for ip in addresses):
                raise ValueError('AMCU source must resolve only to public IP addresses')
            state.update(addresses=addresses, dns=records)
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 PQM-Sandbox/1.0'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=min(timeout, 60)) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('AMCU response exceeds allowed size')
            return raw
        finally:
            state.update(host=None, addresses=set(), dns=None)

    socket.getaddrinfo = pinned_dns
    sys.addaudithook(audit)
    ref._fetch = fetch
    ref._amcu_public_get = lambda url, max_bytes: fetch(url, 30, max_bytes)


if __name__ == '__main__':
    if sys.argv[1:] != ['--download']:
        raise SystemExit('Unsupported worker command')
    sys.path.insert(0, str(WORKER.parent))
    import reference_directories as ref
    install_worker_transport()
    source, rows = ref._download_amcu_rows()
    print(json.dumps({'source': source, 'rows': rows}, ensure_ascii=False))
