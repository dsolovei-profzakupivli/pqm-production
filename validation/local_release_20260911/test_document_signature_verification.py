import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class SignatureSelectionTests(unittest.TestCase):
    @staticmethod
    def docs(*items):
        return [("01-заявка", item) for item in items]

    def test_manual_signature_has_absolute_priority(self):
        documents = self.docs(
            {"title": "sign.p7s", "datePublished": "2026-08-28T12:00:00+03:00"},
            {"title": "chosen.pdf.p7s", "datePublished": "2026-08-27T12:00:00+03:00"},
        )
        self.assertEqual(server.select_main_signature_document(documents, {"1": ["signature"]}), (1, "manual"))

    def test_mvs_mark_does_not_replace_manual_signature(self):
        documents = self.docs({"title": "sign.p7s"}, {"title": "Файл підпису.p7s"})
        selection = {"0": ["signature"], "1": ["mvs_signature"]}
        self.assertEqual(server.select_main_signature_document(documents, selection), (0, "manual"))

    def test_two_manual_signatures_are_rejected(self):
        documents = self.docs({"title": "a.p7s"}, {"title": "b.p7s"})
        with self.assertRaisesRegex(ValueError, "лише біля одного документа"):
            server.select_main_signature_document(documents, {"0": ["signature"], "1": ["signature"]})

    def test_fallback_uses_latest_exact_sign_p7s(self):
        documents = self.docs(
            {"title": "sign.p7s", "datePublished": "2026-08-27T12:00:00+03:00"},
            {"title": "Файл підпису.p7s", "datePublished": "2026-08-29T12:00:00+03:00"},
            {"title": "sign.p7s", "datePublished": "2026-08-28T12:00:00+03:00"},
            {"title": "document.pdf.p7s", "datePublished": "2026-08-30T12:00:00+03:00"},
        )
        self.assertEqual(server.select_main_signature_document(documents, {}), (2, "automatic"))

    def test_equal_latest_fallback_is_ambiguous(self):
        documents = self.docs(
            {"title": "sign.p7s", "datePublished": "2026-08-28T12:00:00+03:00"},
            {"title": "SIGN.P7S", "datePublished": "2026-08-28T12:00:00+03:00"},
        )
        with self.assertRaisesRegex(ValueError, "однакову останню дату"):
            server.select_main_signature_document(documents, {})


class SignatureAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def seed(self, *, supplier_code="12345678", supplier_name='ТОВ "ТЕСТ"', manager="ІВАНЕНКО ІВАН ІВАНОВИЧ", documents=None):
        documents = documents or [{
            "id": "doc-sign", "title": "sign.p7s", "url": "https://example.test/sign.p7s",
            "hash": "sha256:official", "datePublished": "2026-08-28T10:00:00+03:00",
            "format": "application/pkcs7-signature",
        }]
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES ('f','UA-F-TEST','active','{}',?)", (server.now_iso(),))
            con.execute("""INSERT INTO submissions
              (id,framework_id,supplier_code,supplier_name,date_published,documents_json,raw_json,synced_at)
              VALUES ('s','f',?,?,?,?,'{}',?)""",
              (supplier_code, supplier_name, "2026-08-28T10:00:00+03:00", json.dumps(documents), server.now_iso()))
            con.execute("INSERT INTO application_fields(submission_id,manager_name) VALUES ('s',?)", (manager,))

    @staticmethod
    def eds(**overrides):
        signer = {
            "subjectCN": "ІВАНЕНКО ІВАН ІВАНОВИЧ",
            "subjectOrg": 'ТОВ "ТЕСТ"',
            "subjectEDRPOUCode": "12345678",
            "subjectDRFOCode": "3012345678",
            "issuerCN": "Issuer",
            "serial": "serial",
            "isTimeAvail": True,
            "isTimeStamp": True,
            "time": {"year": 2026, "month": 8, "day": 28, "hour": 10, "minute": 5, "second": 6},
        }
        signer.update(overrides)
        return {"status": "success", "signer_count": 1, "signers": [signer]}

    def analyze(self, eds=None, selection=None):
        with patch.object(server, "download_document", return_value=b"signature-bytes"), \
             patch.object(server, "verify_prozorro_eds", return_value=eds or self.eds()), \
             patch.object(server, "search_supplier_contract_experience", return_value={
                 "status": "none", "symbol": "−", "candidates": [], "message": "Не знайдено"}):
            return server.analyze_application_documents("s", selection or {"0": ["signature"]})

    @staticmethod
    def check(result, key):
        return next(item for item in result["checks"] if item["key"] == key)

    def test_code_match_and_document_identity_are_saved(self):
        self.seed()
        result = self.analyze()
        self.assertEqual(result["signature"]["code_comparison"], "match")
        self.assertIn("Відповідає коду Учасника", self.check(result, "code")["detail"])
        self.assertEqual(result["checked_signature_document"]["document_id"], "doc-sign")
        self.assertEqual(result["checked_signature_document"]["selection_source"], "manual")
        self.assertEqual(len(result["checked_signature_document"]["content_sha256"]), 64)

    def test_code_mismatch_is_warning_not_rejection(self):
        self.seed()
        result = self.analyze(self.eds(subjectEDRPOUCode="87654321"))
        self.assertEqual(result["signature"]["code_comparison"], "mismatch")
        self.assertEqual(self.check(result, "code")["status"], "warning")
        self.assertIn("Не відповідає", self.check(result, "code")["detail"])

    def test_signer_drfo_is_separate_and_not_persisted_to_manager(self):
        self.seed()
        result = self.analyze()
        self.assertEqual(self.check(result, "signer_drfo")["detail"], "3012345678")
        with server.db() as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(application_fields)")}
        self.assertNotIn("manager_tax_id", columns)

    def test_signer_name_match(self):
        self.seed()
        result = self.analyze()
        self.assertEqual(result["signature"]["signer_comparison"], "match")
        self.assertIn("Збігається з ПІБ керівника", self.check(result, "signer")["detail"])

    def test_signer_name_mismatch_requires_authority_review(self):
        self.seed()
        result = self.analyze(self.eds(subjectCN="ПЕТРЕНКО ПЕТРО ПЕТРОВИЧ"))
        self.assertEqual(result["signature"]["signer_comparison"], "mismatch")
        self.assertIn("перевірити повноваження", self.check(result, "signer")["detail"])

    def test_fop_without_subject_org_is_not_a_technical_error(self):
        self.seed(supplier_code="3012345678", supplier_name="ФОП ІВАНЕНКО І.І.")
        result = self.analyze(self.eds(subjectOrg="", subjectEDRPOUCode="", subjectDRFOCode="3012345678"))
        self.assertEqual(self.check(result, "organization")["status"], "ok")
        self.assertIn("допустимо для ФОП", self.check(result, "organization")["detail"])

    def test_qualified_certificate_is_never_inferred(self):
        self.seed()
        result = self.analyze()
        self.assertFalse(any(item["key"] == "certificate" for item in result["checks"]))
        self.assertIsNone(result["signature"]["qualified_certificate"])

    def test_certificate_issuer_is_shown_as_reference_only(self):
        self.seed()
        result = self.analyze(self.eds(issuerCN='КНЕДП ТОВ "Тестовий надавач"'))
        self.assertEqual(
            self.check(result, "certificate_issuer")["detail"],
            'КНЕДП ТОВ "Тестовий надавач"',
        )
        self.assertIsNone(result["signature"]["qualified_certificate"])

    def test_organization_is_informational_only(self):
        self.seed()
        result = self.analyze(self.eds(subjectOrg="ІНША НАЗВА"))
        organization = self.check(result, "organization")
        self.assertEqual(organization["status"], "ok")
        self.assertTrue(organization["informational"])

    def test_mvs_signature_is_not_a_separate_result_row(self):
        self.seed()
        result = self.analyze()
        self.assertFalse(any(item["key"] == "mvs_signature" for item in result["checks"]))

    def test_category_merge_preserves_previous_signature(self):
        existing = {"signature": {"signer": "A"}, "checks": [{"key": "signer", "status": "ok"}]}
        current = {"selected_categories": ["mvs"], "checks": [{"key": "mvs_extract", "status": "warning"}]}
        merged = server.merge_document_check_results(existing, current)
        self.assertEqual(merged["signature"]["signer"], "A")
        self.assertEqual(merged["category_results"]["signature"]["status"], "ok")
        self.assertEqual(merged["category_results"]["mvs"]["status"], "warning")

    def test_unavailable_eds_is_a_technical_warning(self):
        self.seed()
        result = self.analyze({"status": "service_unavailable", "error": "Сервіс тимчасово недоступний"})
        self.assertEqual(self.check(result, "eds_verification")["status"], "warning")
        self.assertIn("недоступний", self.check(result, "eds_verification")["detail"])

    def test_signing_time_is_readable(self):
        self.seed()
        result = self.analyze()
        self.assertEqual(self.check(result, "signing_time")["detail"], "28.08.2026 10:05:06")

    def test_valid_on_demand_signature_category_is_green(self):
        self.seed()
        result = self.analyze()
        self.assertEqual(server.document_check_category_summaries(result)["signature"], "ok")


if __name__ == "__main__":
    unittest.main()
