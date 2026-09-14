import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import server


class BidsStatusPresentationTests(unittest.TestCase):
    def test_current_worker_stale_history_and_current_errors_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bids.sqlite3"
            con = sqlite3.connect(path)
            con.executescript(
                """
                CREATE TABLE agreements(agreement_id TEXT, last_search_at TEXT, last_error TEXT);
                CREATE TABLE tenders(tender_id TEXT, detail_loaded INTEGER, last_error TEXT,
                    tender_start TEXT, date_created TEXT, date_modified TEXT, last_detail_at TEXT);
                CREATE TABLE bids(id INTEGER);
                CREATE TABLE awards(id INTEGER);
                CREATE TABLE sync_log(
                    id INTEGER, started_at TEXT, finished_at TEXT, mode TEXT,
                    details_loaded INTEGER, status TEXT, run_id TEXT,
                    last_activity_at TEXT, stage TEXT, process_id INTEGER
                );
                CREATE TABLE search_validation_diagnostics(
                    agreement_id TEXT, response_item_count INTEGER,
                    missing_start_date_count INTEGER, malformed_start_date_count INTEGER,
                    recorded_at TEXT
                );
                INSERT INTO agreements VALUES('a','2026-09-12','bad date');
                INSERT INTO tenders VALUES('t',1,NULL,'2026-09-12',NULL,'2026-09-12','2026-09-12');
                INSERT INTO sync_log VALUES(1,'2026-09-12',NULL,'update',0,'running','current-run','2026-09-12','search',100);
                INSERT INTO sync_log VALUES(2,'2026-08-01',NULL,'update',0,'running',NULL,NULL,NULL,NULL);
                INSERT INTO sync_log VALUES(3,'2026-08-02','2026-08-02','update',0,'abandoned','old-run','2026-08-02','abandoned',101);
                INSERT INTO sync_log VALUES(4,'2026-09-11','2026-09-11','update',0,'completed','done','2026-09-11','completed',102);
                INSERT INTO search_validation_diagnostics VALUES('a',3,2,1,'2026-09-12');
                """
            )
            con.commit()
            con.close()

            @contextmanager
            def test_db():
                connection = sqlite3.connect(path)
                connection.row_factory = sqlite3.Row
                try:
                    yield connection
                finally:
                    connection.close()

            original_state = dict(server.BIDS_UPDATE_STATE)
            try:
                server.BIDS_UPDATE_STATE.update(running=True, run_id="current-run")
                server.BIDS_STATUS_CACHE.update(at=0.0, value=None, error=None)
                with mock.patch.object(server, "bids_db", test_db), mock.patch.object(
                    server, "BIDS_DB_PATH", path
                ):
                    server.BIDS_STATUS_LOCK.acquire()
                    server._refresh_bids_status_cache()
                result = server.BIDS_STATUS_CACHE["value"]
            finally:
                server.BIDS_UPDATE_STATE.clear()
                server.BIDS_UPDATE_STATE.update(original_state)

            self.assertEqual(len(result["active_worker_runs"]), 1)
            self.assertEqual(result["active_worker_runs"][0]["id"], 1)
            self.assertEqual(len(result["stale_open_logs"]), 1)
            self.assertEqual(result["stale_open_logs"][0]["id"], 2)
            self.assertEqual(len(result["abandoned_runs"]), 1)
            self.assertEqual(result["current_validation_errors"]["count"], 1)
            self.assertEqual(result["current_validation_errors"]["missing_start_dates"], 2)
            self.assertEqual(result["run_history_counts"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()
