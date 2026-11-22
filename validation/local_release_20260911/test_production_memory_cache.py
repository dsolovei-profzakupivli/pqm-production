import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server
import supplier_registry_integration as registry
class ProductionCacheTests(unittest.TestCase):
    def test_protocol_readiness_uses_open_connection_and_then_closes(self):
        self.seed()
        with server.db() as con:
            con.execute("UPDATE application_fields SET protocol_number='123' WHERE submission_id='s'")
        observed=[]
        def available(con,sid):
            self.assertEqual(con.execute('SELECT 1').fetchone()[0],1)
            observed.append(con)
        with patch.object(server.formed_protocols,'available',side_effect=available):
            result=server.protocol_readiness({'protocol_number':'123'})
        self.assertEqual(len(observed),1)
        self.assertEqual(result['items'][0]['id'],'s')
        with self.assertRaises(sqlite3.ProgrammingError):
            observed[0].execute('SELECT 1')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(server, 'DB_PATH', Path(self.temp.name) / 'synthetic.sqlite3'))
        self.enterContext(patch.object(server, 'api_get', side_effect=AssertionError('No external API')))
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,title,status,raw_json,synced_at) VALUES ('f','FIX','Synthetic','active','{}',?)", (server.now_iso(),))
        registry.reset_full_registry_cache()

    def seed(self, identifier='s'):
        docs = [{'id': 'supplier-' + identifier, 'url': 'https://example.test/' + identifier,
                 'hash': 'sha256:synthetic-' + identifier}]
        with server.db() as con:
            con.execute("""INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,
              date_published,documents_json,raw_json,synced_at) VALUES (?,'f',?,'ORIGINAL',?,?,'{}',?)""",
              (identifier, identifier, '2026-11-20T00:00:00+00:00', json.dumps(docs), server.now_iso()))
            con.execute('INSERT INTO application_fields(submission_id) VALUES (?)', (identifier,))

    def qualification(self, key, status, stamp, submission='s'):
        docs = [{'id': key, 'url': 'https://example.test/' + key, 'hash': 'sha256:' + key}]
        with server.db() as con:
            con.execute("""INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,
              documents_json,raw_json,synced_at) VALUES (?,'f',?,?,?,?, '{}',?)""",
              (key, submission, status, stamp, json.dumps(docs), server.now_iso()))

    def store(self, identifier='s'):
        docs = server.application_documents(identifier)[1]
        return server._store_document_check_result(identifier, {
            'selected_categories': ['signature'], 'checks': [{'key': 'signer', 'status': 'ok', 'detail': 'synthetic'}],
            'document_fingerprints': {'signature': server.document_source_fingerprint(docs)}}, 'test')

    def read_registry(self):
        with server.db() as con:
            result = registry.full_registry(con)
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')
        return result

    def test_three_fresh_closed_connections_build_once(self):
        self.seed()
        with patch.object(registry, '_build_full_registry', wraps=registry._build_full_registry) as build:
            first = self.read_registry()
            self.assertEqual(self.read_registry(), first)
            self.assertEqual(self.read_registry(), first)
            self.assertEqual(build.call_count, 1)

    def test_committed_update_and_delete_invalidate(self):
        self.seed()
        self.read_registry()
        with server.db() as con:
            con.execute("UPDATE submissions SET supplier_name='CHANGED' WHERE id='s'")
        self.assertEqual(self.read_registry()['items'][0]['latest_submission_name'], 'CHANGED')
        self.seed('second')
        self.assertEqual(len(self.read_registry()['items']), 2)
        with server.db() as con:
            con.execute("DELETE FROM application_fields WHERE submission_id='second'")
            con.execute("DELETE FROM submissions WHERE id='second'")
            con.execute("DELETE FROM application_fields WHERE submission_id='s'")
            con.execute("DELETE FROM submissions WHERE id='s'")
        self.assertEqual(self.read_registry()['items'], [])

    def test_nonempty_wal_commit_checkpoint_and_empty_wal_reads(self):
        self.seed()
        self.read_registry()
        writer = server.db()
        try:
            writer.execute("UPDATE submissions SET supplier_name='WAL-WRITE' WHERE id='s'")
            writer.commit()
            self.assertGreater(Path(str(server.DB_PATH) + '-wal').stat().st_size, 0)
            self.assertEqual(self.read_registry()['items'][0]['latest_submission_name'], 'WAL-WRITE')
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
        finally:
            writer.close()
        with patch.object(registry, '_build_full_registry', wraps=registry._build_full_registry) as build:
            first = self.read_registry()
            self.assertEqual(first['items'][0]['latest_submission_name'], 'WAL-WRITE')
            self.assertEqual(self.read_registry(), first)
            self.assertEqual(self.read_registry(), first)
            self.assertLessEqual(build.call_count, 1)

    def test_uncommitted_value_never_poison_cache_and_rollback_restores(self):
        self.seed()
        original = self.read_registry()
        writer = server.db()
        try:
            writer.execute("UPDATE submissions SET supplier_name='UNCOMMITTED' WHERE id='s'")
            self.assertIsNone(registry.database_revision(writer))
            self.assertEqual(registry.full_registry(writer)['items'][0]['latest_submission_name'], 'UNCOMMITTED')
            writer.rollback()
        finally:
            writer.close()
        self.assertEqual(self.read_registry()['items'], original['items'])

    def test_write_during_build_does_not_publish_old_snapshot(self):
        self.seed()
        original_build = registry._build_full_registry
        def changing(con):
            snapshot = original_build(con)
            with server.db() as writer:
                writer.execute("UPDATE submissions SET supplier_name='DURING-BUILD' WHERE id='s'")
            return snapshot
        with patch.object(registry, '_build_full_registry', side_effect=changing):
            self.assertEqual(self.read_registry()['items'][0]['latest_submission_name'], 'ORIGINAL')
        self.assertIsNone(registry._FULL_REGISTRY_CACHE['payload'])
        self.assertEqual(self.read_registry()['items'][0]['latest_submission_name'], 'DURING-BUILD')

    def test_read_transaction_snapshot_does_not_reuse_or_publish_current_cache(self):
        self.seed()
        self.read_registry()
        reader = server.db()
        try:
            reader.execute('BEGIN')
            reader.execute('SELECT supplier_name FROM submissions').fetchall()
            with server.db() as writer:
                writer.execute("UPDATE submissions SET supplier_name='NEW-SNAPSHOT' WHERE id='s'")
            self.assertEqual(registry.full_registry(reader)['items'][0]['latest_submission_name'], 'ORIGINAL')
            reader.rollback()
        finally:
            reader.close()
        self.assertEqual(self.read_registry()['items'][0]['latest_submission_name'], 'NEW-SNAPSHOT')
