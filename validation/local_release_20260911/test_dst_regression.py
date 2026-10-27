"""DST contracts on disposable SQLite; no external source calls or live data."""
import gc
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import scheduler_runtime as scheduler
import server

KYIV = ZoneInfo('Europe/Kyiv')
UTC = timezone.utc

def instant(raw):
    return datetime.fromisoformat(raw.replace('Z', '+00:00'))


class DstTimeContracts(unittest.TestCase):
    def test_hourly_utc_slots_on_winter_spring_and_normal_days(self):
        for day in ('2026-10-25', '2027-03-28', '2026-07-12', '2026-12-12'):
            for hour in range(24):
                for minute in (0, 4, 5, 6, 59):
                    with self.subTest(day=day, hour=hour, minute=minute):
                        now = instant(f'{day}T{hour:02}:{minute:02}:00Z')
                        expected = now.replace(minute=5)
                        if expected <= now:
                            expected += timedelta(hours=1)
                        target = scheduler.next_hourly_run(now)
                        self.assertEqual(target.astimezone(UTC), expected)
                        self.assertEqual(target.isoformat(), target.astimezone(UTC).astimezone(KYIV).isoformat())

    def test_both_winter_slots_and_spring_gap(self):
        self.assertEqual(scheduler.next_hourly_run(instant('2026-10-25T00:06:00Z')).isoformat(),
                         '2026-10-25T03:05:00+02:00')
        self.assertEqual(scheduler.next_hourly_run(instant('2027-03-28T00:06:00Z')).isoformat(),
                         '2027-03-28T04:05:00+03:00')

    def test_legacy_naive_scheduler_input_remains_kyiv(self):
        self.assertEqual(scheduler.next_hourly_run(datetime(2026, 12, 12, 8, 4)).isoformat(),
                         '2026-12-12T08:05:00+02:00')

    def test_nazk_remains_at_0920_in_both_seasons(self):
        for now, target in [('2026-10-26T07:19:00Z','2026-10-26T09:20:00+02:00'),
                            ('2027-03-29T06:19:00Z','2027-03-29T09:20:00+03:00')]:
            self.assertEqual(scheduler.next_nazk_run(instant(now)).isoformat(),target)
            self.assertFalse(scheduler.nazk_due_today(instant(now),None))
            at=instant(target)
            self.assertTrue(scheduler.nazk_due_today(at,None))
            self.assertFalse(scheduler.nazk_due_today(at+timedelta(minutes=1),at.isoformat()))

    def test_date_deadline_end_of_kyiv_day_and_equivalent_offsets(self):
        for day, end in [('2026-10-25', '2026-10-25T22:00:00Z'),
                         ('2027-03-28', '2027-03-28T21:00:00Z'),
                         ('2026-07-12', '2026-07-12T21:00:00Z')]:
            boundary = instant(end)
            for now in (boundary - timedelta(microseconds=1), boundary, boundary + timedelta(seconds=1)):
                for represented in (now, now.astimezone(KYIV)):
                    passed = now >= boundary
                    self.assertEqual(server._deadline_passed(day, represented), passed)
                    self.assertEqual(server._within_calendar_deadline(represented, day), not passed)

    def test_absolute_deadlines_and_both_folds(self):
        self.assertTrue(server._deadline_passed('2026-10-25T03:45:00+03:00',
                                               instant('2026-10-25T03:15:00+02:00')))
        for raw in ('2026-10-25T03:30:00+03:00', '2026-10-25T03:30:00+02:00',
                    '2027-03-28T04:30:00+03:00'):
            at = instant(raw)
            self.assertFalse(server._deadline_passed(raw, at - timedelta(microseconds=1)))
            self.assertTrue(server._deadline_passed(raw, at))

    def test_ambiguous_and_nonexistent_naive_deadlines_not_guessed(self):
        for raw in ('2026-10-25T03:30:00', '2027-03-28T03:30:00'):
            self.assertFalse(server._deadline_passed(raw, instant('2027-04-01T00:00:00Z')))
        self.assertTrue(server._deadline_passed('2026-12-12T10:00:00',
                                               instant('2026-12-12T08:00:00Z')))

    def test_calendar_and_working_days_start_in_kyiv(self):
        # Friday UTC evening is Saturday in Kyiv; next Mon is still one working day.
        start = instant('2026-10-23T21:30:00Z')
        self.assertEqual(server._add_working_days(start, 1), '2026-10-26')
        self.assertEqual(server._calendar_deadline(start, 1)['calendar_day'], '2026-10-25')
        self.assertEqual(server._calendar_deadline(start, 1)['deadline'], '2026-10-26')
        self.assertEqual(server._add_working_days(datetime(2026, 10, 23), 1), '2026-10-26')

    def test_blank_invalid_and_legacy_date_inputs(self):
        self.assertFalse(server._deadline_passed(None))
        self.assertFalse(server._deadline_passed('invalid'))
        self.assertIsNone(server._within_calendar_deadline(None, '2026-10-25'))
        self.assertTrue(server._within_calendar_deadline(datetime(2026, 10, 25), '2026-10-25'))

    def test_exact_microsecond_order_and_invalid_timestamp_contract(self):
        a = '2026-10-25T03:10:00.000001+02:00'
        b = '2026-10-25T01:10:00.000002Z'
        self.assertEqual(server._timestamp_us(b) - server._timestamp_us(a), 1)
        self.assertEqual(server._timestamp_us(a), server._timestamp_us('2026-10-25T01:10:00.000001Z'))
        self.assertIsNone(server._timestamp_us('2026-10-25T03:30:00'))
        self.assertIsNone(server._timestamp_us('invalid'))
        self.assertIsNotNone(server._timestamp_us('2026-10-25'))


class DstDatabaseContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path, self.old_db = server.DB_PATH, server.db
        server.DB_PATH = Path(self.temp.name) / 'synthetic.sqlite3'
        self.con = self.old_db()
        server.db = lambda: self.con
        server.init_db()
        server.init_reference_tables(server.DB_PATH)

    def tearDown(self):
        server.db = self.old_db
        self.con.close()
        server.DB_PATH = self.old_path
        gc.collect()
        self.temp.cleanup()

    def report(self, number, stamp):
        org = lambda code: {'identifier': {'id': code}, 'name': code}
        return {'id': 'dst-' + str(number), 'violationReportID': 'DST-' + str(number),
                'status': 'pending', 'datePublished': stamp, 'dateModified': stamp,
                'author': org('11111111'), 'defendants': [org('22222222')],
                'authority': org('40996564'), 'details': {'reason': 'contractBreach'},
                'tender_id': 'synthetic-tender'}

    def test_actual_appeals_day_filters_include_entire_25_and_23_hour_days(self):
        for prefix, day, start, end in [('w', '2026-10-25', '2026-10-24T21:00:00Z', '2026-10-25T22:00:00Z'),
                                       ('s', '2027-03-28', '2027-03-27T22:00:00Z', '2027-03-28T21:00:00Z')]:
            begin, finish = instant(start), instant(end)
            stamps = [begin-timedelta(seconds=1), begin, begin+timedelta(hours=3),
                      finish-timedelta(microseconds=1), finish]
            for i, at in enumerate(stamps):
                server.save_violation_report(self.report(prefix+str(i), at.isoformat()))
            before = list(self.con.iterdump())
            with patch.object(server, 'api_get', side_effect=AssertionError('No network')):
                result = server.list_violation_reports({'date_from': [day], 'date_to': [day]})
            self.assertEqual({r['id'] for r in result['items']}, {'dst-'+prefix+str(i) for i in (1,2,3)})
            self.assertEqual(result['total'], 3)
            self.assertEqual(list(self.con.iterdump()), before)

    def test_appeals_same_payload_replay_does_not_duplicate_business_rows(self):
        payload = self.report('repeat', '2026-10-25T03:30:00+03:00')
        server.save_violation_report(payload)
        counts = lambda: tuple(self.con.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]
                               for name in ('violation_reports', 'violation_report_reviews', 'operational_tasks'))
        before = counts()
        server.save_violation_report(payload)
        self.assertEqual(counts(), before)

    def test_actual_appeals_order_is_absolute_in_both_directions(self):
        server.save_violation_report(self.report('early', '2026-10-25T03:50:00+03:00'))
        server.save_violation_report(self.report('late', '2026-10-25T03:10:00+02:00'))
        server.save_violation_report(self.report('invalid', 'invalid'))
        for params, expected in [({'status': ['pending']}, ['dst-early','dst-late','dst-invalid']),
                                 ({}, ['dst-late','dst-early','dst-invalid'])]:
            with patch.object(server, 'api_get', side_effect=AssertionError('No network')):
                self.assertEqual([r['id'] for r in server.list_violation_reports(params)['items']],expected)

    def test_supplier_profile_selects_latest_absolute_milestone_and_contract(self):
        code = '10000001'
        early, late = '2026-10-25T03:50:00+03:00', '2026-10-25T03:10:00+02:00'
        with self.con:
            self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,refreshed_at) VALUES (?,?,?)",
                             (code, 'Synthetic', server.now_iso()))
            self.con.execute("INSERT INTO frameworks(id,pretty_id,title,raw_json,synced_at,status) VALUES ('dst-f','DST','Fixture','{}',?,'active')", (server.now_iso(),))
            for key, stamps in [('old', [early]), ('new', [late, early])]:
                raw = json.dumps({'milestones': [{'dateModified': early, 'documents': [
                    {'datePublished': stamp} for stamp in stamps]}]})
                self.con.execute("""INSERT INTO registry_contracts(id,supplier_code,framework_id,status,raw_json,synced_at)
                  VALUES (?,?,?,'active',?,?)""", (key,code,'dst-f',raw,server.now_iso()))
        with patch.object(server, 'api_get', side_effect=AssertionError('No network')):
            result = server.supplier_profile(code)
        self.assertEqual(len(result['qualifications']), 1)
        self.assertEqual(result['qualifications'][0]['id'], 'new')
        self.assertEqual(result['qualifications'][0]['event_date'], late)


class DstLeaseContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'lease.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_live_lease_blocks_restart_manual_and_second_fold(self):
        at = instant('2026-10-25T00:59:00Z')
        self.assertEqual(scheduler.claim(self.path,'prozorro',trigger='scheduled',now=at,owner_id='first'),'first')
        self.assertIsNone(scheduler.claim(self.path,'prozorro',trigger='manual',now=at+timedelta(seconds=30),owner_id='other'))
        self.assertTrue(scheduler.renew(self.path,'prozorro','first',now=at+timedelta(minutes=1)))
        self.assertIsNone(scheduler.claim(self.path,'prozorro',trigger='startup_catchup',now=at+timedelta(minutes=2),owner_id='restart'))

    def test_crashed_owner_expires_in_utc_and_cannot_finish_recovered_run(self):
        for text in ('2026-10-25T00:59:00Z','2027-03-28T00:59:00Z'):
            at = instant(text)
            self.assertEqual(scheduler.claim(self.path,'prozorro',trigger='scheduled',now=at,owner_id='crashed'),'crashed')
            self.assertEqual(scheduler.claim(self.path,'prozorro',trigger='startup_catchup',now=at+timedelta(minutes=4),owner_id='recovered'),'recovered')
            self.assertFalse(scheduler.finish(self.path,'prozorro','crashed',now=at+timedelta(minutes=5)))
            self.assertTrue(scheduler.finish(self.path,'prozorro','recovered',now=at+timedelta(minutes=5)))

    def test_parallel_claim_has_one_owner(self):
        with sqlite3.connect(self.path) as con:
            scheduler.migrate(con)
        con.close()
        barrier = threading.Barrier(2)
        answers, errors = [], []
        def claim(owner):
            try:
                barrier.wait()
                answers.append(scheduler.claim(self.path,'violation_reports',trigger='scheduled',
                                               now=instant('2026-10-25T01:05:00Z'),owner_id=owner))
            except Exception as exc:
                errors.append(exc)
        workers = [threading.Thread(target=claim,args=(name,)) for name in ('a','b')]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=10)
        self.assertFalse(errors)
        self.assertEqual(sum(x is not None for x in answers),1)

    def test_restart_catchup_uses_elapsed_time_not_repeated_wall_label(self):
        self.assertFalse(scheduler.hourly_catchup_due(instant('2026-10-25T01:04:59Z'),'2026-10-25T00:05:00Z'))
        self.assertTrue(scheduler.hourly_catchup_due(instant('2026-10-25T01:05:00Z'),'2026-10-25T00:05:00Z'))


if __name__ == '__main__':
    unittest.main()
