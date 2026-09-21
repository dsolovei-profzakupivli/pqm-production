"""Dormant sandbox NAZK export worker. Does not grant any HTTP route or job."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

URL = 'https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData'
DEADLINE = 60
MAX_BYTES = 100 * 1024 * 1024
WORKER = Path(__file__).resolve()
_launch = threading.local()


def enabled():
    return os.environ.get('PQM_SANDBOX') == '1' and os.environ.get('PQM_SANDBOX_NAZK_READ') == '1'


def permitted_process(event, args):
    expected = getattr(_launch, 'expected', None)
    return (event == 'subprocess.Popen' and expected is not None
            and args[0] == sys.executable and tuple(args[1]) == expected[0]
            and args[2] == expected[1] and args[3] == expected[2])


def download():
    if not enabled():
        raise RuntimeError('Sandbox NAZK transport disabled; previous registry retained')
    import sandbox_runtime
    sandbox_runtime.validate_environment()
    with tempfile.TemporaryDirectory(prefix='pqm-sandbox-nazk-') as folder:
        command = [sys.executable, '-I', '-B', str(WORKER), '--download']
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        # The bounded response goes to a temporary file, not an unbounded pipe.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            _launch.expected = (tuple(command), folder, environment)
            try:
                process = subprocess.Popen(command, cwd=folder, env=environment,
                                           close_fds=True, start_new_session=True,
                                           stdout=output, stderr=errors)
                try:
                    process.wait(timeout=DEADLINE)
                except subprocess.TimeoutExpired as exc:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise TimeoutError('НАЗК: перевищено загальний ліміт 60 с; попередній реєстр збережено') from exc
            finally:
                _launch.expected = None
            if process.returncode:
                raise RuntimeError('НАЗК: експорт недоступний або некоректний; попередній реєстр збережено')
            output.seek(0)
            raw = output.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('НАЗК: перевищено ліміт відповіді 100 MiB')
            return raw


def worker():
    """One credential-free, redirect-free public GET; no DB/application imports."""
    import ipaddress
    import socket
    import urllib.request
    host = 'corruptinfo.nazk.gov.ua'
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = {row[4][0] for row in records}
    if not addresses or not all(ipaddress.ip_address(ip).is_global for ip in addresses):
        raise RuntimeError('NAZK DNS must contain only public addresses')
    def pinned_dns(name, port, *args, **kwargs):
        if name != host or port != 443:
            raise RuntimeError('NAZK DNS outside exact source')
        return records
    def audit(event, args):
        if event in {'sqlite3.connect', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
            raise RuntimeError('NAZK worker cannot open databases or processes')
        if event in {'socket.connect', 'socket.sendto'}:
            address = args[1] if event == 'socket.connect' else args[-1]
            if (event != 'socket.connect' or not isinstance(address, tuple)
                    or address[0] not in addresses or address[1] != 443):
                raise RuntimeError('NAZK worker outbound denied')
        if event == 'urllib.Request' and (args[0] != URL or args[1] is not None or args[3] != 'GET'):
            raise RuntimeError('NAZK worker only permits exact export GET')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    socket.getaddrinfo = pinned_dns
    sys.addaudithook(audit)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(URL, headers={'User-Agent': 'PQM-Sandbox/1.0', 'Accept': 'application/json'})
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError('NAZK export requires HTTP 200')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('NAZK response too large')
    # Parse before returning; canonical validation and transaction remain in parent.
    json.loads(raw.decode('utf-8-sig'))
    sys.stdout.buffer.write(raw)


if __name__ == '__main__':
    if sys.argv[1:] != ['--download']:
        raise SystemExit('Unsupported worker command')
    worker()
