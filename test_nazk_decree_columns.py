"""Read-model coverage with synthetic data only; no server, imports or live DB."""
import copy
import gc
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import nazk_registry_evidence as evidence
import reference_directories as references


def fixture_rows():
    variants = [
        ("disciplinary", "догана", {"decreeNumber": "00153-к/А", "decreeDate": "2026-08-19"}, {}),
        ("court", "", {}, {"court_case_number": "001/002/26", "sentence_date": "2026-07-03",
                               "sentence_number": "123456789", "punishment_start": "2026-07-14",
                               "decision_url": "https://reyestr.court.gov.ua/Review/123456789"}),
        ("missing-date", "звільнення", {"decreeNumber": "0007-Б"}, {}),
        ("both", "догана", {"decreeNumber": "0009-К/Б", "decreeDate": "2026-09-01"},
         {"court_case_number": "003/004/26", "sentence_date": "2026-08-30", "sentence_number": "987654321",
          "punishment_start": "2026-09-10", "decision_url": "https://reyestr.court.gov.ua/Review/987654321"}),
    ]
    rows = []
    for i, (key, punishment, raw, court) in enumerate(variants, 1):
        row = dict.fromkeys(evidence.FIELDS, "")
        row.update(source_id=str(i), full_name={"disciplinary": "ТЕСТ ДИСЦИПЛІНАРНИЙ НАКАЗ",
                   "court": "ТЕСТ СУДОВЕ РІШЕННЯ", "missing-date": "ТЕСТ БЕЗ ДАТИ НАКАЗУ",
                   "both": "ТЕСТ ОБИДВА ВИДИ РЕКВІЗИТІВ"}[key], offense_name="Синтетичний опис порушення",
                   punishment=punishment, raw_json=json.dumps({**raw, "private_unused": "MUST_NOT_LEAK"}, ensure_ascii=False), **court)
        rows.append(row)
    return rows


class DecreeColumnsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = Path(self.tmp.name) / "synthetic.sqlite3"
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TABLE nazk_registry(" + ",".join(f + " TEXT" for f in evidence.FIELDS) + ")")
            con.execute("CREATE TABLE supplier_nazk_check_matches(check_id INTEGER,nazk_source_id TEXT,match_status TEXT,created_at TEXT)")
            con.execute("CREATE TABLE nazk_registry_evidence_sources(source_id TEXT,payload_json TEXT,observed_at TEXT,provenance_json TEXT)")
            for row in fixture_rows():
                con.execute("INSERT INTO nazk_registry VALUES(" + ",".join("?" for _ in evidence.FIELDS) + ")", [row[f] for f in evidence.FIELDS])
                con.execute("INSERT INTO supplier_nazk_check_matches VALUES(1,?,'candidate','fixture')", (row["source_id"],))
                con.execute("INSERT INTO nazk_registry_evidence_sources VALUES(?,?,'fixture','{}')", (row["source_id"], json.dumps(row)))

    def tearDown(self):
        gc.collect()  # Release SQLite context-manager handles before Windows cleanup.
        self.tmp.cleanup()

    def task_records(self):
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            return evidence.registry_records(con, 1)

    def test_both_read_models_preserve_values_and_court_fields_without_writes(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        task = {r["source_id"]: r for r in self.task_records()}
        directory_rows = references.list_registry(self.path, "nazk", {})["items"]
        directory = {r["full_name"]: r for r in directory_rows}
        for original in fixture_rows():
            raw = json.loads(original["raw_json"])
            for projected in (task[original["source_id"]], directory[original["full_name"]]):
                self.assertEqual(projected["punishment"], original["punishment"])
                self.assertEqual(projected["decree_number"], raw.get("decreeNumber", ""))
                self.assertEqual(projected["decree_date"], raw.get("decreeDate", ""))
                self.assertEqual(projected["court_case_number"], original["court_case_number"])
                self.assertEqual(projected["decision_url"], original["decision_url"])
                self.assertNotIn("raw_json", projected)
                self.assertNotIn("MUST_NOT_LEAK", json.dumps(projected))
            for field in ("sentence_date", "punishment_start", "sentence_number"):
                self.assertEqual(task[original["source_id"]][field], original[field])
            for field in ("sentence_date", "punishment_start"):
                self.assertEqual(directory[original["full_name"]][field], references._date_display(original[field]))
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_historical_fallback_projects_only_and_does_not_change_snapshots(self):
        with sqlite3.connect(self.path) as con:
            con.execute("DELETE FROM nazk_registry")
        before = self.path.read_bytes()
        for row in self.task_records():
            self.assertFalse(row["current_registry_present"])
            self.assertEqual(row["registry_source"], "historical_web_snapshot")
            raw = json.loads(next(r for r in fixture_rows() if r["source_id"] == row["source_id"])["raw_json"])
            self.assertEqual(row["decree_number"], raw.get("decreeNumber", ""))
            self.assertEqual(row["decree_date"], raw.get("decreeDate", ""))
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_or_malformed_raw_is_safe_and_never_leaks(self):
        for raw in (None, "", "{broken", "null", "[]", '"text"', '{"decreeNumber":{},"decreeDate":[]}'):
            with self.subTest(raw=raw):
                original = {"raw_json": raw, "punishment": "догана", "sentence_date": "2026-01-02"}
                saved = copy.deepcopy(original)
                result = evidence.project_decree_fields(original)
                self.assertEqual(result, {"punishment": "догана", "sentence_date": "2026-01-02", "decree_number": "", "decree_date": ""})
                self.assertEqual(original, saved)

    def test_exact_strings_and_html_are_preserved_by_api_not_interpreted(self):
        number = '000А-к/<img src=x onerror="alert(1)">'
        result = evidence.project_decree_fields({"raw_json": json.dumps({"decreeNumber": number, "decreeDate": "2026-01-02"})})
        self.assertEqual(result, {"decree_number": number, "decree_date": "2026-01-02"})

    def test_pagination_and_existing_court_filters_are_unchanged(self):
        self.assertEqual(references.list_registry(self.path, "nazk", {"size": ["2"]})["total"], 4)
        self.assertEqual(len(references.list_registry(self.path, "nazk", {"size": ["2"]})["items"]), 2)
        filtered = references.list_registry(self.path, "nazk", {"date_from": ["2026-08-01"]})
        self.assertEqual([r["full_name"] for r in filtered["items"]], ["ТЕСТ ОБИДВА ВИДИ РЕКВІЗИТІВ"])


def export_browser_fixtures(destination):
    case = DecreeColumnsTests()
    case.setUp()
    try:
        data = {"directory": references.list_registry(case.path, "nazk", {}), "task": {"nazk_records": case.task_records()}}
        Path(destination).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        case.tearDown()


if __name__ == "__main__":
    unittest.main()
