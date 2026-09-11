import json
import tempfile
import unittest
from pathlib import Path

import server


class ProtocolBusinessRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
        with server.db() as con:
            con.execute("""INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at)
              VALUES ('f','UA-F-TEST','active',?,?)""",
              (json.dumps({"qualificationPeriod": {"endDate": "2099-12-31T00:00:00"}}),
               server.now_iso()))

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def seed(self, submission_id, *, decision, remarks, compliance, comment="", package=""):
        with server.db() as con:
            qualification_id = f"q-{submission_id}"
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
              VALUES (?,'f',?,'pending','[]','{}',?)""",
              (qualification_id, submission_id, server.now_iso()))
            con.execute("""INSERT INTO submissions
              (id,framework_id,supplier_code,supplier_name,qualification_id,date_published,raw_json,synced_at)
              VALUES (?,'f','10000001',?,?,'2026-08-25T10:00:00','{}',?)""",
              (submission_id, submission_id, qualification_id, server.now_iso()))
            con.execute("""INSERT INTO application_fields
              (submission_id,protocol_number,protocol_date,protocol_officer,manager_name,
               protocol_decision,protocol_remarks,compliance_status,compliance_comments,document_package)
              VALUES (?,'TEST-1','2026-08-25','УО','КЕРІВНИК',?,?,?,?,?)""",
              (submission_id, decision, remarks, compliance, comment, package))

    def errors(self):
        result = server.protocol_readiness({"protocol_number": "TEST-1"})
        return {item["id"]: item["errors"] for item in result["items"]}

    def test_admit_with_meaningful_remarks_is_blocked(self):
        self.seed("admit-conflict", decision="admit", remarks="Виявлено порушення",
                  compliance="approved")
        self.assertTrue(any("має зауваження" in error for error in self.errors()["admit-conflict"]))

    def test_reject_without_ground_is_blocked(self):
        self.seed("reject-conflict", decision="reject", remarks="Без зауважень",
                  compliance="approved")
        self.assertTrue(any("Немає підстав для відхилення" in error
                            for error in self.errors()["reject-conflict"]))

    def test_rejected_compliance_requires_comment(self):
        self.seed("missing-comment", decision="reject", remarks="Є зауваження",
                  compliance="rejected", comment="")
        self.assertTrue(any("коментар комплаєнс" in error
                            for error in self.errors()["missing-comment"]))

    def test_document_package_is_optional(self):
        self.seed("package-optional", decision="admit", remarks="Без зауважень",
                  compliance="approved", package="")
        self.assertFalse(any("Пакет документів" in error
                             for error in self.errors()["package-optional"]))


if __name__ == "__main__":
    unittest.main()
