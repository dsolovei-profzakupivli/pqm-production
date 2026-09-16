"""Sandbox bootstrap/HTTP isolation on a fresh disposable synthetic DB only."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sandbox_runtime as sandbox


class PolicyTests(unittest.TestCase):
    def env(self):
        return {**sandbox.POLICY, 'PQM_DATA_DIR': '/var/data',
                'PQM_DB_PATH': '/var/data/pqm_sandbox.sqlite3',
                'RENDER_SERVICE_ID': 'srv-sandbox-fixture', 'RENDER_SERVICE_NAME': 'pqm-sandbox'}

    def test_01_valid_policy(self):
        self.assertEqual(Path('/var/data/pqm_sandbox.sqlite3').resolve(), sandbox.validate_environment(self.env())[1])

    def test_02_working_service_and_db_rejected(self):
        for key, value in [('RENDER_SERVICE_ID', 'srv-da7vmitg1s2s73fim0p0'),
                           ('RENDER_SERVICE_NAME', 'pqm-production-1'),
                           ('PQM_DB_PATH', '/var/data/pqm_test_20260831.sqlite3')]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                sandbox.validate_environment({**self.env(), key: value})

    def test_03_no_flag_can_enable_mutations_or_integrations(self):
        for key in sandbox.POLICY:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                sandbox.validate_environment({**self.env(), key: 'invalid'})

    def test_04_no_inherited_secrets_or_storage(self):
        for key in ['PQM_USERS_JSON', 'PQM_GOOGLE_OAUTH_CLIENT_JSON', 'PQM_GOOGLE_OAUTH_TOKEN',
                    'PQM_SUPPLIER_REGISTRY_TOKEN', 'PQM_PROTOCOLS_DIR', 'PQM_CACHE_DIR']:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                sandbox.validate_environment({**self.env(), key: 'forbidden-fixture'})

    def test_05_outbound_and_child_process_guard(self):
        for event, args in [('socket.connect', (None, ('10.0.0.1', 80))),
                            ('socket.connect', (None, ('1.1.1.1', 443))),
                            ('socket.getaddrinfo', ('pqm-production-1',)),
                            ('socket.sendto', (None, b'data', ('10.0.0.1', 53))),
                            ('subprocess.Popen', ()), ('os.system', ())]:
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                sandbox.outbound_audit(event, args)
        sandbox.outbound_audit('socket.connect', (None, ('127.0.0.1', 10000)))
        sandbox.outbound_audit('socket.getaddrinfo', ('localhost',))

    def test_06_html_label_before_login(self):
        raw = sandbox.decorate_html((ROOT / 'index.html').read_bytes())
        self.assertIn(b'id="sandboxWarning"', raw)
        self.assertIn(b'noindex,nofollow,noarchive', raw)


class SandboxHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pqm-sandbox-smoke-')
        cls.data = Path(cls.temp.name) / 'data'
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            cls.port = reserve.getsockname()[1]
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(('PQM_', 'RENDER_'))}
        cls.env.update(sandbox.POLICY, PQM_SANDBOX_LOCAL_FIXTURE='1', PQM_DATA_DIR=str(cls.data),
                       PQM_DB_PATH=str(cls.data / 'pqm_sandbox.sqlite3'), HOST='127.0.0.1', PORT=str(cls.port),
                       PYTHONDONTWRITEBYTECODE='1')
        cls.env['PQM_SANDBOX_EDITS'] = getattr(cls, 'EDIT_MODE', '0')
        cls.env.update(getattr(cls, 'EXTRA_ENV', {}))
        cls.log = open(Path(cls.temp.name) / 'child.log', 'w+')
        cls.start()
        cls.accounts = json.loads((cls.data / sandbox.ACCESS_FILE).read_text())['accounts']

    @classmethod
    def start(cls):
        cls.proc = subprocess.Popen([sys.executable, '-B', str(ROOT / getattr(cls, 'RUNNER', 'sandbox_runtime.py'))],
                                    cwd=ROOT, env=cls.env, stdout=cls.log, stderr=cls.log)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if cls.proc.poll() is not None:
                cls.log.flush(); cls.log.seek(0)
                raise RuntimeError('Sandbox fixture failed: ' + cls.log.read()[-6000:])
            try:
                if cls.request('/api/health', role=None)[0] == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        raise RuntimeError('Sandbox fixture did not start')

    @classmethod
    def stop(cls):
        cls.proc.terminate()
        try: cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill(); cls.proc.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.stop()
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, role='admin', method='GET', payload=None):
        headers = {}
        if role:
            username = 'sandbox.' + role
            headers['Authorization'] = 'Basic ' + base64.b64encode((username + ':' + cls.accounts[username]).encode()).decode()
        body = None if payload is None else json.dumps(payload)
        if body is not None: headers['Content-Type'] = 'application/json'
        client = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=15)
        client.request(method, path, body, headers)
        response = client.getresponse()
        raw, status, out = response.read(), response.status, dict(response.getheaders())
        client.close()
        return status, json.loads(raw) if 'application/json' in out.get('Content-Type', '') else raw, out

    def test_10_auth_noindex_and_private_files(self):
        status, raw, headers = self.request('/', None)
        self.assertEqual(200, status)
        self.assertIn(b'SANDBOX', raw)
        self.assertIn('noindex', headers['X-Robots-Tag'])
        self.assertEqual(401, self.request('/api/applications', None)[0])
        for path in ['/sandbox_runtime.py', '/data/' + sandbox.ACCESS_FILE, '/' + sandbox.ACCESS_FILE,
                     '/data/pqm_sandbox.sqlite3']:
            self.assertEqual(404, self.request(path, None)[0])
        for role in ['admin', 'officer', 'viewer']:
            status, who, _ = self.request('/api/auth/me', role)
            self.assertEqual(200, status)
            self.assertEqual(role, who['role'])
        self.assertEqual(0o600, (self.data / sandbox.ACCESS_FILE).stat().st_mode & 0o777)

    def test_11_offline_features_and_modules(self):
        status, flags, _ = self.request('/api/runtime-features')
        self.assertEqual(200, status)
        self.assertTrue(flags['sandbox_mode'])
        self.assertTrue(flags['safe_mode'])
        for key in ['google', 'bids_update', 'powerbi', 'scheduler', 'nazk_scheduler']:
            self.assertFalse(flags[key], key)
        self.assertTrue(all(not row['enabled'] and not row['running'] for row in flags['scheduler_jobs']))
        for path in ['/api/applications', '/api/application-history', '/api/admin/users', '/api/admin/templates',
                     '/api/uo-work-queue', '/api/violation-reports', '/api/chats', '/api/reference-status',
                     '/api/edr-monitoring']:
            self.assertEqual(200, self.request(path)[0], path)
        self.assertEqual(7, len(self.request('/api/admin/templates')[1]['items']))

    def test_12_safe_mode_denies_updates(self):
        for role in ['admin', 'officer', 'viewer']:
            for path in ['/api/sync', '/api/admin/scheduler-jobs/prozorro', '/api/admin/runtime-features/google']:
                self.assertEqual(503, self.request(path, role, 'POST', {'enabled': True})[0])
            self.assertEqual(503, self.request('/api/applications/sandbox-pending', role, 'PATCH', {'notes': 'forbidden'})[0])
        for path in ['/api/amcu-registry?refresh=1', '/api/nazk-registry?refresh=1']:
            self.assertEqual(503, self.request(path)[0])

    def test_13_only_synthetic_data_no_tasks_or_registry(self):
        with sqlite3.connect((self.data / 'pqm_sandbox.sqlite3').as_uri() + '?mode=ro', uri=True) as con:
            self.assertEqual(3, con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0])
            self.assertEqual(3, con.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0])
            self.assertEqual(['00000000'], [r[0] for r in con.execute('SELECT DISTINCT supplier_code FROM submissions')])
            for table in ['operational_tasks', 'supplier_nazk_checks', 'nazk_registry', 'amcu_registry', 'chat_messages', 'chat_threads']:
                self.assertEqual(0, con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], table)
            self.assertEqual(['never'], [r[0] for r in con.execute('SELECT DISTINCT last_status FROM scheduler_job_state')])
            self.assertEqual('ok', con.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([], con.execute('PRAGMA foreign_key_check').fetchall())
            self.assertTrue(all(row[0].startswith('pbkdf2_sha256:') for row in con.execute('SELECT password_hash FROM auth_users')))

    def test_14_restart_keeps_accounts_and_fixture(self):
        access_hash = hashlib.sha256((self.data / sandbox.ACCESS_FILE).read_bytes()).hexdigest()
        with sqlite3.connect(self.data / 'pqm_sandbox.sqlite3') as con:
            before = con.execute('SELECT username,password_hash FROM auth_users ORDER BY username').fetchall()
        self.stop(); self.start()
        self.assertEqual(access_hash, hashlib.sha256((self.data / sandbox.ACCESS_FILE).read_bytes()).hexdigest())
        with sqlite3.connect(self.data / 'pqm_sandbox.sqlite3') as con:
            self.assertEqual(before, con.execute('SELECT username,password_hash FROM auth_users ORDER BY username').fetchall())
            self.assertEqual(3, con.execute('SELECT COUNT(*) FROM submissions').fetchone()[0])

    def test_15_existing_unmarked_or_foreign_db_rejected(self):
        path = Path(self.temp.name) / 'untrusted.sqlite3'
        with sqlite3.connect(path) as con: con.execute('CREATE TABLE unrelated (id INTEGER)')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError): sandbox._verify_existing(path, 'wrong-service')
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(RuntimeError): sandbox._verify_existing(self.data / 'pqm_sandbox.sqlite3', 'wrong-service')


if __name__ == '__main__':
    unittest.main(verbosity=2)
