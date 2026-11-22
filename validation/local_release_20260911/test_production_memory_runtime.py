import unittest,threading,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
import server,runtime_memory
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
