import unittest

from supplier_edr_projection import project_supplier_facts


def facts(code="22562514", **overrides):
    value = {
        "supplier_code": code,
        "prozorro_status": "Активний",
        "google_sync_eligible": True,
        "entity_type": "legal_entity",
        "submissions": [{"id": "s1", "date_published": "2026-09-01T10:00:00",
                         "supplier_name": "Заявка", "application_manager_name": "Керівник А"}],
        "qualifications": [{"id": "q1", "submission_id": "s1", "status": "active",
                            "decision_date": "2026-09-02T10:00:00",
                            "protocol_date": "2026-09-02", "protocol_officer": "УО А"}],
        "verification_events": [],
        "profile": {},
    }
    value.update(overrides)
    return value


class SharedSupplierProjectionTests(unittest.TestCase):
    def test_eighteen_active_blank_google_metadata_cases_project_from_qualification(self):
        codes = ('22562514', '31678214', '35007125', '39156686', '39391415',
                 '40158393', '41245570', '43392975', '43419221', '44520905',
                 '44726167', '44900776', '45324378', '45610580', '45797244',
                 '45811436', '46386880', '46390813')
        for code in codes:
            with self.subTest(code=code):
                old_admission = {"id": 99, "event_type": "admission", "occurred_at": "2026-09-02",
                                 "officer": "Інша УО", "snapshot": {"edr_status": "Зареєстровано"}}
                result = project_supplier_facts(facts(code=code, verification_events=[old_admission]))
                self.assertEqual(result['edr_status'], 'Зареєстровано')
                self.assertEqual(result['verification_date'], '2026-09-02')
                self.assertEqual(result['verification_officer'], 'УО А')
                self.assertEqual(result['provenance']['I']['source_qualification_id'], 'q1')

    def test_not_in_registry_has_no_synthetic_edr_verification(self):
        result = project_supplier_facts(facts(prozorro_status='Ще не в реєстрі', qualifications=[]))
        self.assertIsNone(result['edr_status'])
        self.assertIsNone(result['verification_date'])
        self.assertIsNone(result['verification_officer'])

    def test_qualification_event_and_latest_application(self):
        result = project_supplier_facts(facts(), today=None)
        self.assertEqual(result["edr_status"], "Зареєстровано")
        self.assertEqual(result["verification_date"], "2026-09-02")
        self.assertEqual(result["verification_officer"], "УО А")
        self.assertEqual(result["last_application_date"], "2026-09-01")
        self.assertEqual(result["provenance"]["E"]["source_qualification_id"], "q1")

    def test_sandbox_no_fake_officer(self):
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": ""}])
        result = project_supplier_facts(row, officer_required=False)
        self.assertEqual(result["verification_date"], "2026-09-02")
        self.assertIsNone(result["verification_officer"])
        self.assertEqual(result["provenance"]["L"]["officer_availability"], "unavailable_in_sandbox")
        self.assertNotIn("qualification_officer_missing_required", result["conflicts"])

    def test_prod_requires_officer(self):
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": ""}])
        result = project_supplier_facts(row, officer_required=True)
        self.assertIsNone(result["verification_date"])
        self.assertIn("qualification_officer_missing_required", result["conflicts"])

    def test_later_qualification_beats_old_google_profile(self):
        old = {"id": 5, "event_type": "google_clarity", "occurred_at": "2026-09-01",
               "officer": "УО Б", "snapshot": {"edr_status": "Припинено"}}
        result = project_supplier_facts(facts(verification_events=[old]))
        self.assertEqual(result["edr_status"], "Зареєстровано")
        self.assertEqual(result["verification_officer"], "УО А")

    def test_later_google_event_beats_qualification(self):
        event = {"id": 5, "event_type": "google_clarity", "occurred_at": "2026-09-03",
                 "officer": "УО Б", "snapshot": {"edr_status": "🔴 Припинено"}}
        result = project_supplier_facts(facts(verification_events=[event]))
        self.assertEqual(result["edr_status"], "Припинено")
        self.assertEqual(result["verification_officer"], "УО Б")

    def test_same_day_conflict_date_only(self):
        event = {"id": 5, "event_type": "google_clarity", "occurred_at": "2026-09-02",
                 "officer": "УО Б", "snapshot": {"edr_status": "Припинено"}}
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": "УО А"}],
            verification_events=[event])
        result = project_supplier_facts(row)
        self.assertIsNone(result["verification_date"])
        self.assertIn("same_day_verification_order_ambiguous", result["conflicts"])

    def test_three_same_day_events_keep_ambiguity_independent_of_input_order(self):
        events = [
            {"id": 5, "event_type": "google_clarity", "occurred_at": "2026-09-02",
             "officer": "УО Б", "snapshot": {"edr_status": "Припинено"}},
            {"id": 6, "event_type": "google_clarity", "occurred_at": "2026-09-02",
             "officer": "УО А", "snapshot": {"edr_status": "Зареєстровано"}},
        ]
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": "УО А"}])
        for order in (events, list(reversed(events))):
            with self.subTest(order=[event["id"] for event in order]):
                result = project_supplier_facts({**row, "verification_events": order})
                self.assertIsNone(result["verification_date"])
                self.assertIn("same_day_verification_order_ambiguous", result["conflicts"])

    def test_same_day_equivalent_is_not_ambiguous(self):
        event = {"id": 5, "event_type": "google_clarity", "occurred_at": "2026-09-02",
                 "officer": "УО А", "snapshot": {"edr_status": "✅ Зареєстровано"}}
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": "УО А"}],
            verification_events=[event])
        result = project_supplier_facts(row)
        self.assertEqual(result["conflicts"], [])

    def test_latest_application_even_if_not_qualified(self):
        row = facts(submissions=[{"id": "s1", "date_published": "2026-09-01",
            "application_manager_name": "Керівник А"}, {"id": "s2", "date_published": "2026-09-05",
            "application_manager_name": "Керівник Б"}])
        result = project_supplier_facts(row)
        self.assertEqual(result["last_application_date"], "2026-09-05")

    def test_two_same_day_qualifications_use_actual_business_datetime(self):
        q1 = {"id": "q1", "submission_id": "s1", "status": "active",
              "decision_date": "2026-09-02T09:00:00", "protocol_date": "2026-09-02", "protocol_officer": "УО А"}
        q2 = {"id": "q2", "submission_id": "s2", "status": "active",
              "decision_date": "2026-09-02T15:00:00", "protocol_date": "2026-09-02", "protocol_officer": "УО Б"}
        result = project_supplier_facts(facts(qualifications=[q2, q1]))
        self.assertEqual(result["verification_officer"], "УО Б")
        self.assertEqual(result["provenance"]["I"]["source_qualification_id"], "q2")
        self.assertNotIn("same_day_verification_order_ambiguous", result["conflicts"])

    def test_legacy_unknown_officer_is_not_valid_new_prod_event(self):
        row = facts(qualifications=[{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02",
            "protocol_officer": "НЕ ВИЗНАЧЕНО"}])
        self.assertIn("qualification_officer_missing_required",
                      project_supplier_facts(row, officer_required=True)["conflicts"])
        self.assertIsNone(project_supplier_facts(row, officer_required=False)["verification_officer"])

    def test_inherited_manager_date_is_source_submission_not_latest_application(self):
        submissions = [{"id": "s1", "date_published": "2026-09-01T10:00:00",
            "application_manager_name": "Керівник А"},
            {"id": "s2", "date_published": "2026-09-05T10:00:00",
             "application_manager_name": "Керівник А", "manager_name_source": "previous_application",
             "manager_name_source_submission_id": "s1"}]
        result = project_supplier_facts(facts(submissions=submissions))
        self.assertEqual(result["provenance"]["D"]["source_submission_id"], "s1")
        self.assertEqual(result["provenance"]["D"]["event_date"], "2026-09-01")

    def test_later_application_day_changes_manager_after_date_only_verification(self):
        submissions = [{"id": "s1", "date_published": "2026-09-01",
            "application_manager_name": "Керівник А"},
            {"id": "s2", "date_published": "2026-09-03",
             "application_manager_name": "Керівник Б", "manager_name_source": "manual"}]
        qualifications = [{"id": "q1", "submission_id": "s1", "status": "active",
            "decision_date": "2026-09-02", "protocol_date": "2026-09-02", "protocol_officer": "УО А"}]
        result = project_supplier_facts(facts(submissions=submissions, qualifications=qualifications,
            profile={"manager_name": "Керівник А", "edr_checked_at": "2026-09-02",
                     "source_sheet": "ЮО"}))
        self.assertEqual(result["manager_for_verification"], "Керівник Б")
        self.assertEqual(result["provenance"]["D"]["event_date"], "2026-09-03")


if __name__ == "__main__":
    unittest.main()
