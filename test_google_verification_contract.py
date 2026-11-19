import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from google_verification_contract import (incoming_verification_gate, verification_instant,
    decision_datetime_precision, google_verification_instant, google_verification_timestamp)


class VerificationDatetimeContract(unittest.TestCase):
    def test_existing_decision_timestamp_needs_no_separate_signature_fetch(self):
        self.assertEqual(decision_datetime_precision('2026-10-12T17:03:00+03:00'), 'instant')
        self.assertEqual(decision_datetime_precision('12.10.2026 17:03:00'), 'instant')
        self.assertEqual(decision_datetime_precision('2026-10-12'), 'day')
        self.assertEqual(decision_datetime_precision('invalid'), 'missing')

    def test_same_day_different_seconds(self):
        self.assertTrue(incoming_verification_gate("2026-10-12T17:03:01+03:00", "12.10.2026 17:03:00")["accepted"])
        self.assertFalse(incoming_verification_gate("2026-10-12T17:03:00+03:00", "12.10.2026 17:03:01")["accepted"])

    def test_equal_instant_different_timezones(self):
        self.assertEqual(incoming_verification_gate("2026-10-12T17:03:00+03:00", "2026-10-12T14:03:00Z")["reason"], "equal")

    def test_blank_and_invalid_both_directions(self):
        self.assertTrue(incoming_verification_gate("2026-10-12T17:03:00+03:00", "")["accepted"])
        for first, second in [("", "2026-10-12"), ("invalid", ""), ("2026-10-12", "invalid")]:
            self.assertFalse(incoming_verification_gate(first, second)["accepted"])

    def test_calendar_offsets_gap_fold(self):
        for value in ["2026-02-30T12:00:00+02:00", "2026-10-12T12:00:00+15:00", "2026-03-29T03:30:00", "2026-10-25T03:30:00"]:
            self.assertEqual(verification_instant(value)["kind"], "invalid", value)

    def test_explicit_fold_offset_is_known_instant(self):
        self.assertEqual(verification_instant("2026-10-25T03:30:00+03:00")["kind"], "datetime")

    def test_sheet_serial_fraction_retains_seconds(self):
        parsed = verification_instant(46307 + (17 * 3600 + 3 * 60 + 19) / 86400)
        self.assertEqual(parsed["value"].astimezone(__import__('zoneinfo').ZoneInfo('Europe/Kyiv')).strftime('%H:%M:%S'), '17:03:19')

    def test_date_only_is_kyiv_midnight_for_cross_day_and_same_day_ordering(self):
        cases = [
            ("30.10.2026", "29.10.2026 16:50:00", True, "newer"),
            ("29.10.2026", "30.10.2026 09:00:00", False, "older"),
            ("29.10.2026 17:00:00", "29.10.2026 16:50:00", True, "newer"),
            ("29.10.2026", "29.10.2026 16:50:00", False, "older"),
            ("29.10.2026 16:50:00", "29.10.2026", True, "newer"),
            ("29.10.2026", "29.10.2026", False, "equal"),
        ]
        for incoming, current, accepted, reason in cases:
            with self.subTest(incoming=incoming, current=current):
                gate = incoming_verification_gate(incoming, current, require_time=True)
                self.assertEqual(gate, {"accepted": accepted, "reason": reason})

    def test_date_only_google_value_compares_as_midnight_but_stays_date_when_stored(self):
        parsed = verification_instant("29.10.2026")
        self.assertEqual(parsed["kind"], "datetime")
        self.assertEqual(parsed["value"].astimezone(ZoneInfo("Europe/Kyiv")).isoformat(),
                         "2026-10-29T00:00:00+02:00")
        self.assertEqual(google_verification_instant("29.10.2026")["kind"], "datetime")
        self.assertEqual(google_verification_timestamp("29.10.2026"), "2026-10-29")
        self.assertEqual(google_verification_timestamp("29.10.2026 16:50:41"),
                         "2026-10-29T16:50:41+02:00")
        serial = verification_instant(46324)
        self.assertEqual(serial["kind"], "datetime")
        self.assertEqual(google_verification_timestamp(46324), "2026-10-29")

    def test_date_only_kyiv_canonical_timezone_has_expected_seasonal_offsets(self):
        # The product accepts Europe/Kiev as a Google timezone identifier, but
        # uses only canonical Europe/Kyiv for date interpretation. Some slim
        # Linux timezone databases omit the legacy Europe/Kiev alias link, so
        # this regression guards the actual canonical date-only behavior.
        for value, expected in (
            ("15.01.2026", "2026-01-15T00:00:00+02:00"),
            ("15.07.2026", "2026-07-15T00:00:00+03:00"),
        ):
            with self.subTest(date=value):
                parsed = verification_instant(value)
                self.assertEqual(parsed["kind"], "datetime")
                self.assertEqual(parsed["value"].astimezone(ZoneInfo("Europe/Kyiv")).isoformat(), expected)


if __name__ == '__main__':
    unittest.main()
