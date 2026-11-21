"""Current-tree acceptance tests for the two stage1 review regressions."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import server
import supplier_registry_integration as registry


class FollowupTests(unittest.TestCase):
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

    def seed(self, identifier='s', decided=False):
        docs = [{'id': 'supplier-' + identifier, 'url': 'https://example.test/' + identifier,
                 'hash': 'sha256:synthetic-' + identifier}]
        with server.db() as con:
            con.execute("""INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,
              date_published,documents_json,raw_json,synced_at) VALUES (?,'f',?,'ORIGINAL',?,?,'{}',?)""",
              (identifier, identifier, '2026-11-20T00:00:00+00:00', json.dumps(docs), server.now_iso()))
            con.execute('INSERT INTO application_fields(submission_id) VALUES (?)', (identifier,))

        if decided:
            self.qualification('fixture-' + identifier, 'active', '2026-11-20', identifier)
            with server.db() as con:
                con.execute('UPDATE submissions SET qualification_id=? WHERE id=?', ('fixture-' + identifier, identifier))

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

    def test_old_pointer_list_detail_and_job_sources_agree_without_business_status_change(self):
        self.seed()
        self.qualification('old', 'pending', '2026-11-18')
        self.qualification('new', 'active', '2026-11-20')
        with server.db() as con:
            con.execute("UPDATE submissions SET qualification_id='old' WHERE id='s'")
        saved = self.store()
        with patch.object(server, 'application_documents', side_effect=AssertionError('No N+1 detail calls in list')):
            row = server.list_applications({})['items'][0]
        self.assertEqual(row['document_check_status'], 'ok')
        self.assertEqual(row['document_check_categories']['signature'], 'ok')
        self.assertEqual(row['decision'], server.decision_label('pending'))
        self.assertFalse(row['review_completed'])
        self.assertTrue(server.document_result_for_current_sources('s', saved)['ready'])

    def test_absent_pointer_same_priority_dates_ids_and_fallback(self):
        self.seed()
        self.qualification('active-old', 'active', '2026-11-01')
        self.qualification('unsuccessful-new', 'unsuccessful', '2026-11-20')
        self.qualification('active-new-a', 'active', '2026-11-02')
        self.qualification('active-new-z', 'active', '2026-11-02')
        self.assertEqual(server.application_documents('s')[1][-1][1]['id'], 'active-new-z')
        saved = self.store()
        self.assertEqual(server.list_applications({})['items'][0]['document_check_status'], 'ok')
        with server.db() as con:
            con.execute("DELETE FROM qualifications WHERE submission_id='s'")
        self.assertFalse(server.document_result_for_current_sources('s', saved)['ready'])
        self.assertEqual(server.list_applications({})['items'][0]['document_check_status'], 'warning')
        self.assertIsNone(server.application_documents('missing'))

    def test_changed_documents_both_views_stale_and_get_does_not_rewrite_saved_evidence(self):
        self.seed()
        self.qualification('chosen', 'active', '2026-11-20')
        saved = self.store()
        with server.db() as con:
            original = con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0]
            con.execute("UPDATE qualifications SET documents_json='[]' WHERE id='chosen'")
        self.assertFalse(server.document_result_for_current_sources('s', saved)['ready'])
        self.assertEqual(server.list_applications({})['items'][0]['document_check_status'], 'warning')
        with server.db() as con:
            self.assertEqual(con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0], original)

    def test_page_batch_read_is_one_call_and_query_only(self):
        for index in range(12):
            identifier = f's{index}'
            self.seed(identifier)
            self.store(identifier)
        original = server.application_document_sources
        with patch.object(server, 'application_document_sources', wraps=original) as sources:
            rows = server.list_applications({})['items']
            self.assertEqual(len(rows), 12)
            self.assertEqual(sources.call_count, 1)
        with server.db() as con:
            con.execute('PRAGMA query_only=ON')
            self.assertEqual(len(original(con, [row['id'] for row in rows])), 12)

    def test_three_fresh_closed_connections_build_once(self):
        self.seed(decided=True)
        with patch.object(registry, '_build_full_registry', wraps=registry._build_full_registry) as build:
            first = self.read_registry()
            self.assertEqual(self.read_registry(), first)
            self.assertEqual(self.read_registry(), first)
            self.assertEqual(build.call_count, 1)

    def test_committed_update_and_delete_invalidate(self):
        self.seed(decided=True)
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
        self.seed(decided=True)
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
        self.seed(decided=True)
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
        self.seed(decided=True)
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
        self.seed(decided=True)
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


if __name__ == '__main__':
    unittest.main()
