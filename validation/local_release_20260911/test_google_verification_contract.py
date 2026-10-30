import unittest
from datetime import datetime, timezone

from google_verification_contract import (
    google_verification_instant, incoming_verification_gate,
    google_verification_timestamp,
)


class GoogleVerificationContractTests(unittest.TestCase):
    def test_exact_kyiv_timestamp_keeps_time_and_offset(self):
        parsed = google_verification_instant("29.10.2026 14:27:49")
        self.assertEqual(parsed["kind"], "datetime")
        self.assertEqual(parsed["value"], datetime(2026, 10, 29, 12, 27, 49, tzinfo=timezone.utc))
        self.assertEqual(google_verification_timestamp("29.10.2026 14:27:49"),
                         "2026-10-29T14:27:49+02:00")

    def test_date_only_blank_and_malformed_values_are_not_instants(self):
        self.assertEqual(google_verification_instant("29.10.2026")["kind"], "date_only")
        self.assertEqual(google_verification_instant("")["kind"], "blank")
        self.assertEqual(google_verification_instant("29.10.2026 25:99:99")["kind"], "invalid")
        self.assertEqual(google_verification_timestamp("29.10.2026"), "")

    def test_dst_ambiguous_and_nonexistent_wall_times_are_rejected(self):
        self.assertEqual(google_verification_instant("25.10.2026 03:30:00")["kind"], "invalid")
        self.assertEqual(google_verification_instant("29.03.2026 03:30:00")["kind"], "invalid")

    def test_only_strictly_newer_exact_timestamps_are_accepted(self):
        old = "2026-10-29T14:27:49+02:00"
        self.assertTrue(incoming_verification_gate("29.10.2026 14:27:50", old)["accepted"])
        self.assertEqual(incoming_verification_gate("29.10.2026 14:27:49", old)["reason"], "equal")
        self.assertEqual(incoming_verification_gate("29.10.2026 14:27:48", old)["reason"], "older")

    def test_date_only_current_requires_a_later_calendar_day(self):
        self.assertEqual(incoming_verification_gate(
            "29.10.2026 14:27:49", "2026-10-29", require_time=True)["reason"],
            "current_date_only_not_newer_by_day")
        self.assertTrue(incoming_verification_gate(
            "30.10.2026 00:00:01", "2026-10-29", require_time=True)["accepted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
