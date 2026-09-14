import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from declension import DeclensionResult
from violation_text import normalize_justification_text


def organization(code):
    return {"identifier": {"id": code}, "name": code}


def report_payload(decisions=None):
    return {
        "id": "report-internal", "violationReportID": "UA-D-TEST", "status": "pending",
        "datePublished": "2026-08-18T10:00:00+03:00", "dateModified": "2026-08-18T10:00:00+03:00",
        "defendantPeriod": {"endDate": "2026-08-21T18:00:00+03:00"},
        "tender_id": "tender-id", "author": organization("11111111"),
        "defendants": [organization("22222222")], "authority": organization("40996564"),
        "details": {"reason": "contractBreach", "documents": [
            {"id": "customer-doc", "title": "Доказ.docx", "url": "https://example.test/customer"}
        ]},
        "defendantStatements": [{"id": "statement", "description": "Пояснення", "documents": [
            {"id": "supplier-doc", "title": "Пояснення.pdf", "url": "https://example.test/supplier"}
        ]}],
        "decisions": decisions or [],
    }


class ViolationReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
        server.save_violation_report(report_payload())

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_justification_plain_text_normalization(self):
        raw = "\tПерший абзац.\r\n\r\n  Другий абзац.\rТретій абзац.\n\n"
        self.assertEqual(
            normalize_justification_text(raw),
            "Перший абзац.\nДругий абзац.\nТретій абзац.",
        )

    def test_review_saved_only_without_official_decision(self):
        with patch.object(server, "api_get", return_value={"data": report_payload()}):
            result = server.save_violation_review("report-internal", {"review_status": "in_review"})
        self.assertFalse(result["is_read_only"])
        self.assertEqual(result["review"]["review_status"], "in_review")

    def test_contract_requisites_are_manual_and_survive_save_and_sync(self):
        external = {"available": True, "contract_pretty_id": "UA-AUTO-a1",
                    "contract_date": "2026-01-01", "contract_url": "https://auto.invalid"}
        with patch.object(server, "api_get", return_value={"data": report_payload()}), \
                patch.object(server, "build_procurement_context", return_value=external):
            saved = server.save_violation_review("report-internal", {
                "actual_contract_signed": True,
                "actual_contract_date": "2026-09-07",
                "actual_contract_number": "MANUAL-77",
                "actual_contract_url": "https://manual.example/77",
            })
            repeated = server.save_violation_review("report-internal", {"review_notes": "Повторний Save"})
        server.save_violation_report(report_payload())
        with patch.object(server, "build_procurement_context", return_value=external):
            after_sync = server.violation_report_detail("report-internal", refresh=False)
        for item in (saved, repeated, after_sync):
            self.assertTrue(item["review"]["actual_contract_signed"])
            self.assertEqual(item["review"]["actual_contract_date"], "2026-09-07")
            self.assertEqual(item["review"]["actual_contract_number"], "MANUAL-77")
            self.assertEqual(item["review"]["actual_contract_url"], "https://manual.example/77")

    def test_customer_names_reuse_latest_saved_same_code_and_current_values_win(self):
        historical=report_payload();historical.update(id='historical-report',violationReportID='UA-D-HISTORICAL')
        server.save_violation_report(historical)
        now=server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,customer_verified_full_name,customer_verified_short_name,updated_at,updated_by)
              VALUES (?,?,?,?,?)""",('historical-report','ПОВНА НАЗВА З ІСТОРІЇ','СКОРОЧЕНА З ІСТОРІЇ',now,'УО'))
        with patch.object(server,'build_procurement_context',return_value={'available':False}):
            reused=server.violation_report_detail('report-internal',refresh=False)
        self.assertEqual(reused['review']['customer_verified_full_name'],'ПОВНА НАЗВА З ІСТОРІЇ')
        self.assertEqual(reused['review']['customer_verified_short_name'],'СКОРОЧЕНА З ІСТОРІЇ')
        self.assertEqual(reused['review']['customer_name_reuse_sources']['customer_verified_full_name'],'UA-D-HISTORICAL')
        server.init_db()
        with patch.object(server,'build_procurement_context',return_value={'available':False}):
            after_restart=server.violation_report_detail('report-internal',refresh=False)
        self.assertEqual(after_restart['review']['customer_verified_full_name'],'ПОВНА НАЗВА З ІСТОРІЇ')
        self.assertEqual(after_restart['review']['customer_verified_short_name'],'СКОРОЧЕНА З ІСТОРІЇ')
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,customer_verified_full_name,customer_verified_short_name,updated_at,updated_by)
              VALUES (?,?,?,?,?)""",('report-internal','ПОТОЧНА ПОВНА','ПОТОЧНА СКОРОЧЕНА',server.now_iso(),'УО'))
        with patch.object(server,'build_procurement_context',return_value={'available':False}):
            current=server.violation_report_detail('report-internal',refresh=False)
        self.assertEqual(current['review']['customer_verified_full_name'],'ПОТОЧНА ПОВНА')
        self.assertEqual(current['review']['customer_verified_short_name'],'ПОТОЧНА СКОРОЧЕНА')
        self.assertNotIn('customer_name_reuse_sources',current['review'])

    def test_contract_checkbox_can_be_cleared_without_technical_repopulation(self):
        external = {"available": True, "contract_pretty_id": "UA-AUTO-a1",
                    "contract_date": "2026-01-01", "contract_url": "https://auto.invalid"}
        with patch.object(server, "api_get", return_value={"data": report_payload()}), \
                patch.object(server, "build_procurement_context", return_value=external):
            server.save_violation_review("report-internal", {
                "actual_contract_signed": True, "actual_contract_date": "2026-09-07",
                "actual_contract_number": "MANUAL-77"})
            cleared = server.save_violation_review("report-internal", {"actual_contract_signed": False})
        self.assertFalse(cleared["review"]["actual_contract_signed"])
        source = (server.ROOT / "app.js").read_text(encoding="utf-8")
        active = source[source.rfind("function violationReasonFields(item)"):
                        source.rfind("requestContextBlock=function(item)")]
        self.assertNotIn("r.actual_contract_number||c.contract_pretty_id", active)
        self.assertNotIn("r.actual_contract_date||String(c.contract_date", active)

    def test_legacy_assigned_officer_fallback_and_patch_round_trip(self):
        with server.db() as connection:
            officer = connection.execute(
                "SELECT id,full_name FROM authorized_officers WHERE active=1 ORDER BY id LIMIT 1").fetchone()
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,assigned_officer,review_notes,updated_at,updated_by)
                VALUES (?,?,?,?,?)""", ("report-internal", officer["full_name"].lower(),
                "Не змінювати", server.now_iso(), "Тест"))
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertIsNone(detail["review"]["assigned_officer_id"])
        self.assertEqual(detail["review"]["assigned_officer_effective_id"], officer["id"])
        self.assertEqual(detail["review"]["assigned_officer_display"],
                         server.formatted_officer_name(officer["full_name"]))
        with patch.object(server, "api_get", return_value={"data": report_payload()}), \
                patch.object(server, "build_procurement_context", return_value={"available": False}):
            saved = server.save_violation_review("report-internal", {
                "assigned_officer_id": officer["id"]})
        self.assertEqual(saved["review"]["assigned_officer_id"], officer["id"])
        self.assertEqual(saved["review"]["assigned_officer_effective_id"], officer["id"])
        self.assertEqual(saved["review"]["review_notes"], "Не змінювати")
        server.save_violation_report(report_payload())
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            reopened = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(reopened["review"]["assigned_officer_effective_id"], officer["id"])
        self.assertEqual(reopened["review"]["review_notes"], "Не змінювати")

    def test_managed_assigned_officer_survives_detail_reload(self):
        with server.db() as connection:
            officer = connection.execute(
                "SELECT id,full_name FROM authorized_officers WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        with patch.object(server, "api_get", return_value={"data": report_payload()}), \
                patch.object(server, "build_procurement_context", return_value={"available": False}):
            saved = server.save_violation_review("report-internal", {
                "assigned_officer_id": officer["id"], "review_notes": "Контроль"})
            reopened = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(saved["review"]["assigned_officer_effective_id"], officer["id"])
        self.assertEqual(reopened["review"]["assigned_officer_effective_id"], officer["id"])
        self.assertEqual(reopened["review"]["assigned_officer"], officer["full_name"])
        self.assertEqual(reopened["review"]["review_notes"], "Контроль")

    def test_official_decision_blocks_patch_without_overwriting_review(self):
        with patch.object(server, "api_get", return_value={"data": report_payload()}):
            server.save_violation_review("report-internal", {"review_notes": "Зберегти"})
        official = {"id": "decision", "resolution": "satisfied", "documents": []}
        with patch.object(server, "api_get", return_value={"data": report_payload([official])}):
            with self.assertRaises(PermissionError):
                server.save_violation_review("report-internal", {"review_notes": "Не записувати"})
        with server.db() as connection:
            note = connection.execute("SELECT review_notes FROM violation_report_reviews").fetchone()[0]
        self.assertEqual(note, "Зберегти")

    def test_document_review_is_sparse_audited_and_survives_prozorro_sync(self):
        with server.db() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM violation_report_document_reviews").fetchone()[0], 0)
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            result = server.save_violation_document_review(
                "report-internal", "customer", "customer-doc", True, "Тестова УО")
        document = result["evidence_documents"][0]
        self.assertTrue(document["manual_reviewed"])
        self.assertTrue(document["file_unavailable"])
        server.save_violation_report(report_payload())
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            refreshed = server.violation_report_detail("report-internal", refresh=False)
        self.assertTrue(refreshed["evidence_documents"][0]["file_unavailable"])
        with server.db() as connection:
            row = connection.execute(
                "SELECT checked_by,file_unavailable FROM violation_report_document_reviews").fetchone()
            event = connection.execute("""SELECT field_name,new_value FROM violation_report_review_events
                WHERE field_name='document_unavailable:customer:customer-doc'""").fetchone()
        self.assertEqual(tuple(row), ("Тестова УО", 1))
        self.assertEqual(tuple(event), ("document_unavailable:customer:customer-doc", "1"))

    def test_unavailable_document_does_not_change_review_decision(self):
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            server.save_violation_document_review(
                "report-internal", "supplier", "supplier-doc", True, "Тестова УО")
        with server.db() as connection:
            review = connection.execute(
                "SELECT * FROM violation_report_reviews WHERE report_id='report-internal'").fetchone()
        self.assertIsNone(review)

    def test_fail_closed_when_prozorro_unavailable(self):
        with patch.object(server, "api_get", side_effect=OSError("offline")):
            with self.assertRaises(ConnectionError):
                server.save_violation_review("report-internal", {"review_status": "in_review"})

    def test_official_supplier_deadline_uses_exact_timestamp(self):
        report = {
            "date_published": "2026-08-26T10:45:58+03:00",
            "defendant_period_end": "2026-09-01T00:00:00+03:00",
        }
        before = server._parse_prozorro_date("2026-08-31T23:59:59+03:00")
        at_boundary = server._parse_prozorro_date("2026-09-01T00:00:00+03:00")
        self.assertFalse(server.violation_deadline_control(report, before)["supplier_ready"])
        self.assertTrue(server.violation_deadline_control(report, at_boundary)["supplier_ready"])
        self.assertEqual(server.violation_deadline_control(report, at_boundary)["supplier_official_deadline"],
                         "2026-09-01T00:00:00+03:00")

    def test_local_three_day_control_never_unlocks_missing_official_deadline(self):
        report = {"date_published": "2026-08-01T10:00:00+03:00", "defendant_period_end": ""}
        control = server.violation_deadline_control(
            report, server._parse_prozorro_date("2026-09-01T12:00:00+03:00"))
        self.assertFalse(control["supplier_ready"])
        self.assertTrue(control["supplier_deadline_missing"])

    def test_foreign_authority_is_read_only_and_all_mutations_fail_closed(self):
        payload = report_payload()
        payload["authority"] = organization("42574629")
        server.save_violation_report(payload)
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertTrue(detail["foreign_authority_read_only"])
        self.assertTrue(detail["is_read_only"])
        with patch.object(server, "api_get", return_value={"data": payload}):
            with self.assertRaises(server.ForeignAuthorityError):
                server.save_violation_review("report-internal", {"review_notes": "Заборонено"})
        with self.assertRaises(server.ForeignAuthorityError):
            server.save_violation_document_review(
                "report-internal", "customer", "customer-doc", True, "Адміністратор")

    def test_weekend_shift_and_extension(self):
        start = server._parse_prozorro_date("2026-08-17T10:00:00+03:00")
        five = server._calendar_deadline(start, 5)
        ten = server._calendar_deadline(start, 10)
        self.assertEqual(five["calendar_day"], "2026-08-22")
        self.assertEqual(five["deadline"], "2026-08-24")
        self.assertTrue(five["shifted"])
        self.assertEqual(ten["deadline"], "2026-08-27")

    def test_five_day_deadline_uses_full_calendar_day(self):
        start = server._parse_prozorro_date("2026-08-14T10:15:00+03:00")
        deadline = server._calendar_deadline(start, 5)
        self.assertEqual(deadline["deadline"], "2026-08-19")
        self.assertTrue(server._within_calendar_deadline(
            server._parse_prozorro_date("2026-08-19T23:59:59+03:00"), deadline["deadline"]))
        self.assertFalse(server._within_calendar_deadline(
            server._parse_prozorro_date("2026-08-20T00:00:00+03:00"), deadline["deadline"]))

    def test_shifted_monday_is_included_in_full(self):
        start = server._parse_prozorro_date("2026-08-17T10:00:00+03:00")
        deadline = server._calendar_deadline(start, 5)
        self.assertEqual(deadline["deadline"], "2026-08-24")
        self.assertTrue(server._within_calendar_deadline(
            server._parse_prozorro_date("2026-08-24T23:59:59+03:00"), deadline["deadline"]))
        self.assertFalse(server._within_calendar_deadline(
            server._parse_prozorro_date("2026-08-25T00:00:00+03:00"), deadline["deadline"]))

    def test_p1_business_logic_uses_effective_weekend_deadline(self):
        tender = {"data": {"tenderID": "UA-TEST", "awards": [
            {"id": "winner", "qualified": True, "status": "active",
             "period": {"startDate": "2026-08-17T10:00:00+03:00"},
             "suppliers": [organization("22222222")]},
            {"id": "rejected", "qualified": False, "status": "unsuccessful",
             "date": "2026-08-23T18:00:00+03:00", "title": "Не підписано договір",
             "suppliers": [organization("22222222")]},
        ], "contracts": [], "items": []}}
        with patch.object(server, "api_get", return_value=tender):
            context = server.build_procurement_context({
                "tender_id": "tender-id", "defendant_code": "22222222",
                "reason": "contractBreach",
            })
        self.assertEqual(context["day_5"], "2026-08-22")
        self.assertTrue(context["day_5_shifted"])
        self.assertEqual(context["contract_deadline"], "2026-08-24")
        self.assertTrue(context["rejected_before_deadline"])
        recommendation = server.violation_rules_engine("contractBreach", {
            **context, "supplier_deadline_ready": True, "defendant_statements_present": False,
        }, {})
        self.assertEqual(recommendation["recommended_decision"], "decline")

    def test_p1_decline_justification_ordinary_deadline_matches_recommendation(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "rejected_before_deadline": True,
            "winner_selected_at": "2026-09-02T10:00:00+03:00",
            "day_5": "2026-09-07", "day_5_shifted": False,
            "contract_deadline": "2026-09-07", "rejection_date": "2026-09-06T12:00:00+03:00",
        }
        review = {"internal_decision": "decline"}
        self.assertEqual(server.violation_decision_template_key(report, context, review),
                         "p49_1_decline_before_deadline")
        recommendation = server.violation_rules_engine("contractBreach", context, review)
        self.assertEqual(recommendation["recommended_decision"], "decline")
        self.assertEqual(recommendation["recommendation_reason"],
                         "Пропозицію постачальника відхилено до закінчення строку, передбаченого п. 66 Порядку № 822 для укладення договору.")
        text = server.build_violation_decision_justification(report, context, review)
        self.assertIn("Граничним днем для укладення договору у цій закупівлі є 07.09.2026", text)
        self.assertIn("Замовник відхилив пропозицію Постачальника 06.09.2026", text)
        self.assertNotIn("ст. 254 Цивільного кодексу України", text)

    def test_p1_decline_before_deadline_adds_security_only_when_required(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "rejected_before_deadline": True,
            "winner_selected_at": "2026-08-24T08:00:00+03:00",
            "day_5": "2026-08-29", "day_5_weekday_uk": "субота", "day_5_shifted": True,
            "contract_deadline": "2026-08-31", "contract_deadline_weekday_uk": "понеділок",
            "rejection_date": "2026-08-31T15:22:00+03:00",
            "performance_security_required": True,
        }
        review = {"internal_decision": "decline"}
        text = server.build_violation_decision_justification(report, context, review)
        self.assertIn("припадає на 29.08.2026 (субота)", text)
        self.assertIn("переноситься на понеділок 31.08.2026", text)
        self.assertIn("забезпечення виконання договору надається постачальником до або під час укладення", text)
        self.assertIn("відмову в задоволенні звернення Замовника", text)
        without_security = server.build_violation_decision_justification(
            report, {**context, "performance_security_required": False,
                     "contract_guarantee_required": False}, review)
        self.assertNotIn("забезпечення виконання договору надається постачальником", without_security)

    def test_p1_decline_security_without_shift_keeps_security_but_omits_civil_code(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "rejected_before_deadline": True,
            "winner_selected_at": "2026-09-02T10:00:00+03:00",
            "day_5": "2026-09-07", "day_5_shifted": False,
            "contract_deadline": "2026-09-07", "rejection_date": "2026-09-06T12:00:00+03:00",
            "performance_security_required": True,
        }
        text = server.build_violation_decision_justification(
            report, context, {"internal_decision": "decline"})
        self.assertIn("строк для виконання цієї дії також вважається таким, що не закінчився", text)
        self.assertNotIn("ст. 254 ЦК України", text)
        self.assertNotIn("переноситься на", text)

    def test_p1_decline_justification_weekend_uses_structured_shift(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "rejected_before_deadline": True,
            "winner_selected_at": "2026-08-24T08:00:00+03:00",
            "day_5": "2026-08-29", "day_5_weekday_uk": "субота", "day_5_shifted": True,
            "contract_deadline": "2026-08-31", "rejection_date": "2026-08-31T15:22:00+03:00",
        }
        review = {"internal_decision": "decline"}
        self.assertEqual(server.violation_decision_template_key(report, context, review),
                         "p49_1_decline_before_deadline_civil_shift")
        text = server.build_violation_decision_justification(report, context, review)
        self.assertIn("п’ятий календарний день припадає на 29.08.2026 (субота)", text)
        self.assertIn("ч. 5 ст. 254 ЦК України", text)
        self.assertIn("переноситься на перший робочий день 31.08.2026", text)
        self.assertIn("Замовник відхилив пропозицію Постачальника 31.08.2026", text)

    def test_contract_deadline_ui_uses_structured_shift_values_only(self):
        source = (server.ROOT / "app.js").read_text(encoding="utf-8")
        start = source.index("function violationReasonFields(item)")
        end = source.index("requestContextBlock=function(item)", start)
        renderer = source[start:end]
        self.assertIn("const shiftedWeekday=String(c.day_5_weekday_uk||'').trim()", renderer)
        self.assertIn("const shiftedDeadline=c.day_5_shifted?(shiftedWeekday?", renderer)
        self.assertIn("displayDateOnly(c.day_5)", renderer)
        self.assertIn("c.day_5_weekday_uk", renderer)
        self.assertIn("displayDateOnly(c.contract_deadline)", renderer)
        self.assertIn("5-й календарний день:", renderer)
        self.assertIn("Строк перенесено на перший робочий день відповідно до ч. 5 ст. 254 ЦК України.", renderer)
        self.assertIn("${shiftedDeadline}", renderer)
        self.assertIn("backend не повернув day_5_weekday_uk", renderer)
        self.assertNotIn("(${esc(c.day_5_weekday_uk)||'—'})", renderer)
        self.assertNotIn("getDay(", renderer)
        self.assertNotIn("new Date(c.day_5", renderer)

    def test_contract_checkbox_visibility_uses_complete_rejection_facts(self):
        self.assertFalse(server.violation_has_complete_rejection({}))
        self.assertFalse(server.violation_has_complete_rejection({
            "rejection_date": "2026-09-01", "rejection_title": ""}))
        self.assertFalse(server.violation_has_complete_rejection({
            "rejection_date": None, "rejection_title": "Відхилено"}))
        self.assertTrue(server.violation_has_complete_rejection({
            "rejection_date": "2026-09-01", "rejection_title": "Відхилено"}))
        source = (server.ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function violationHasCompleteRejection(context={})", source)
        self.assertIn("context.rejection_date&&String(context.rejection_reason||context.rejection_title||context.rejection_description||'').trim()", source)
        self.assertIn("const contractState=violationHasCompleteRejection(c)?'':", source)

    def test_rejected_offer_ignores_but_does_not_clear_saved_contract_value(self):
        item = {
            "reason": "goodsNonCompliance",
            "deadline_control": {"supplier_ready": True},
            "has_official_decision": False,
            "procurement_context": {
                "available": True, "rejection_date": "2026-09-01",
                "rejection_description": "Документи не відповідають вимогам",
            },
            "review": {
                "assigned_officer": "УО", "internal_decision": "decline",
                "decision_justification": "Збережене обґрунтування",
                "protocol_number": "1", "protocol_date": "2026-09-08",
                "actual_contract_signed": True,
                "actual_contract_date": "", "actual_contract_number": "",
            },
        }
        gate = server.violation_protocol_readiness(item)
        self.assertTrue(gate["ready"], gate["reasons"])
        self.assertTrue(item["review"]["actual_contract_signed"])

    def test_ua_d_2026_08_31_000001_deadline_trace_has_approved_template(self):
        tender = {"data": {"tenderID": "UA-TEST", "awards": [
            {"id": "winner", "qualified": True, "status": "active",
             "period": {"startDate": "2026-08-24T08:00:00+03:00"},
             "suppliers": [organization("22222222")]},
            {"id": "rejected", "qualified": False, "status": "unsuccessful",
             "date": "2026-08-31T15:22:00+03:00", "title": "Не підписано договір",
             "suppliers": [organization("22222222")]},
        ], "contracts": [], "items": []}}
        report = {"report_id": "UA-D-2026-08-31-000001", "tender_id": "tender-id",
                  "defendant_code": "22222222", "reason": "contractBreach",
                  "defendant_statements": []}
        with patch.object(server, "api_get", return_value=tender):
            context = server.build_procurement_context(report)
        self.assertEqual(context["day_5"], "2026-08-29")
        self.assertEqual(context["day_5_weekday_uk"], "субота")
        self.assertTrue(context["day_5_shifted"])
        self.assertEqual(context["contract_deadline"], "2026-08-31")
        self.assertTrue(context["rejected_before_deadline"])
        review = {"internal_decision": "decline"}
        self.assertTrue(server.build_violation_decision_justification(report, context, review))

    def test_three_and_ten_day_boundaries(self):
        start = server._parse_prozorro_date("2026-08-14T10:15:00+03:00")
        three = server._calendar_deadline(start, 3)
        ten = server._calendar_deadline(start, 10)
        self.assertEqual(three["deadline"], "2026-08-17")
        self.assertEqual(ten["deadline"], "2026-08-24")
        self.assertTrue(server._within_calendar_deadline(
            server._parse_prozorro_date("2026-08-24T23:00:00+03:00"), ten["deadline"]))

    def test_rules_without_rejection_has_no_automatic_decision(self):
        result = server.violation_rules_engine("contractBreach", {"rejection_present": False}, None)
        self.assertIsNone(result["recommended_decision"])
        self.assertEqual(result["recommended_scenario"], "review_without_rejection")

    def test_contract_breach_recommendation_tracks_deadline_and_explanations(self):
        base = {"rejection_present": True, "rejected_before_deadline": False}
        running = server.violation_rules_engine(
            "contractBreach", {**base, "supplier_deadline_ready": False,
                                "defendant_statements_present": False}, None)
        ended = server.violation_rules_engine(
            "contractBreach", {**base, "supplier_deadline_ready": True,
                                "defendant_statements_present": False}, None)
        explained = server.violation_rules_engine(
            "contractBreach", {**base, "supplier_deadline_ready": True,
                                "defendant_statements_present": True}, None)
        self.assertEqual(running["recommendation_reason"],
                         "Строк для укладення договору закінчився до відхилення пропозиції; потрібно дочекатися пояснень для прийняття рішення.")
        self.assertEqual(ended["recommendation_reason"],
                         "Строк для укладення договору закінчився до відхилення пропозиції; пояснень від постачальника не надано.")
        self.assertEqual(explained["recommendation_reason"],
                         "Строк для укладення договору закінчився до відхилення пропозиції; пояснення від постачальника надано, для прийняття рішення потрібно проаналізувати надані пояснення/документи.")

    def test_written_refusal_and_court_rules(self):
        self.assertEqual(server.violation_rules_engine(
            "signingRefusal", {"written_refusal_within_deadline": True}, {})["recommended_decision"], "decline")
        self.assertEqual(server.violation_rules_engine(
            "signingRefusal", {"written_refusal_within_deadline": False}, {})["recommended_decision"], "warning")
        self.assertEqual(server.violation_rules_engine(
            "goodsNonCompliance", {}, {"court_decision_final_present": False})["recommended_decision"], "decline")
        self.assertEqual(server.violation_rules_engine(
            "goodsNonCompliance", {}, {"court_decision_final_present": True})["recommended_decision"], "individual_review")

    def test_supplier_awards_do_not_mix(self):
        tender = {
            "tenderID": "UA-TEST", "criteria": [], "contracts": [{"id": "c1", "awardID": "w1", "status": "cancelled", "date": "2026-07-20"}],
            "awards": [
                {"id": "w1", "status": "cancelled", "qualified": True, "period": {"startDate": "2026-07-10T10:00:00+03:00"}, "suppliers": [organization("22222222")]},
                {"id": "r1", "status": "unsuccessful", "qualified": False, "date": "2026-07-16T10:00:00+03:00", "suppliers": [organization("22222222")]},
                {"id": "other", "status": "unsuccessful", "qualified": False, "date": "2026-07-17T10:00:00+03:00", "suppliers": [organization("33333333")]},
            ],
        }
        with patch.object(server, "api_get", return_value={"data": tender}):
            context = server.build_procurement_context({"tender_id": "tender-id", "defendant_code": "22222222"})
        self.assertEqual(context["winner_award_id"], "w1")
        self.assertEqual(context["rejection_award_id"], "r1")
        self.assertEqual(context["contract_status"], "cancelled")
        self.assertNotIn("actual_contract_date", context)

    def test_cancelled_contract_never_populates_manual_contract_fields(self):
        tender = {
            "tenderID": "UA-TEST", "criteria": [],
            "contracts": [{"id": "c1", "contractID": "UA-AUTO-a1", "awardID": "w1",
                           "status": "cancelled", "date": "2026-07-20"}],
            "awards": [{"id": "w1", "status": "cancelled", "qualified": True,
                        "suppliers": [organization("22222222")]}],
        }
        with patch.object(server, "api_get", return_value={"data": tender}):
            context = server.build_procurement_context({"tender_id": "tender-id", "defendant_code": "22222222"})
        self.assertEqual(context["contract_status"], "cancelled")
        for key in ("actual_contract_signed", "actual_contract_date", "actual_contract_number", "actual_contract_url"):
            self.assertNotIn(key, context)

    def test_manual_and_hourly_violation_sync_share_guard(self):
        server.VIOLATION_SYNC_STATE["running"] = True
        try:
            self.assertFalse(server.start_violation_reports_sync())
        finally:
            server.VIOLATION_SYNC_STATE["running"] = False

    def test_rejection_reason_classifier_is_conservative(self):
        self.assertEqual(server.classify_award_rejection_reason(
            {"title": "Відмова від підписання договору"}), "non_signing")
        self.assertEqual(server.classify_award_rejection_reason(
            {"description": "Не надано забезпечення виконання договору"}), "guarantee_missing")
        self.assertEqual(server.classify_award_rejection_reason(
            {"description": "Документи не відповідають вимогам"}), "other")
        self.assertEqual(server.classify_award_rejection_reason({}), "unknown")

    def test_contract_block_hidden_only_for_explicit_reason_without_related_contract(self):
        tender = {"tenderID": "UA-TEST", "criteria": [], "contracts": [], "awards": [
            {"id": "w1", "status": "cancelled", "qualified": True,
             "period": {"startDate": "2026-07-10T10:00:00+03:00"},
             "suppliers": [organization("22222222")]},
            {"id": "r1", "status": "unsuccessful", "qualified": False,
             "date": "2026-07-16T10:00:00+03:00", "title": "Не підписано договір",
             "suppliers": [organization("22222222")]},
        ]}
        with patch.object(server, "api_get", return_value={"data": tender}):
            context = server.build_procurement_context(
                {"tender_id": "tender-id", "defendant_code": "22222222", "reason": "contractBreach"})
        self.assertFalse(context["contract_info_required"])
        self.assertEqual(context["rejection_reason_classification"], "non_signing")

    def test_non_signing_rejection_does_not_inherit_winner_award_contract(self):
        tender = {"tenderID": "UA-TEST", "criteria": [],
                  "contracts": [{"id": "c1", "awardID": "w1", "status": "active",
                                 "suppliers": [organization("22222222")]}],
                  "awards": [
                      {"id": "w1", "status": "active", "qualified": True,
                       "period": {"startDate": "2026-08-18T09:00:00+03:00"},
                       "suppliers": [organization("22222222")]},
                      {"id": "r1", "status": "unsuccessful", "qualified": False,
                       "date": "2026-08-25T10:13:00+03:00", "title": "Не підписано договір",
                       "suppliers": [organization("22222222")]},
                  ]}
        with patch.object(server, "api_get", return_value={"data": tender}):
            context = server.build_procurement_context(
                {"tender_id": "tender-id", "defendant_code": "22222222", "reason": "contractBreach"})
        self.assertFalse(context["related_contract_found"])
        self.assertEqual(context["contract_warning"], "")
        self.assertFalse(context["contract_info_required"])

    def test_manual_justification_is_saved_as_canonical_plain_text(self):
        manual = "\tРучний офіційний текст УО\r\n\r\n  Другий абзац"
        expected = "Ручний офіційний текст УО\nДругий абзац"
        with patch.object(server, "api_get", return_value={"data": report_payload()}):
            result = server.save_violation_review(
                "report-internal", {"decision_justification": manual, "review_notes": ""})
        self.assertEqual(result["review"]["decision_justification"], expected)
        with server.db() as connection:
            stored = connection.execute(
                "SELECT decision_justification FROM violation_report_reviews WHERE report_id=?",
                ("report-internal",),
            ).fetchone()[0]
        self.assertEqual(stored, expected)
        self.assertEqual(result["justification_draft"], "")

    def test_supplier_refusal_and_customer_decision_are_stored_separately(self):
        payload = report_payload(); payload["details"]["reason"] = "signingRefusal"
        server.save_violation_report(payload)
        values = {
            "written_refusal_date": "2026-08-21", "written_refusal_number": "38",
            "written_refusal_url": "https://example.test/refusal",
            "customer_protocol_decision_date": "2026-08-25",
            "customer_protocol_decision_number": "106",
            "customer_protocol_decision_url": "https://example.test/customer-decision",
        }
        with patch.object(server, "api_get", return_value={"data": payload}), \
                patch.object(server, "build_procurement_context", return_value={"available": False}):
            result = server.save_violation_review("report-internal", values)
        review = result["review"]
        self.assertEqual(review["written_refusal_number"], "38")
        self.assertEqual(review["customer_protocol_decision_number"], "106")
        self.assertNotEqual(review["written_refusal_url"], review["customer_protocol_decision_url"])

    def test_supplier_and_administrator_working_day_deadlines_are_separate(self):
        control = server.violation_deadline_control({
            "date_published": "2026-08-21T10:00:00+03:00",
            "defendant_period_end": "2026-08-27T18:00:00+03:00",
        }, server._parse_prozorro_date("2026-08-28T10:00:00+03:00"))
        self.assertEqual(control["supplier_official_deadline"], "2026-08-27T18:00:00+03:00")
        self.assertEqual(control["supplier_local_control_deadline"], "2026-08-26")
        self.assertEqual(control["admin_deadline"], "2026-09-04")
        self.assertTrue(control["supplier_ready"])
        self.assertFalse(control["admin_overdue"])

    def test_dk_uses_contract_items_then_tender_fallback_and_deduplicates(self):
        tender = {"items": [
            {"classification": {"id": "11110000-0", "description": "Тендер"}},
            {"classification": {"id": "22220000-0", "description": "Інший"}},
        ]}
        contract = {"items": [
            {"classification": {"id": "33330000-0", "description": "Договір"}},
            {"classification": {"id": "33330000-0", "description": "Договір"}},
            {"classification": {"id": "44440000-0", "description": "Другий"}},
        ]}
        self.assertEqual(server.procurement_dk_classifications(tender, contract), [
            {"code": "33330000-0", "description": "Договір"},
            {"code": "44440000-0", "description": "Другий"},
        ])
        self.assertEqual(server.procurement_dk_classifications(tender, None)[0]["code"], "11110000-0")

    def test_reviewed_status_is_blocked_before_official_supplier_deadline(self):
        payload = report_payload()
        payload["defendantPeriod"] = {"endDate": "2099-01-01T18:00:00+02:00"}
        server.save_violation_report(payload)
        with patch.object(server, "api_get", return_value={"data": payload}):
            with self.assertRaisesRegex(ValueError, "окремою дією"):
                server.save_violation_review("report-internal", {
                    "review_status": "reviewed", "internal_decision": "warning"})
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,internal_decision,updated_at,updated_by)
                VALUES (?,?,?,?,?)""", ("report-internal", "in_review", "warning", server.now_iso(), "УО"))
        detail = {"id": "report-internal", "decisions": [],
                  "authority_code": "40996564",
                  "deadline_control": {"supplier_ready": False},
                  "review": {"review_status": "in_review", "internal_decision": "warning"}}
        with patch.object(server, "violation_report_detail", return_value=detail):
            with self.assertRaisesRegex(ValueError, "офіційного строку"):
                server.complete_violation_review("report-internal", "УО")

    def test_official_decision_is_presented_as_completed_without_rewriting_review(self):
        payload = report_payload()
        payload["decisions"] = [{"id": "official-decision"}]
        server.save_violation_report(payload)
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,updated_at,updated_by) VALUES (?,?,?,?)""",
                ("report-internal", "in_review", server.now_iso(), "УО"))
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertTrue(detail["is_read_only"])
        self.assertEqual(detail["review"]["review_status"], "completed")
        with server.db() as connection:
            stored = connection.execute(
                "SELECT review_status FROM violation_report_reviews WHERE report_id='report-internal'").fetchone()[0]
        self.assertEqual(stored, "in_review")

    def test_legacy_local_completed_is_presented_as_reviewed(self):
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,updated_at,updated_by) VALUES (?,?,?,?)""",
                ("report-internal", "completed", server.now_iso(), "УО"))
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertTrue(detail["is_read_only"])
        self.assertEqual(detail["review"]["review_status"], "reviewed")

    def test_protocol_generation_does_not_complete_review(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,protocol_number,protocol_date,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning",
                "Остаточне ручне обґрунтування", "TEST-1", "2026-08-31", now, "Тест",
            ))
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "authority_code": "40996564",
            "date_published": "2026-08-18T10:00:00+03:00", "date_created": "2026-08-18T10:00:00+03:00",
            "tender_pretty_id": "UA-TEST", "author_name": "Замовник", "author_code": "11111111",
            "defendant_name": "Постачальник", "defendant_code": "22222222", "description": "Порушення",
            "evidence_documents": [], "defendant_statements": [], "supplier_verified": None,
            "deadline_control": {"supplier_ready": True},
            "procurement_context": {"available": True, "winner_selected_at": "2026-08-01T10:00:00+03:00"},
            "review": {"review_status": "in_review", "assigned_officer": "Тестова УО",
                       "customer_verified_short_name": "Замовник",
                       "internal_decision": "warning", "decision_justification": "Остаточне ручне обґрунтування",
                       "protocol_number": "TEST-1", "protocol_date": "2026-08-31"},
        }
        output_dir = Path(self.temp.name) / "protocols"
        def write_test_protocol(_kind, path, *_args):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"docx")
            return path
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "PROTOCOLS_DIR", output_dir), \
                patch.object(server, "build_violation_protocol_docx", side_effect=write_test_protocol):
            first = server.generate_violation_protocol(
                "report-internal", {"protocol_number": "TEST-1", "protocol_date": "2026-08-31"})
            result = server.generate_violation_protocol(
                "report-internal", {"protocol_number": "TEST-1", "protocol_date": "2026-08-31"})
        self.assertNotEqual(first["filename"], result["filename"])
        self.assertTrue((output_dir / result["filename"]).is_file())
        self.assertEqual(result["review_status"], "in_review")
        with server.db() as connection:
            review = connection.execute("""SELECT review_status,reviewed_at,updated_by,
                generated_protocol_filename,generated_protocol_metadata_json,protocol_generated_at
                FROM violation_report_reviews WHERE report_id='report-internal'""").fetchone()
            events = connection.execute("""SELECT COUNT(*) FROM violation_report_review_events
                WHERE report_id='report-internal' AND event_type='protocol_generated'""").fetchone()[0]
        self.assertEqual(review["review_status"], "in_review")
        self.assertFalse(review["reviewed_at"])
        self.assertEqual(review["generated_protocol_filename"], result["filename"])
        metadata = json.loads(review["generated_protocol_metadata_json"])
        self.assertEqual(metadata, result["metadata"])
        self.assertEqual(metadata["protocol_subject"]["label"], "Тема протоколу / короткий зміст")
        self.assertIn("UA-D-TEST", metadata["protocol_subject"]["value"])
        self.assertEqual(result["resolved_metadata"], [{
            "metadata_key": "protocol_subject",
            "label": "Тема протоколу / короткий зміст",
            "resolved_text": metadata["protocol_subject"]["value"],
            "version": metadata["protocol_subject"]["config_version"],
            "display_order": 0,
        }])
        self.assertEqual(result["pdf_download_url"], "/api/violation-reports/report-internal/protocol/pdf")
        self.assertTrue(review["protocol_generated_at"])
        self.assertEqual(review["updated_by"], server.CURRENT_USER)
        self.assertGreaterEqual(events, 1)

    def test_protocol_uses_manual_contract_requisites_not_prozorro_mapping(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,protocol_number,protocol_date,actual_contract_signed,
                 actual_contract_date,actual_contract_number,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning", "Погоджений текст",
                "TEST-MANUAL", "2026-09-07", 1, "2026-09-06", "MANUAL-42", now, "Тест"))
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "authority_code": "40996564", "date_published": "2026-08-18T10:00:00+03:00",
            "date_created": "2026-08-18T10:00:00+03:00", "tender_pretty_id": "UA-TEST",
            "author_name": "Замовник", "author_code": "11111111", "defendant_name": "Постачальник",
            "defendant_code": "22222222", "description": "Порушення", "evidence_documents": [],
            "defendant_statements": [], "supplier_verified": None,
            "deadline_control": {"supplier_ready": True},
            "procurement_context": {"available": True, "contract_date": "2020-01-01",
                                    "contract_pretty_id": "UA-AUTO-a1",
                                    "winner_selected_at": "2026-08-01T10:00:00+03:00"},
            "review": {"review_status": "in_review", "assigned_officer": "Тестова УО",
                       "customer_verified_short_name": "Замовник",
                       "internal_decision": "warning", "decision_justification": "Погоджений текст",
                       "protocol_number": "TEST-MANUAL", "protocol_date": "2026-09-07",
                       "actual_contract_signed": 1, "actual_contract_date": "2026-09-06",
                       "actual_contract_number": "MANUAL-42"},
        }
        captured = {}
        def write_test_protocol(_kind, path, values, _justification, _customer, _supplier, flags, *_args):
            captured.update(values=values, flags=flags);path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b"docx")
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "PROTOCOLS_DIR", Path(self.temp.name) / "protocols"), \
                patch.object(server, "build_violation_protocol_docx", side_effect=write_test_protocol):
            server.generate_violation_protocol("report-internal", {
                "protocol_number": "TEST-MANUAL", "protocol_date": "2026-09-07"})
        self.assertEqual(captured["values"]["contract_number"], "MANUAL-42")
        self.assertEqual(captured["values"]["contract_date"], "06.09.2026")
        self.assertNotIn("UA-AUTO-a1", captured["values"].values())
        self.assertTrue(captured["flags"]["has_contract"])

    def test_protocol_normalizes_customer_supplier_quotes_before_all_declensions(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,protocol_number,protocol_date,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning", "Погоджений текст",
                "TEST-QUOTES", "2026-09-08", now, "Тест"))
        customer = 'ДЕРЖАВНЕ ПІДПРИЄМСТВО "ЗАМОВНИК"'
        supplier = 'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ОХТИРКА М\'ЯСОПРОДУКТ"'
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "authority_code": "40996564", "date_created": "2026-09-01", "tender_pretty_id": "UA-TEST",
            "author_name": customer, "author_code": "11111111", "defendant_name": supplier,
            "defendant_code": "22222222", "description": "Порушення", "evidence_documents": [],
            "defendant_statements": [], "supplier_verified": {"full_name": supplier, "short_name": 'ТОВ "ОХТИРКА М\'ЯСОПРОДУКТ"'},
            "deadline_control": {"supplier_ready": True},
            "procurement_context": {"available": True, "winner_selected_at": "2026-09-01"},
            "review": {"assigned_officer": "Тестова УО", "internal_decision": "warning",
                       "customer_verified_short_name": "ДП «ЗАМОВНИК»",
                       "decision_justification": "Погоджений текст", "protocol_number": "TEST-QUOTES",
                       "protocol_date": "2026-09-08"},
        }
        captured = {}
        declined_inputs = []
        def decline_presentation_name(original, entity_type, grammatical_case):
            declined_inputs.append(original)
            # Simulate an override/automatic rule that still contains source
            # ASCII quotes: document presentation must normalize its result too.
            ascii_result = original.replace("«", '"').replace("»", '"')
            return DeclensionResult(ascii_result, "resolved", "automatic", original, entity_type)
        def capture(_kind, path, values, *_args):
            captured.update(values)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"docx")
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "PROTOCOLS_DIR", Path(self.temp.name) / "protocols"), \
                patch.object(server, "decline_name", side_effect=decline_presentation_name), \
                patch.object(server, "build_violation_protocol_docx", side_effect=capture):
            server.generate_violation_protocol("report-internal", {
                "protocol_number": "TEST-QUOTES", "protocol_date": "2026-09-08"})
        name_tokens = ("customer_name", "customer_name_genitive", "customer_name_accusative",
                       "supplier_name", "supplier_short_name", "supplier_name_genitive",
                       "supplier_name_dative", "supplier_name_accusative")
        for token in name_tokens:
            self.assertNotIn('"', captured[token], token)
        self.assertIn("«ЗАМОВНИК»", captured["customer_name"])
        for token in name_tokens[3:]:
            self.assertIn("«ОХТИРКА М'ЯСОПРОДУКТ»", captured[token], token)
        self.assertTrue(declined_inputs)
        self.assertTrue(all('"' not in value for value in declined_inputs))

    def test_protocol_civil_code_flag_uses_only_the_current_reason_deadline(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,protocol_number,protocol_date,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning", "Погоджений текст",
                "TEST-CIVIL", "2026-09-08", now, "Тест"))
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "authority_code": "40996564", "date_created": "2026-09-01", "tender_pretty_id": "UA-TEST",
            "author_name": "Замовник", "author_code": "11111111", "defendant_name": "Постачальник",
            "defendant_code": "22222222", "description": "Порушення", "evidence_documents": [],
            "defendant_statements": [], "supplier_verified": None,
            "deadline_control": {"supplier_ready": True},
            "procurement_context": {"available": True, "winner_selected_at": "2026-09-01",
                                    "day_5_shifted": False, "day_3_shifted": True},
            "review": {"assigned_officer": "Тестова УО", "internal_decision": "warning",
                       "customer_verified_short_name": "Замовник",
                       "decision_justification": "Погоджений текст", "protocol_number": "TEST-CIVIL",
                       "protocol_date": "2026-09-08"},
        }
        captured = {}
        def capture(_kind, path, _values, _justification, _customer, _supplier, flags, *_args):
            captured.update(flags)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"docx")
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "PROTOCOLS_DIR", Path(self.temp.name) / "protocols"), \
                patch.object(server, "decline_name", side_effect=lambda value, entity, case:
                             DeclensionResult(value, "resolved", "automatic", value, entity)), \
                patch.object(server, "build_violation_protocol_docx", side_effect=capture):
            server.generate_violation_protocol("report-internal", {
                "protocol_number": "TEST-CIVIL", "protocol_date": "2026-09-08"})
        self.assertFalse(captured["has_civil_code_basis"])

    def test_contract_breach_scenario_summary_is_derived_and_keeps_manual_comment_separate(self):
        report = {
            "reason": "contractBreach",
            "defendant_statements": [],
            "review": {"review_notes": "Ручний коментар УО"},
        }
        context = {
            "available": True, "rejection_present": True,
            "rejected_before_deadline": True,
            "performance_security_required": True,
            "day_5_shifted": True,
        }
        summary = server.violation_scenario_summary(report, context)
        self.assertEqual(summary, (
            "Сценарій: дострокове відхилення; забезпечення виконання договору — вимагається; "
            "пояснення постачальника — відсутні; ЦКУ — застосовується "
            "(перенесення граничного строку)."))
        self.assertNotIn(report["review"]["review_notes"], summary)
        self.assertEqual(report["review"]["review_notes"], "Ручний коментар УО")

    def test_contract_breach_scenario_summary_updates_from_structured_context(self):
        report = {"reason": "contractBreach", "defendant_statements": [
            {"description": "Фактичне пояснення постачальника"}]}
        context = {
            "available": True, "rejection_present": True,
            "rejected_before_deadline": False,
            "contract_guarantee_required": False,
            "day_5_shifted": False,
        }
        self.assertEqual(server.violation_scenario_summary(report, context), (
            "Сценарій: відхилення після закінчення строку, визначеного п. 66 Порядку № 822; "
            "забезпечення виконання договору — не вимагається; пояснення постачальника — надані; "
            "ЦКУ — не застосовується."))
        self.assertEqual(server.violation_scenario_summary(
            {"reason": "goodsNonCompliance"}, context), (
                "Сценарій: пп. 3 п. 49; рішення суду, що набрало законної сили — не визначено; "
                "пояснення постачальника — відсутні."))

    def test_scenario_summary_covers_p2_before_and_after_deadline(self):
        report = {"reason": "signingRefusal", "defendant_statements": [], "review": {
            "written_refusal_date": "2026-09-08"}}
        before = {"available": True, "written_refusal_deadline_expired": False,
                  "written_refusal_within_deadline": True, "day_3_shifted": True}
        self.assertEqual(server.violation_scenario_summary(report, before), (
            "Сценарій: пп. 2 п. 49; триденний строк — не сплив; письмова відмова "
            "постачальника — надана; пояснення постачальника — відсутні; ЦКУ — "
            "застосовується (перенесення граничного строку)."))
        report["review"] = {}
        after = {"available": True, "written_refusal_deadline_expired": True,
                 "day_3_shifted": False}
        self.assertIn("триденний строк — не визначено; письмова відмова постачальника — відсутня",
                      server.violation_scenario_summary(report, after))

        report["review"] = {"written_refusal_url": "https://example.test/refusal"}
        self.assertIn("триденний строк — не визначено; письмова відмова постачальника — надана",
                      server.violation_scenario_summary(report, after))

    def test_ua_d_2026_09_08_000001_uses_canonical_refusal_deadline_flag(self):
        report = {
            "report_id": "UA-D-2026-09-08-000001",
            "reason": "signingRefusal",
            "defendant_statements": [],
            "review": {"written_refusal_date": "2026-09-07"},
        }
        context = {
            "available": True,
            "written_refusal_within_deadline": True,
            # The wall clock is now past the deadline, but the refusal itself
            # was submitted while that deadline had not expired.
            "written_refusal_deadline_expired": True,
            "day_3_shifted": True,
        }
        recommendation = server.violation_rules_engine(
            report["reason"], context, report["review"])
        self.assertEqual(recommendation["recommended_decision"], "decline")
        self.assertEqual(recommendation["recommendation_reason"],
                         "Письмову відмову надано в межах строку.")
        self.assertEqual(server.violation_scenario_summary(report, context), (
            "Сценарій: пп. 2 п. 49; триденний строк — не сплив; письмова відмова "
            "постачальника — надана; пояснення постачальника — відсутні; ЦКУ — "
            "застосовується (перенесення граничного строку)."))

    def test_scenario_summary_covers_p3_without_unrelated_contract_facts(self):
        report = {"reason": "goodsNonCompliance", "defendant_statements": [
            {"description": "Пояснення"}], "review": {"court_decision_final_present": False}}
        summary = server.violation_scenario_summary(report, {})
        self.assertEqual(summary, (
            "Сценарій: пп. 3 п. 49; рішення суду, що набрало законної сили — відсутнє; "
            "пояснення постачальника — надані."))
        self.assertNotIn("догов", summary.lower())
        self.assertNotIn("штраф", summary.lower())

    def test_scenario_summary_p1_exists_before_deadline_without_rejection(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        summary = server.violation_scenario_summary(report, {
            "available": True, "rejection_present": False, "contract_deadline_expired": False,
            "performance_security_required": False, "day_5_shifted": False})
        self.assertIn("строк, визначений п. 66 Порядку № 822, ще не сплив", summary)
        self.assertTrue(summary.startswith("Сценарій:"))

    def test_protocol_passes_last_saved_justification_verbatim(self):
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "authority_code": "40996564", "date_created": "2026-09-01", "tender_pretty_id": "UA-TEST",
            "author_name": "Замовник", "author_code": "11111111", "defendant_name": "Постачальник",
            "defendant_code": "22222222", "description": "Порушення", "evidence_documents": [],
            "defendant_statements": [], "supplier_verified": None,
            "deadline_control": {"supplier_ready": True, "supplier_deadline": "2026-09-05"},
            "procurement_context": {"available": True, "winner_selected_at": "2026-09-01", "dk_code": "44110000-4"},
            "review": {"assigned_officer": "Тестова УО", "internal_decision": "warning",
                       "customer_verified_short_name": "Замовник",
                       "decision_justification": "Останній збережений текст УО — без змін.",
                       "protocol_number": "P-1", "protocol_date": "2026-09-08"},
        }
        captured = {}
        def capture(_kind, path, _values, justification, *_args):
            captured["justification"] = justification
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"docx")
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "PROTOCOLS_DIR", Path(self.temp.name) / "protocols"), \
                patch.object(server, "build_violation_protocol_docx", side_effect=capture):
            server.generate_violation_protocol("report-internal", {"protocol_number": "P-1", "protocol_date": "2026-09-08"})
        self.assertEqual(captured["justification"], "Останній збережений текст УО — без змін.")

    def test_protocol_reason_bindings_use_full_reason_metadata_not_customer_description(self):
        descriptions = {
            "contractBreach": "Опис Замовника для пп. 1",
            "signingRefusal": "Опис Замовника для пп. 2",
            "goodsNonCompliance": "Опис Замовника для пп. 3",
        }
        for reason, description in descriptions.items():
            metadata = server.VIOLATION_REASON_PROTOCOL_METADATA[reason]
            self.assertIn(f"Підпункт {metadata['number']} пункту 49", metadata["label"])
            self.assertIn("Постанови Кабінету Міністрів України від 14.09.2020 № 822", metadata["label"])
            self.assertTrue(metadata["text"])
            self.assertNotEqual(metadata["text"], description)
        self.assertNotIn("Непідписання договору / ненадання забезпечення в строк",
                         {item["label"] for item in server.VIOLATION_REASON_PROTOCOL_METADATA.values()})

    def test_protocol_officer_name_uses_first_name_then_uppercase_surname(self):
        self.assertEqual(server._protocol_officer_name("СВІТЛАНА НАМЯСЕНКО"),
                         "Світлана НАМЯСЕНКО")
        self.assertEqual(server._protocol_officer_name("Яна КАСЬЯН"), "Яна КАСЬЯН")

    def test_manual_completion_is_separate_and_preserves_review_history(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,generated_protocol_filename,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning",
                "Ручне обґрунтування", "already-generated.docx", now, "Тест",
            ))
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "decisions": [],
            "authority_code": "40996564",
            "deadline_control": {"supplier_ready": True},
            "review": {"review_status": "in_review", "internal_decision": "warning",
                       "decision_justification": "Ручне обґрунтування",
                       "generated_protocol_filename": "already-generated.docx"},
        }
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "build_procurement_context", return_value={
                    "available": True, "dk_code": "15510000-6", "winner_selected_at": "2026-08-20",
                    "rejection_date": "2026-08-26", "contract_guarantee_required": True}):
            result = server.complete_violation_review("report-internal", "Тестова УО")
        self.assertEqual(result["review_status"], "reviewed")
        with server.db() as connection:
            review = connection.execute("""SELECT review_status,completed_at,completed_by,
                decision_justification,generated_protocol_filename
                FROM violation_report_reviews WHERE report_id='report-internal'""").fetchone()
            events = connection.execute("""SELECT COUNT(*) FROM violation_report_review_events
                WHERE report_id='report-internal' AND event_type='review_completed'""").fetchone()[0]
        self.assertEqual(review["review_status"], "reviewed")
        self.assertTrue(review["completed_at"])
        self.assertEqual(review["completed_by"], "Тестова УО")
        self.assertEqual(review["decision_justification"], "Ручне обґрунтування")
        self.assertEqual(review["generated_protocol_filename"], "already-generated.docx")
        self.assertEqual(events, 1)

    def test_completion_atomically_saves_form_and_context_snapshot(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,assigned_officer,internal_decision,
                 decision_justification,review_notes,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "Тестова УО", "warning",
                "Попередній текст", "Попередня примітка", now, "Тест",
            ))
        detail = {
            "id": "report-internal", "report_id": "UA-D-TEST", "reason": "contractBreach",
            "status": "pending", "decisions": [], "has_official_decision": False,
            "authority_code": "40996564", "defendant_statements": [],
            "evidence_documents": [], "description": "Порушення",
            "deadline_control": {"supplier_ready": True},
            "review": {"review_status": "in_review", "internal_decision": "warning"},
        }
        context = {"available": True, "dk_code": "15510000-6", "winner_selected_at": "2026-08-20",
                   "rejection_present": True, "rejection_date": "2026-08-26",
                   "contract_deadline": "2026-08-25", "rejected_before_deadline": False,
                   "contract_guarantee_required": True}
        payload = {"review_status": "in_review", "internal_decision": "warning",
                   "decision_justification": "Остаточний текст", "review_notes": "Остання примітка"}
        with patch.object(server, "violation_report_detail", return_value=detail), \
                patch.object(server, "build_procurement_context", return_value=context):
            result = server.complete_violation_review("report-internal", "Тестова УО", payload)
        self.assertEqual(result["review_status"], "reviewed")
        with server.db() as connection:
            review = connection.execute("""SELECT review_status,completed_at,decision_justification,
                review_notes FROM violation_report_reviews WHERE report_id='report-internal'""").fetchone()
            snapshot = connection.execute("""SELECT new_value FROM violation_report_review_events
                WHERE report_id='report-internal' AND event_type='decision_context_snapshotted'""").fetchone()
        self.assertEqual(review["review_status"], "reviewed")
        self.assertTrue(review["completed_at"])
        self.assertEqual(review["decision_justification"], "Остаточний текст")
        self.assertEqual(review["review_notes"], "Остання примітка")
        saved = json.loads(snapshot["new_value"])
        self.assertEqual(saved["procurement_context"]["dk_code"], "15510000-6")
        self.assertEqual(saved["recommendation"]["recommended_decision"], "warning")

    def test_failed_atomic_save_does_not_complete_or_snapshot(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,internal_decision,decision_justification,updated_at,updated_by)
                VALUES (?,?,?,?,?,?)""", (
                "report-internal", "in_review", "warning", "Збережено", now, "Тест"))
        detail = {"id": "report-internal", "reason": "contractBreach", "decisions": [],
                  "has_official_decision": False, "authority_code": "40996564",
                  "deadline_control": {"supplier_ready": True}, "review": {}}
        with patch.object(server, "violation_report_detail", return_value=detail):
            with self.assertRaisesRegex(ValueError, "Невідоме внутрішнє рішення"):
                server.complete_violation_review("report-internal", "УО", {
                    "internal_decision": "invalid", "decision_justification": "Не зберігати"})
        with server.db() as connection:
            review = connection.execute("""SELECT completed_at,decision_justification FROM
                violation_report_reviews WHERE report_id='report-internal'""").fetchone()
            snapshots = connection.execute("""SELECT COUNT(*) FROM violation_report_review_events
                WHERE event_type='decision_context_snapshotted'""").fetchone()[0]
        self.assertFalse(review["completed_at"])
        self.assertEqual(review["decision_justification"], "Збережено")
        self.assertEqual(snapshots, 0)

    def test_stale_patch_cannot_change_completed_review(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,internal_decision,completed_at,completed_by,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "reviewed", "warning", now, "УО", now, "УО"))
        payload = report_payload()
        with patch.object(server, "api_get", return_value={"data": payload}):
            with self.assertRaisesRegex(PermissionError, "завершено"):
                server.save_violation_review("report-internal", {"review_status": "in_review"})
        with server.db() as connection:
            status = connection.execute("SELECT review_status FROM violation_report_reviews WHERE report_id='report-internal'").fetchone()[0]
        self.assertEqual(status, "reviewed")

    def test_local_completion_uses_snapshot_and_sync_does_not_overwrite_it(self):
        now = server.now_iso()
        snapshot = {"version": 1, "procurement_context": {"dk_code": "OLD-CPV"},
                    "recommendation": {"recommended_decision": "warning", "recommendation_reason": "Збережено"}}
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,internal_decision,completed_at,completed_by,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "reviewed", "warning", now, "УО", now, "УО"))
            connection.execute("""INSERT INTO violation_report_review_events
                (report_id,event_type,field_name,new_value,changed_at,changed_by)
                VALUES (?,?,?,?,?,?)""", (
                "report-internal", "decision_context_snapshotted", "decision_context_snapshot",
                json.dumps(snapshot, ensure_ascii=False), now, "УО"))
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(detail["read_only_reason"], "local_completion")
        self.assertEqual(detail["procurement_context"]["dk_code"], "OLD-CPV")
        self.assertEqual(detail["recommendation"]["recommendation_reason"], "Збережено")
        refreshed = report_payload()
        refreshed["dateModified"] = "2026-09-01T18:00:00+03:00"
        server.save_violation_report(refreshed)
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            after = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(after["procurement_context"]["dk_code"], "OLD-CPV")
        refreshed["decisions"] = [{"id":"official","status":"satisfied","date":"2026-09-02"}]
        server.save_violation_report(refreshed)
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            official = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(official["read_only_reason"], "official_decision")
        self.assertEqual(official["procurement_context"]["dk_code"], "OLD-CPV")
        self.assertEqual(official["recommendation"]["recommendation_reason"], "Збережено")

    def test_single_report_sheets_json_is_sparse_kyiv_dated_and_snapshot_only(self):
        snapshot = {"version": 1, "procurement_context": {
            "available": True,
            "dk_code": "15610000-7 — Продукція борошномельно-круп’яної промисловості",
            "winner_selected_at": "2026-08-23T22:30:00Z",
            "rejection_date": "2026-08-31T15:16:00+03:00",
            "rejection_title": "Підстава з finalized context",
        }, "recommendation": {}}
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""UPDATE violation_reports SET report_id=?,tender_pretty_id=?,
              author_name=?,author_code=?,defendant_name=?,defendant_code=?,description=?,reason=?
              WHERE id='report-internal'""", (
                "UA-D-2026-08-31-000001", "UA-2026-08-19-008079-a",
                "Замовник із Prozorro", "00112233", "Постачальник із Prozorro", "22222222",
                "Фактичний опис без перефразування", "contractBreach"))
            connection.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,full_name,short_name,synced_at) VALUES (?,?,?,?)""", (
                "22222222", "КАНОНІЧНА ПОВНА НАЗВА", "ТОВ «КОРОТКО»", now))
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,assigned_officer,internal_decision,protocol_number,
               protocol_date,customer_verified_full_name,customer_verified_short_name,
               updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                "report-internal", "reviewed", "СВІТЛАНА НАМЯСЕНКО", "decline", "679-1",
                "2026-09-08", "КАНОНІЧНИЙ ЗАМОВНИК", "ЗАМОВНИК КОРОТКО", now, "УО"))
            connection.execute("""INSERT INTO violation_report_review_events
              (report_id,event_type,field_name,new_value,changed_at,changed_by)
              VALUES (?,?,?,?,?,?)""", (
                "report-internal", "decision_context_snapshotted", "decision_context_snapshot",
                json.dumps(snapshot, ensure_ascii=False), now, "УО"))
        with patch.object(server, "build_procurement_context") as live_lookup:
            payload = server.violation_report_sheets_json("UA-D-2026-08-31-000001")
        live_lookup.assert_not_called()
        self.assertEqual(payload["received_at"], "18.08.2026")
        self.assertEqual(payload["winner_selected_at"], "24.08.2026")
        self.assertEqual(payload["rejection_at"], "31.08.2026")
        self.assertEqual(payload["supplier_name"], "КАНОНІЧНА ПОВНА НАЗВА")
        self.assertEqual(payload["uo_decision"], "Відмова в задоволенні звернення")
        self.assertEqual(payload["output_name"], "UA-D-2026-08-31-000001_679-1_В")
        self.assertEqual(payload["legal_basis_short"], "пп. 1 п. 49")
        self.assertNotIn("contract_date", payload)
        self.assertNotIn("contract_number", payload)
        self.assertEqual(len(payload), 21)

    def test_sheets_json_eligibility_starts_at_reviewed_not_completed_at(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,internal_decision,completed_at,updated_at,updated_by)
              VALUES (?,?,?,?,?,?)""", (
                "report-internal", "reviewed", "warning", "", now, "УО"))
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            detail = server.violation_report_detail("report-internal", refresh=False)
            payload = server.violation_report_sheets_json("report-internal")
        self.assertTrue(detail["sheets_json_available"])
        self.assertNotIn("protocol_number", payload)
        self.assertNotIn("protocol_date", payload)
        self.assertNotIn("output_name", payload)
        with server.db() as connection:
            connection.execute("UPDATE violation_report_reviews SET review_status='completed' "
                               "WHERE report_id='report-internal'")
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            completed = server.violation_report_detail("report-internal", refresh=False)
        self.assertTrue(completed["sheets_json_available"])

    def test_sheets_json_accepts_official_completed_projection_with_saved_decision(self):
        official = report_payload([{"id": "decision", "status": "declined", "date": "2026-09-08"}])
        server.save_violation_report(official)
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,internal_decision,protocol_number,protocol_date,
               updated_at,updated_by) VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "decline", "P-1", "2026-09-08", now, "УО"))
        detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(detail["review"]["review_status"], "completed")
        self.assertFalse(detail["local_review_completed"])
        self.assertTrue(detail["sheets_json_available"])
        with patch.object(server, "build_procurement_context", return_value={"available": False}):
            payload = server.violation_report_sheets_json("report-internal")
        self.assertEqual(payload["report_id"], "UA-D-TEST")
        self.assertEqual(payload["uo_decision"], "Відмова в задоволенні звернення")

    def test_sheets_json_rejects_in_review_without_completed_projection(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,internal_decision,protocol_number,protocol_date,
               updated_at,updated_by) VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "decline", "P-1", "2026-09-08", now, "УО"))
        detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertEqual(detail["review"]["review_status"], "in_review")
        self.assertFalse(detail["sheets_json_available"])
        with self.assertRaisesRegex(PermissionError, "Розглянуто"):
            server.violation_report_sheets_json("report-internal")

    def test_sheets_json_legacy_procurement_fallback_is_one_case_only(self):
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,internal_decision,protocol_number,protocol_date,
               updated_at,updated_by) VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "reviewed", "decline", "P-2", "2026-09-08", now, "УО"))
        legacy = {"available": True, "dk_code": "99999999-9", "winner_selected_at": "2026-08-20"}
        with patch.object(server, "build_procurement_context", return_value=legacy) as lookup:
            payload = server.violation_report_sheets_json("report-internal")
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(lookup.call_args.args[0]["id"], "report-internal")
        self.assertEqual(payload["cpv"], "99999999-9")

    def test_read_only_card_and_sheets_json_share_case_scoped_resolved_context(self):
        official = report_payload([{"id": "decision", "status": "declined", "date": "2026-09-01"}])
        server.save_violation_report(official)
        now = server.now_iso()
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
              (report_id,review_status,internal_decision,protocol_number,protocol_date,
               updated_at,updated_by) VALUES (?,?,?,?,?,?,?)""", (
                "report-internal", "in_review", "warning", "679-4", "2026-09-08", now, "УО"))
        resolved = {
            "available": True,
            "dk_code": "44110000-4 — Конструкційні матеріали",
            "winner_selected_at": "2026-08-21T10:00:00+03:00",
            "rejection_date": "2026-09-01T12:00:00+03:00",
            "rejection_title": "Канонічна підстава відхилення",
        }
        with patch.object(server, "build_procurement_context", return_value=resolved) as card_lookup:
            detail = server.violation_report_detail("report-internal", refresh=False)
        card_lookup.assert_called_once()
        self.assertTrue(detail["is_read_only"])
        self.assertEqual(detail["decision_context_source"], "case_scoped_resolver")
        self.assertEqual(detail["procurement_context"]["cpv"], resolved["dk_code"])
        self.assertEqual(detail["procurement_context"]["rejection_at"], resolved["rejection_date"])
        self.assertEqual(detail["procurement_context"]["rejection_reason"], resolved["rejection_title"])
        with patch.object(server, "build_procurement_context", return_value=resolved) as export_lookup:
            payload = server.violation_report_sheets_json("report-internal")
        export_lookup.assert_called_once()
        self.assertEqual(payload["cpv"], detail["procurement_context"]["cpv"])
        self.assertEqual(payload["winner_selected_at"], "21.08.2026")
        self.assertEqual(payload["rejection_at"], "01.09.2026")
        self.assertEqual(payload["rejection_reason"], detail["procurement_context"]["rejection_reason"])

    def test_unreviewed_read_only_card_resolves_factual_cpv_without_json_eligibility(self):
        official = report_payload([{"id": "decision", "status": "declined", "date": "2026-07-06"}])
        server.save_violation_report(official)
        resolved = {
            "available": True,
            "dk_code": "44110000-4 — Конструкційні матеріали",
            "contract_pretty_id": "UA-2026-06-22-011297-a-a2",
        }
        with patch.object(server, "build_procurement_context", return_value=resolved) as lookup:
            detail = server.violation_report_detail("report-internal", refresh=False)
        lookup.assert_called_once()
        self.assertTrue(detail["is_read_only"])
        self.assertFalse(detail["sheets_json_available"])
        self.assertIsNone(detail["procurement_context"])
        self.assertEqual(detail["factual_procurement_context_source"], "case_scoped_resolver")
        self.assertEqual(detail["factual_procurement_context"]["cpv"], resolved["dk_code"])
        self.assertEqual(detail["review"].get("internal_decision") or "", "")

    def test_justification_generation_is_blocked_before_supplier_deadline(self):
        payload = report_payload()
        payload["defendantPeriod"] = {"endDate": "2099-01-01T18:00:00+02:00"}
        payload["defendantStatements"] = []
        server.save_violation_report(payload)
        context = {
            "available": True, "rejection_present": True,
            "contract_guarantee_required": True, "rejected_before_deadline": False,
            "winner_selected_at": "2026-08-01T10:00:00+03:00",
            "contract_deadline": "2026-08-06", "rejection_date": "2026-08-07T12:00:00+03:00",
        }
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,internal_decision,decision_justification,decision_template_key,
                 justification_source_hash,justification_generated_at,justification_manually_edited,
                 updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?)""",
                ("report-internal", "warning", "Стара автоматична чернетка", "individual_review",
                 "old-hash", "2026-08-26T12:00:00+00:00", 0, server.now_iso(), "УО"))
        with patch.object(server, "build_procurement_context", return_value=context):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertFalse(detail["deadline_control"]["supplier_ready"])
        self.assertEqual(detail["justification_draft"], "")
        self.assertEqual(detail["justification_template_key"], "")
        self.assertFalse(detail["justification_stale"])
        self.assertTrue(detail["hide_saved_automatic_justification"])
        self.assertTrue(any("строк постачальника" in reason
                            for reason in detail["protocol_readiness"]["reasons"]))
        with patch.object(server, "api_get", return_value={"data": payload}), \
                patch.object(server, "build_procurement_context", return_value=context):
            with self.assertRaisesRegex(ValueError, "буде доступне після завершення строку"):
                server.save_violation_review("report-internal", {
                    "action": "regenerate_justification", "internal_decision": "warning",
                    "guarantee_documents_visible": False})

    def test_manual_justification_remains_visible_before_supplier_deadline(self):
        payload = report_payload()
        payload["defendantPeriod"] = {"endDate": "2099-01-01T18:00:00+02:00"}
        server.save_violation_report(payload)
        with server.db() as connection:
            connection.execute("""INSERT INTO violation_report_reviews
                (report_id,decision_justification,justification_manually_edited,updated_at,updated_by)
                VALUES (?,?,?,?,?)""", ("report-internal", "Ручний текст УО", 1, server.now_iso(), "УО"))
        with patch.object(server, "build_procurement_context", return_value={"available": True}):
            detail = server.violation_report_detail("report-internal", refresh=False)
        self.assertFalse(detail["hide_saved_automatic_justification"])
        self.assertEqual(detail["review"]["decision_justification"], "Ручний текст УО")

    def test_review_changes_are_audited_and_guarantee_is_tri_state(self):
        with patch.object(server, "api_get", return_value={"data": report_payload()}):
            server.save_violation_review("report-internal", {
                "additional_check_required": True, "guarantee_documents_visible": None,
                "supplier_explanation_assessment": "Документи переглянуто"})
        with server.db() as connection:
            review = connection.execute("SELECT * FROM violation_report_reviews").fetchone()
            events = connection.execute("SELECT COUNT(*) FROM violation_report_review_events").fetchone()[0]
        self.assertEqual(review["additional_check_required"], 1)
        self.assertIsNone(review["guarantee_documents_visible"])
        self.assertGreaterEqual(events, 2)

    def test_explicit_regeneration_records_hash_without_silent_overwrite(self):
        payload = report_payload()
        payload["defendantStatements"] = []
        server.save_violation_report(payload)
        context = {
            "rejection_present": True, "contract_guarantee_required": True,
            "rejected_before_deadline": False,
            "winner_selected_at": "2026-08-01T10:00:00+03:00",
            "contract_deadline": "2026-08-06", "rejection_date": "2026-08-07T12:00:00+03:00",
        }
        with patch.object(server, "api_get", return_value={"data": payload}), \
                patch.object(server, "build_procurement_context", return_value=context):
            result = server.save_violation_review("report-internal", {
                "action": "regenerate_justification", "internal_decision": "warning",
                "guarantee_documents_visible": False})
        self.assertTrue(result["review"]["decision_justification"])
        self.assertTrue(result["review"]["justification_source_hash"])
        self.assertFalse(result["review"]["justification_manually_edited"])
        self.assertEqual(result["review"]["decision_template_key"],
                         "p49_1_warning_guarantee_no_documents_no_explanation")

    def test_p1_approved_template_requires_exact_supported_combination(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "contract_guarantee_required": True,
            "rejected_before_deadline": False,
            "winner_selected_at": "2026-08-01T10:00:00+03:00",
            "contract_deadline": "2026-08-06", "rejection_date": "2026-08-07T12:00:00+03:00",
        }
        review = {"internal_decision": "warning", "guarantee_documents_visible": False}
        text = server.build_violation_decision_justification(report, context, review)
        self.assertNotIn("\r", text)
        self.assertNotIn("\n\n", text)
        self.assertIn("пп. 1 п. 49 Порядку № 822", text)
        self.assertIn("відсутні документи/відомості", text)
        self.assertNotIn("recommended_scenario", text)
        self.assertEqual(server.build_violation_decision_justification(
            report, context, {**review, "guarantee_documents_visible": None}), "")
        self.assertEqual(server.build_violation_decision_justification(
            {**report, "defendant_statements": [{"description": "Надано пояснення"}]},
            context, review), "")

    def test_p1_warning_without_guarantee_uses_approved_base_scenario(self):
        report = {"reason": "contractBreach", "defendant_statements": []}
        context = {
            "rejection_present": True, "contract_guarantee_required": False,
            "rejected_before_deadline": False,
            "winner_selected_at": "2026-08-18T10:00:00+03:00",
            "contract_deadline": "2026-08-24", "rejection_date": "2026-08-25T12:00:00+03:00",
        }
        review = {"internal_decision": "warning", "guarantee_documents_visible": None}
        self.assertEqual(server.violation_decision_template_key(report, context, review),
                         "p49_1_warning")
        text = server.build_violation_decision_justification(report, context, review)
        self.assertIn("пп. 1 п. 49 Порядку № 822", text)
        self.assertIn("не надано жодних доказів або пояснень", text)
        self.assertNotIn("забезпечення виконання договору", text)

    def test_p2_approved_template_adds_civil_code_only_for_weekend_shift(self):
        report = {"reason": "signingRefusal", "defendant_statements": []}
        context = {
            "written_refusal_within_deadline": True, "day_3_shifted": True,
            "winner_selected_at": "2026-08-20T10:00:00+03:00", "day_3": "2026-08-23",
            "day_3_weekday_uk_accusative": "неділю", "written_refusal_deadline": "2026-08-24",
        }
        review = {"internal_decision": "decline", "written_refusal_date": "2026-08-24"}
        shifted = server.build_violation_decision_justification(report, context, review)
        self.assertNotIn("\r", shifted)
        self.assertNotIn("\n\n", shifted)
        self.assertIn("ч. 5 ст. 254 ЦК України", shifted)
        self.assertIn("пп. 2 п. 49 Порядку № 822", shifted)
        ordinary = server.build_violation_decision_justification(
            report, {**context, "day_3_shifted": False}, review)
        self.assertNotIn("ст. 254 ЦК України", ordinary)

    def test_unsupported_reason_has_no_generated_legal_text(self):
        self.assertEqual(server.build_violation_decision_justification(
            {"reason": "goodsNonCompliance"}, {}, {"internal_decision": "warning"}), "")

    def test_violation_modal_uses_approved_wide_reason_specific_layout(self):
        source = (server.ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('class="violation-top-row"', source)
        self.assertIn("Замовник", source)
        self.assertIn("Постачальник", source)
        self.assertIn("Закупівля · Договір · Звернення", source)
        self.assertIn("Підстава та докази замовника", source)
        self.assertIn("Строк для документів постачальника — 3 р.д.", source)
        self.assertIn("Пояснення та документи постачальника", source)
        self.assertIn("Обґрунтування рішення буде доступне після завершення строку", source)
        self.assertIn("hide_saved_automatic_justification", source)
        self.assertIn("До завершення строку постачальника", source)
        self.assertIn("data-copy-violation-json", source)
        self.assertIn("/sheets-json", source)
        self.assertIn("JSON скопійовано", source)
        self.assertIn("['Код ДК / CPV',c.cpv]", source)
        self.assertIn("['Дата визначення переможцем',displayDateOnly(c.winner_selected_at)]", source)
        self.assertIn("['Дата відхилення',displayDateOnly(c.rejection_at)]", source)
        self.assertIn("['Підстава відхилення',c.rejection_reason]", source)

        reason_fields = source[source.rfind("function violationReasonFields(item)"):
                               source.rfind("requestContextBlock=function(item)")]
        p1 = reason_fields[reason_fields.find("if(item.reason==='contractBreach')"):
                           reason_fields.find("if(item.reason==='signingRefusal')")]
        self.assertIn("Дата визначення переможцем", p1)
        self.assertIn("Дата укладення договору", p1)
        self.assertIn("Забезпечення виконання договору", p1)
        self.assertIn("violationContractSigned", p1)
        self.assertNotIn("Письмова відмова", p1)
        self.assertNotIn("Рішення суду", p1)

        self.assertIn("syncContractDetails", source)
        self.assertIn("input.disabled=!enabled", source)

        module_css = (server.ROOT / "modules.css").read_text(encoding="utf-8")
        legacy_grid = module_css.find(".request-details-body{padding:18px 24px;display:grid")
        wide_override = module_css.rfind(".request-details-dialog-wide .request-details-body{display:block")
        self.assertGreater(wide_override, legacy_grid)
        self.assertIn(".request-details-dialog.request-details-dialog-wide{width:min(1500px,96vw)", module_css)


if __name__ == "__main__":
    unittest.main()
