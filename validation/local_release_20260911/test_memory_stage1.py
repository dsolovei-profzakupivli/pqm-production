import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

import runtime_memory
import server


class RuntimeMemoryTests(unittest.TestCase):
    def test_expired_and_lru(self):
        now = [0]
        cache = runtime_memory.ContractCache(2, clock=lambda: now[0])
        cache.put('a', {'value': 1}, 10)
        cache.put('b', {'value': 2}, 20)
        cache.get('a')
        cache.put('c', {'value': 3}, 20)
        self.assertIsNone(cache.get('b'))
        now[0] = 10
        self.assertIsNone(cache.get('a'))
        self.assertEqual(len(cache), 1)
        now[0] = 20
        self.assertEqual(len(cache), 0)

    def test_byte_budget_and_oversize(self):
        cache = runtime_memory.ContractCache(max_bytes=100)
        cache.put('a', {'value': 'a' * 60}, 20)
        cache.put('b', {'value': 'b' * 60}, 20)
        self.assertEqual(len(cache), 1)
        cache.put('large', {'value': 'x' * 1000}, 20)
        self.assertIsNone(cache.get('large'))

    def test_parallel_cache(self):
        cache = runtime_memory.ContractCache(max_entries=20)
        def run(offset):
            for index in range(100):
                cache.put((offset, index), {'value': index}, 60)
                cache.get((offset, index))
        threads = [threading.Thread(target=run, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(cache), 20)

    def test_expiration_heap_does_not_grow_with_overwrites(self):
        cache = runtime_memory.ContractCache(max_entries=8)
        for index in range(1000):
            cache.put('same', {'value': index}, 60)
        self.assertEqual(len(cache), 1)
        self.assertLessEqual(len(cache._expiry), 16)

    def test_running_jobs_are_not_evicted_and_admission_is_bounded(self):
        jobs = runtime_memory.DocumentJobs(max_active=1, max_completed=1)
        self.assertTrue(jobs.start('one', 's'))
        self.assertFalse(jobs.start('two', 's'))
        self.assertEqual(jobs.get('one')['status'], 'running')
        jobs.finish('one', {'status': 'complete', 'result': {'value': 1}})
        self.assertTrue(jobs.start('two', 's'))
        jobs.finish('two', {'status': 'error', 'error': 'synthetic'})
        self.assertIsNone(jobs.get('one'))
        self.assertEqual(jobs.get('two')['status'], 'error')

    def test_completed_job_expiration(self):
        now = [0]
        jobs = runtime_memory.DocumentJobs(ttl=10, clock=lambda: now[0])
        jobs.start('one', 's')
        jobs.finish('one', {'status': 'complete', 'result': {}})
        now[0] = 10
        self.assertIsNone(jobs.get('one'))

    def test_thread_start_failure_releases_active_slot(self):
        jobs = runtime_memory.DocumentJobs(max_active=1)
        with patch.object(server, 'DOCUMENT_CHECK_JOBS', jobs), \
             patch.object(server.threading.Thread, 'start', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                server.launch_document_check_job('one', 's')
        self.assertTrue(jobs.start('two', 's'))
        self.assertEqual(jobs.get('one')['status'], 'error')

    def test_connection_commit_rollback_close_and_nested_context(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.sqlite3'
            connection = sqlite3.connect(path, factory=runtime_memory.ClosingConnection)
            with connection:
                connection.execute('CREATE TABLE t (value INTEGER)')
                with connection:
                    connection.execute('INSERT INTO t VALUES (1)')
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM t').fetchone()[0], 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            connection = sqlite3.connect(path, factory=runtime_memory.ClosingConnection)
            with self.assertRaises(ValueError):
                with connection:
                    connection.execute('INSERT INTO t VALUES (2)')
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            with sqlite3.connect(path, factory=runtime_memory.ClosingConnection) as reader:
                self.assertEqual(reader.execute('SELECT value FROM t').fetchall(), [(1,)])

    def test_commit_failure_still_closes(self):
        connection = sqlite3.connect(':memory:', factory=runtime_memory.ClosingConnection)
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('CREATE TABLE parent(id PRIMARY KEY)')
        connection.execute('CREATE TABLE child(id REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)')
        with self.assertRaises(sqlite3.IntegrityError):
            with connection:
                connection.execute('INSERT INTO child VALUES (9)')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')


class PersistedDocumentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'synthetic.sqlite3'
        self.db_patch = patch.object(server, 'DB_PATH', self.path)
        self.db_patch.start()
        with server.db() as con:
            con.execute('''CREATE TABLE application_fields (
                submission_id TEXT PRIMARY KEY, document_check_status TEXT,
                document_check_summary TEXT, document_checked_at TEXT,
                document_check_result_json TEXT, updated_at TEXT, updated_by TEXT,
                authority_review TEXT DEFAULT '', mvs_seal_review TEXT DEFAULT '')''')
            server.auth_access.migrate(con)
        self.docs = [('supplier', {'id': 'one', 'hash': 'sha256:one', 'url': 'https://example.test/one'})]
        self.current = {'selected_categories': ['signature'], 'signature': {'signer': 'SYNTHETIC'},
                        'document_fingerprints': {'signature': server.document_source_fingerprint(self.docs)},
                        'checks': [{'key': 'signer', 'status': 'ok', 'detail': 'synthetic'}]}

    def tearDown(self):
        self.db_patch.stop()
        gc.collect()
        self.folder.cleanup()

    def test_result_survives_memory_replacement_and_new_connection(self):
        result = server._store_document_check_result('s', self.current, 'test')
        with patch.object(server, 'DOCUMENT_CHECK_JOBS', runtime_memory.DocumentJobs()):
            with server.db() as con:
                raw = con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0]
            self.assertEqual(json.loads(raw), result)
            visible = server.document_result_for_current_sources('s', json.loads(raw), self.docs)
            self.assertTrue(visible['ready'])
            self.assertEqual(visible['source_freshness'], 'metadata_matches')

    def test_changed_deleted_and_legacy_sources_keep_history_but_not_current_success(self):
        for docs in ([], [('supplier', {'id': 'one', 'hash': 'sha256:changed'})]):
            visible = server.document_result_for_current_sources('s', self.current, docs)
            self.assertFalse(visible['ready'])
            self.assertEqual(visible['checks'][0]['historical_status'], 'ok')
            self.assertEqual(self.current['checks'][0]['status'], 'ok')
        legacy = {**self.current, 'document_fingerprints': {}}
        self.assertFalse(server.document_result_for_current_sources('s', legacy, self.docs)['ready'])

    def test_categories_and_fingerprints_merge_independently(self):
        saved = server._store_document_check_result('s', self.current, 'test')
        updated = server._store_document_check_result('s', {
            'selected_categories': ['experience'],
            'checks': [{'key': 'contract_experience', 'status': 'neutral', 'search_status': 'none'}]}, 'test')
        self.assertEqual(updated['signature'], saved['signature'])
        self.assertEqual(updated['document_fingerprints'], saved['document_fingerprints'])

    def test_source_order_is_stable_but_changed_metadata_is_not(self):
        second = ('supplier', {'id': 'two', 'hash': 'sha256:two'})
        self.assertEqual(server.document_source_fingerprint(self.docs + [second]),
                         server.document_source_fingerprint([second] + self.docs))
        changed = [('supplier', {**self.docs[0][1], 'dateModified': '2026-11-21'})]
        self.assertNotEqual(server.document_source_fingerprint(self.docs),
                            server.document_source_fingerprint(changed))

    def test_saved_endpoint_after_job_eviction_and_changed_documents(self):
        current = {**self.current, 'document_check_job_id': 'job'}
        server._store_document_check_result('s', current, 'test')
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, 'AUTH_ENABLED', False), \
                 patch.object(server, 'application_documents', return_value=('synthetic', self.docs)):
                with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/api/applications/s/document-check-result') as response:
                    result = json.load(response)
                self.assertEqual(result['document_check_job_id'], 'job')
                self.assertTrue(result['ready'])
            with patch.object(server, 'AUTH_ENABLED', False), \
                 patch.object(server, 'application_documents', return_value=('synthetic', [])):
                with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/api/applications/s/document-check-result') as response:
                    result = json.load(response)
                self.assertFalse(result['ready'])
            with server.db() as con:
                saved = json.loads(con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0])
            self.assertEqual(saved['checks'][0]['status'], 'ok')
        finally:
            http.shutdown()
            thread.join()
            http.server_close()

    def test_worker_persists_correlation_before_terminal_cache_eviction(self):
        jobs = runtime_memory.DocumentJobs(max_completed=0)
        jobs.start('job', 's')
        with patch.object(server, 'DOCUMENT_CHECK_JOBS', jobs), \
             patch.object(server, 'analyze_application_documents', return_value=self.current):
            server.document_check_worker('job', 's')
        self.assertIsNone(jobs.get('job'))
        with server.db() as con:
            saved = json.loads(con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0])
        self.assertEqual(saved['document_check_job_id'], 'job')


if __name__ == '__main__':
    unittest.main()
