import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import server


class SyncReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        self.original_wal_ready = server.DB_WAL_READY
        self.original_overlap = server.SYNC_CURSOR_OVERLAP_SECONDS
        server.DB_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        server.DB_WAL_READY = False
        server.SYNC_CURSOR_OVERLAP_SECONDS = 86400

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        server.DB_WAL_READY = self.original_wal_ready
        server.SYNC_CURSOR_OVERLAP_SECONDS = self.original_overlap
        self.temp_dir.cleanup()

    def test_db_context_closes_connection(self):
        with server.db() as con:
            con.execute("CREATE TABLE sample(id INTEGER)")
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_resource_cursor_rewinds_by_overlap(self):
        item_id = "qualification-1"
        modified = "2026-08-31T14:54:38+03:00"
        with server.db() as con:
            con.execute("CREATE TABLE qualifications(id TEXT, framework_id TEXT, raw_json TEXT)")
            con.execute(
                "INSERT INTO qualifications VALUES (?,?,?)",
                (item_id, "framework-1", json.dumps({"dateModified": modified})),
            )

        cursor = server.resource_cursor("framework-1", "qualifications")
        seconds, marker, digest = cursor.split(".", 2)
        expected = datetime.fromisoformat(modified).astimezone(timezone.utc).timestamp() - 86400
        self.assertAlmostEqual(float(seconds), expected, places=3)
        self.assertEqual(marker, "1")
        self.assertEqual(digest, hashlib.md5(item_id.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
