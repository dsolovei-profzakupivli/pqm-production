import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import server


class ContractExperienceSearchTests(unittest.TestCase):
    def setUp(self):
        server.CONTRACT_EXPERIENCE_CACHE.clear()

    @staticmethod
    def detail(identifier, modified="2026-08-01T10:00:00+03:00", termination=None):
        return {"id": identifier, "contractID": f"UA-CONTRACT-{identifier}",
                "status": "terminated", "dateModified": modified,
                "terminationDetails": termination, "buyer": {"name": "Замовник"}}

    def test_returns_up_to_three_historical_candidates_without_verdict(self):
        search = {"page": 1, "per_page": 20, "total": 4, "data": [
            {"contractID": "UA-CONTRACT-c1", "status": "terminated"}, {"contractID": "UA-CONTRACT-c2", "status": "terminated"},
            {"contractID": "UA-CONTRACT-c3", "status": "terminated"}, {"contractID": "UA-CONTRACT-c4", "status": "terminated"},
        ]}
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=[search, self.detail("c1"), self.detail("c2"), self.detail("c3")]):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["symbol"], "+")
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["candidates"][0]["url"],
                         "https://prozorro.gov.ua/uk/contract/UA-CONTRACT-c1")
        self.assertTrue(all(item["url"].startswith("https://prozorro.gov.ua/uk/contract/")
                            for item in result["candidates"]))
        self.assertIn("proxy", result["cutoff_note"])

    def test_contract_badge_is_green_only_when_candidate_found(self):
        found = {"category_results": {"experience": {"status": "neutral", "checks": [{
            "key": "contract_experience", "status": "neutral", "search_status": "found",
        }]}}}
        none = {"category_results": {"experience": {"status": "error", "checks": [{
            "key": "contract_experience", "status": "neutral", "search_status": "none",
        }]}}}
        unavailable = {"checks": [{
            "key": "contract_experience", "status": "error", "search_status": "unavailable",
        }]}
        self.assertEqual(server.document_check_category_summaries(found)["experience"], "ok")
        self.assertEqual(server.document_check_category_summaries(none)["experience"], "neutral")
        self.assertEqual(server.document_check_category_summaries(unavailable)["experience"], "neutral")

    def test_excludes_late_modified_and_terminated_with_details(self):
        search = {"page": 1, "per_page": 20, "total": 2, "data": [
            {"contractID": "UA-CONTRACT-late", "status": "terminated"}, {"contractID": "UA-CONTRACT-breach", "status": "terminated"}]}
        with patch.object(server, "_contract_experience_http_json", side_effect=[
                search, self.detail("late", "2026-08-26T10:00:00+03:00"),
                self.detail("breach", termination="Розірвано через порушення")]):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["symbol"], "−")
        self.assertEqual(result["candidates"], [])

    def test_real_search_contract_ids_use_public_detail_route(self):
        search = {"page": 1, "per_page": 20, "total": 2, "data": [
            {"contractID": "UA-2025-07-03-010253-a-a1", "status": "terminated"},
            {"contractID": "UA-2025-06-06-006327-a-a1", "status": "terminated"},
        ]}
        details = [
            {"id": "internal-1", "contractID": row["contractID"], "status": "terminated",
             "dateModified": "2025-12-01T10:00:00+02:00", "terminationDetails": ""}
            for row in search["data"]
        ]
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=[search, *details]) as fetch:
            result = server.search_supplier_contract_experience(
                "31280027", "44110000-4", "2026-08-27T00:00:00+03:00")
        self.assertEqual([item["contract_id"] for item in result["candidates"]],
                         ["UA-2025-07-03-010253-a-a1", "UA-2025-06-06-006327-a-a1"])
        self.assertIn("/api/contracts/UA-2025-07-03-010253-a-a1", fetch.call_args_list[1].args[0])

    def test_api_error_is_neutral_and_cached(self):
        with patch.object(server, "_contract_experience_http_json", side_effect=OSError("offline")) as fetch:
            first = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
            second = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(first["status"], "unavailable")
        self.assertEqual(first["symbol"], "−")
        self.assertEqual(second, first)
        # ``unavailable`` has a short in-memory TTL, but the immediate second
        # call still reuses it instead of hammering the external API.
        self.assertEqual(fetch.call_count, 2)

    @staticmethod
    def fallback_responses(candidate_cpv="44191200-7", supplier="12345678", lot_id="lot-1"):
        exact_empty = {"page": 1, "per_page": 20, "total": 0, "data": []}
        fallback = {"page": 1, "per_page": 20, "total": 1, "data": [
            {"contractID": "UA-CONTRACT-fallback", "status": "terminated"}
        ]}
        portal = {"id": "internal-fallback", "contractID": "UA-CONTRACT-fallback",
                  "status": "terminated", "dateModified": "2026-08-01T10:00:00+03:00",
                  "terminationDetails": "", "buyer": {"name": "Замовник"}}
        raw = {"data": {"id": "internal-fallback", "contractID": "UA-CONTRACT-fallback",
                "status": "terminated", "tender_id": "tender-internal", "awardID": "award-1",
                "suppliers": [{"identifier": {"id": supplier}}],
                "items": [{"relatedLot": lot_id, "classification": {"id": candidate_cpv}}]}}
        tender = {"data": {"id": "tender-internal", "awards": [{"id": "award-1", "lotID": lot_id,
                   "suppliers": [{"identifier": {"id": supplier}}]}],
                   "items": [{"relatedLot": lot_id, "classification": {"id": candidate_cpv}}]}}
        return [exact_empty, fallback, portal, raw, tender]

    def test_exact_search_success_does_not_start_supplier_only_fallback(self):
        search = {"page": 1, "per_page": 20, "total": 1, "data": [
            {"contractID": "UA-CONTRACT-exact", "status": "terminated"}
        ]}
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=[search, self.detail("exact")]) as fetch:
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["candidates"][0]["discovery_mode"], "exact")
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("cpv", fetch.call_args_list[0].args[1])

    def test_exact_empty_runs_supplier_only_and_accepts_same_cpv_group(self):
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=self.fallback_responses()) as fetch:
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "found")
        row = result["candidates"][0]
        self.assertEqual(row["discovery_mode"], "fallback")
        self.assertEqual(row["resolved_cpv"], "44191200-7")
        self.assertEqual(row["lot_id"], "lot-1")
        self.assertEqual(row["cpv_match"], "cpv_prefix_4")
        self.assertNotIn("cpv", fetch.call_args_list[1].args[1])

    def test_fallback_rejects_different_supplier(self):
        responses = self.fallback_responses(supplier="87654321")
        with patch.object(server, "_contract_experience_http_json", side_effect=responses):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "none")

    def test_fallback_rejects_unrelated_cpv(self):
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=self.fallback_responses(candidate_cpv="34351100-3")):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "none")

    def test_lot_resolution_uses_only_award_lot_items(self):
        responses = self.fallback_responses(candidate_cpv="44191200-7", lot_id="lot-good")
        responses[-1]["data"]["items"].insert(
            0, {"relatedLot": "lot-other", "classification": {"id": "34351100-3"}}
        )
        with patch.object(server, "_contract_experience_http_json", side_effect=responses):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["candidates"][0]["resolved_cpvs"], ["44191200-7"])

    def test_one_detail_failure_does_not_discard_other_candidate(self):
        search = {"page": 1, "per_page": 20, "total": 2, "data": [
            {"contractID": "UA-CONTRACT-failed", "status": "terminated"},
            {"contractID": "UA-CONTRACT-good", "status": "terminated"},
        ]}
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=[search, OSError("one detail failed"), self.detail("good")]):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "found")
        self.assertEqual([row["contract_id"] for row in result["candidates"]], ["UA-CONTRACT-good"])

    def test_all_detail_requests_fail_returns_unavailable(self):
        search = {"page": 1, "per_page": 20, "total": 2, "data": [
            {"contractID": "UA-CONTRACT-a", "status": "terminated"},
            {"contractID": "UA-CONTRACT-b", "status": "terminated"},
        ]}
        empty_fallback = {"page": 1, "per_page": 20, "total": 0, "data": []}
        with patch.object(server, "_contract_experience_http_json",
                          side_effect=[search, OSError("a"), OSError("b"), empty_fallback]):
            result = server.search_supplier_contract_experience(
                "12345678", "44190000-8", "2026-08-25T12:00:00+03:00")
        self.assertEqual(result["status"], "unavailable")

    def test_cpv_policy_normalizes_and_uses_one_configured_prefix(self):
        self.assertEqual(server.cpv_matches_experience("4419 0000-8", "44191200-7"),
                         (True, "cpv_prefix_4"))
        self.assertEqual(server.cpv_matches_experience("44190000-8", "34351100-3"),
                         (False, "unrelated"))

    def test_http_429_and_5xx_are_retried(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": []}'
        response.__enter__.return_value.__exit__.return_value = False
        errors = [
            urllib.error.HTTPError("https://example.test", 429, "rate", {"Retry-After": "0"}, None),
            urllib.error.HTTPError("https://example.test", 503, "down", {}, None),
            response,
        ]
        with patch("urllib.request.urlopen", side_effect=errors) as fetch, patch("time.sleep"):
            result = server._contract_experience_http_json("https://example.test")
        self.assertEqual(result, {"data": []})
        self.assertEqual(fetch.call_count, 3)

    def test_network_timeout_is_retried(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": []}'
        response.__enter__.return_value.__exit__.return_value = False
        with patch("urllib.request.urlopen", side_effect=[TimeoutError("slow"), response]) as fetch, \
             patch("time.sleep"):
            result = server._contract_experience_http_json("https://example.test")
        self.assertEqual(result, {"data": []})
        self.assertEqual(fetch.call_count, 2)

    def test_formatted_supplier_identifier_matches_after_normalization(self):
        parties = [{"identifier": {"id": "UA-EDR 12-345-678"}}]
        self.assertTrue(server.supplier_matches_experience("12 345 678", parties))

    def test_legacy_2016_shape_passes_unchanged_detail_predicates(self):
        detail = self.detail("legacy", modified="2021-10-05T11:25:36+03:00", termination="")
        resolved, reason = server.validate_contract_candidate(
            detail, "2729718444", "03210000-6",
            server._contract_experience_cutoff("2026-09-10T16:33:26+03:00"), "exact",
        )
        self.assertEqual(reason, "accepted")
        self.assertEqual(resolved["cpv_match"], "external_exact")

    def test_stored_unavailable_is_never_fresh(self):
        stored = {"category_results": {"experience": {"checked_at": server.now_iso(), "checks": [{
            "key": "contract_experience", "algorithm_version": server.CONTRACT_EXPERIENCE_ALGORITHM_VERSION,
            "search_status": "unavailable",
        }]}}}
        self.assertFalse(server._stored_experience_is_fresh(stored))

    def test_legacy_document_experience_is_hidden_without_rewriting_history(self):
        stored = {"checks": [{"key": "business_contract", "status": "error"},
                              {"key": "signer", "status": "ok"}],
                  "category_results": {
                      "experience": {"status": "error", "checks": [
                          {"key": "business_contract", "status": "error"}]},
                      "signature": {"status": "ok", "checks": [
                          {"key": "signer", "status": "ok"}]}}}
        visible = server.current_document_check_result(stored)
        self.assertEqual([item["key"] for item in visible["checks"]], ["signer"])
        self.assertNotIn("experience", visible["category_results"])
        self.assertIn("experience", stored["category_results"])

    def test_legacy_cached_uuid_url_is_normalized_from_public_contract_id_on_read(self):
        old_url = "https://prozorro.gov.ua/contract/82c2aaefa2154d6288cfb25c7698da57"
        expected = "https://prozorro.gov.ua/uk/contract/UA-2024-10-22-004409-a-a1"
        row = {"id": "82c2aaefa2154d6288cfb25c7698da57",
               "contract_id": "UA-2024-10-22-004409-a-a1", "url": old_url}
        stored = {"checks": [{"key": "contract_experience", "rows": [dict(row)]}],
                  "contract_experience": {"candidates": [dict(row)]},
                  "category_results": {"experience": {"status": "ok", "checks": [
                      {"key": "contract_experience", "search_status": "found", "rows": [dict(row)]}
                  ]}}}
        visible = server.current_document_check_result(stored)
        self.assertEqual(visible["checks"][0]["rows"][0]["url"], expected)
        self.assertEqual(visible["category_results"]["experience"]["checks"][0]["rows"][0]["url"], expected)
        self.assertEqual(visible["contract_experience"]["candidates"][0]["url"], expected)
        self.assertEqual(stored["checks"][0]["rows"][0]["url"], old_url)


class OnDemandDocumentCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
        documents = [{"id": "sign", "title": "sign.p7s", "url": "https://example.test/sign.p7s"},
                     {"id": "mvs", "title": "Витяг МВС.pdf", "url": "https://example.test/mvs.pdf"},
                     {"id": "mvs-sign", "title": "Витяг МВС.pdf.p7s", "url": "https://example.test/mvs.p7s"}]
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,dk_code,raw_json,synced_at) VALUES ('f','UA-F','active','44190000-8','{}',?)", (server.now_iso(),))
            con.execute("""INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,documents_json,raw_json,synced_at)
                           VALUES ('s','f','12345678','ТОВ ТЕСТ','2026-08-25T12:00:00+03:00',?,'{}',?)""",
                        (json.dumps(documents), server.now_iso()))
            con.execute("INSERT INTO application_fields(submission_id,manager_name) VALUES ('s','ІВАНЕНКО ІВАН ІВАНОВИЧ')")

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_empty_selection_does_not_run_kep_mvs_or_ocr(self):
        neutral = {"status": "none", "symbol": "−", "candidates": [], "message": "Не знайдено"}
        with patch.object(server, "download_document") as download, \
             patch.object(server, "verify_prozorro_eds") as verify, \
             patch.object(server, "pdf_ocr_text") as ocr, \
             patch.object(server, "search_supplier_contract_experience", return_value=neutral) as search:
            result = server.analyze_application_documents("s", {})
        download.assert_not_called()
        verify.assert_not_called()
        ocr.assert_not_called()
        search.assert_not_called()
        self.assertEqual(result["selected_categories"], [])
        self.assertEqual(result["checks"], [])

    def test_background_search_persists_experience_and_fresh_result_is_reused(self):
        found = {"status": "found", "symbol": "+", "message": "Знайдено: 1",
                 "candidates": [{"contract_id": "UA-2024-10-22-004409-a-a1",
                                  "url": "https://prozorro.gov.ua/uk/contract/UA-2024-10-22-004409-a-a1"}]}
        with patch.object(server, "search_supplier_contract_experience", return_value=found) as search:
            server.contract_experience_worker(["s"])
            server.contract_experience_worker(["s"])
        self.assertEqual(search.call_count, 1)
        with server.db() as con:
            stored = json.loads(con.execute(
                "SELECT document_check_result_json FROM application_fields WHERE submission_id='s'"
            ).fetchone()[0])
        check = stored["category_results"]["experience"]["checks"][0]
        self.assertEqual(check["search_status"], "found")
        self.assertEqual(check["rows"][0]["contract_id"], "UA-2024-10-22-004409-a-a1")
        self.assertEqual(server.document_check_category_summaries(stored)["experience"], "ok")

    def test_background_none_result_uses_normal_freshness(self):
        none = {"status": "none", "symbol": "−", "message": "Не знайдено",
                "candidates": [], "algorithm_version": server.CONTRACT_EXPERIENCE_ALGORITHM_VERSION}
        with patch.object(server, "search_supplier_contract_experience", return_value=none) as search:
            server.contract_experience_worker(["s"])
            server.contract_experience_worker(["s"])
        self.assertEqual(search.call_count, 1)

    def test_background_unavailable_result_schedules_retry(self):
        unavailable = {"status": "unavailable", "symbol": "−", "message": "Тимчасово недоступно",
                       "candidates": [], "algorithm_version": server.CONTRACT_EXPERIENCE_ALGORITHM_VERSION}
        with patch.object(server, "search_supplier_contract_experience", return_value=unavailable), \
             patch.object(server, "_schedule_contract_experience_retry", return_value=True) as schedule:
            server.contract_experience_worker(["s"])
        schedule.assert_called_once_with("s")

    @staticmethod
    def mvs_extract(extract_type="full"):
        absent = {"found": True, "value": "ВІДСУТНІ", "absent": True}
        return {"type": extract_type, "person_name": "ІВАНЕНКО ІВАН ІВАНОВИЧ",
                "manager_name": "ІВАНЕНКО ІВАН ІВАНОВИЧ", "person_matches_manager": True,
                "issue_date": "2026-08-20", "submitted_date": "2026-08-25", "age_days": 5,
                "within_30_days": True, "criminal_liability": absent,
                "unspent_conviction": absent, "wanted_status": absent}

    def analyze_mvs(self, extract_type="full"):
        neutral = {"status": "none", "symbol": "−", "candidates": [], "message": "Не знайдено"}
        eds = {"status": "success", "signers": [{
            "subjectEDRPOUCode": "00032684",
            "subjectOrg": "МІНІСТЕРСТВО ВНУТРІШНІХ СПРАВ УКРАЇНИ"}]}
        with patch.object(server, "download_document", return_value=b"%PDF-test"), \
             patch.object(server, "pdf_text", return_value="readable"), \
             patch.object(server, "_needs_ukrainian_ocr", return_value=False), \
             patch.object(server, "pdf_has_unreadable_pages", return_value=False), \
             patch.object(server, "verify_prozorro_eds", return_value=eds), \
             patch.object(server, "analyze_mvs_extract", return_value=self.mvs_extract(extract_type)), \
             patch.object(server, "search_supplier_contract_experience", return_value=neutral):
            return server.analyze_application_documents("s", {"1": ["mvs"], "2": ["mvs_signature"]})

    def test_valid_mvs_and_verified_signature_are_green(self):
        result = self.analyze_mvs()
        self.assertEqual(server.document_check_category_summaries(result)["mvs"], "ok")
        seal = next(item for item in result["checks"] if item["key"] == "mvs_seal")
        self.assertEqual(seal["status"], "ok")

    def test_short_mvs_extract_is_red(self):
        result = self.analyze_mvs("short")
        extract_type = next(item for item in result["checks"] if item["key"] == "mvs_extract_type")
        self.assertEqual(extract_type["status"], "error")


if __name__ == "__main__":
    unittest.main()
