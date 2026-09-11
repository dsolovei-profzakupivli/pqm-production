import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reference_directories
from reference_directories import init_reference_tables, list_registry, start_reference_refresh


class ReferenceDirectorySearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp.name) / "references.sqlite3"
        init_reference_tables(self.db_path)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""INSERT INTO nazk_registry
              (source_id,full_name,offense_name,court_case_number,sentence_date,raw_json)
              VALUES ('1','САЛІЙ ІЛЛЯ ЄВГЕНОВИЧ','Тест','1/1/26','2026-01-01','{}')""")

    def tearDown(self):
        self.temp.cleanup()

    def search(self, value):
        return list_registry(self.db_path, "nazk", {"search": [value], "page": ["1"], "size": ["50"]})

    def test_ukrainian_search_is_case_insensitive(self):
        self.assertEqual([self.search(value)["total"] for value in
                          ("САЛІЙ", "Салій", "салій")], [1, 1, 1])

    def test_apostrophes_hyphens_and_spaces_are_normalized(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""INSERT INTO nazk_registry
              (source_id,full_name,offense_name,court_case_number,sentence_date,raw_json)
              VALUES ('2','П’ЯТНИЦЬКА-ЇВГА ЄВГЕНІЇВНА','Тест','2/2/26','2026-01-02','{}')""")
        self.assertEqual(self.search("  п'ятницька   ївга ")["total"], 1)

    def test_long_refresh_is_deferred_and_duplicate_start_is_rejected(self):
        with patch.object(reference_directories.threading, "Timer") as timer:
            timer.return_value.start.return_value = None
            self.assertTrue(start_reference_refresh(self.db_path, "nazk"))
            self.assertFalse(start_reference_refresh(self.db_path, "nazk"))
            self.assertEqual(timer.call_count, 1)
            self.assertEqual(timer.call_args.args[0], 0.2)


if __name__ == "__main__":
    unittest.main()
