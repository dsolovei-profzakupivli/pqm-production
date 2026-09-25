import sqlite3
import unittest
from unittest.mock import patch

import edr_sync_v2


def database():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript('''
      CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT);
      CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT,supplier_code TEXT,date_published TEXT);
      CREATE TABLE qualifications(id TEXT PRIMARY KEY,framework_id TEXT,submission_id TEXT,status TEXT);
      CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,framework_id TEXT,qualification_id TEXT,supplier_code TEXT,status TEXT);
      CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,protocol_number TEXT,protocol_date TEXT,
        protocol_officer TEXT,review_officer TEXT,protocol_decision TEXT,marketplace_decision TEXT,
        generated_protocol_number TEXT,generated_protocol_date TEXT,generated_protocol_decision TEXT,
        protocol_generated_at TEXT,updated_by TEXT);
      CREATE TABLE formed_protocols(id TEXT PRIMARY KEY,protocol_number TEXT,protocol_date TEXT,
        officer TEXT,status TEXT);
      CREATE TABLE formed_protocol_members(protocol_id TEXT,submission_id TEXT,active INTEGER);
      CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,edr_status TEXT DEFAULT '',
        edr_checked_at TEXT DEFAULT '',edr_officer TEXT DEFAULT '',synced_at TEXT NOT NULL);
      CREATE TABLE supplier_edr_sync_log(id INTEGER PRIMARY KEY,started_at TEXT,status TEXT);
    ''')
    edr_sync_v2.migrate(con)
    con.execute("INSERT INTO frameworks VALUES('f','active','{}')")
    con.execute("INSERT INTO submissions VALUES('s','f','12345678','2026-08-30')")
    con.execute("INSERT INTO qualifications VALUES('q','f','s','active')")
    con.execute("INSERT INTO registry_contracts VALUES('c','f','q','12345678','active')")
    con.execute('''INSERT INTO application_fields VALUES
      ('s','P-1','2026-08-31','Protocol Officer','Protocol Officer','admit','admit',
       'P-1','2026-08-31','admit','2026-08-31T12:00:00','officer')''')
    con.execute("INSERT INTO formed_protocols VALUES('p','P-1','2026-08-31','Protocol Officer','active')")
    con.execute("INSERT INTO formed_protocol_members VALUES('p','s',1)")
    return con


class FutureAdmissionTests(unittest.TestCase):
    def materialize(self, con):
        return edr_sync_v2.materialize_effective_admission(con, 'c', '2026-09-01T12:00:00')

    def test_effective_admission_materializes_protocol_provenance(self):
        con = database()
        self.assertTrue(self.materialize(con))
        profile = con.execute('SELECT * FROM supplier_edr_profiles').fetchone()
        self.assertEqual((profile['edr_status'], profile['edr_checked_at'], profile['edr_officer']),
                         ('Зареєстровано', '2026-08-31', 'Protocol Officer'))
        self.assertNotEqual(profile['edr_checked_at'], '2026-08-30')
        event = con.execute('SELECT * FROM supplier_edr_verification_events').fetchone()
        self.assertEqual(event['source_submission_id'], 's')
        self.assertEqual(event['officer'], 'Protocol Officer')
        self.assertFalse(self.materialize(con))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0], 1)

    def test_not_yet_effective_does_not_materialize(self):
        for sql in ("UPDATE registry_contracts SET status='pending'",
                    "UPDATE qualifications SET status='pending'",
                    "UPDATE frameworks SET status='inactive'",
                    "UPDATE application_fields SET marketplace_decision=''"):
            with self.subTest(sql=sql):
                con = database()
                con.execute(sql)
                self.assertFalse(self.materialize(con))
                self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_profiles').fetchone()[0], 0)

    def test_default_or_unproven_officer_rejected(self):
        for sql in ("UPDATE formed_protocol_members SET active=0",
                    "UPDATE application_fields SET protocol_generated_at=''",
                    "UPDATE formed_protocols SET officer='Different Officer'"):
            with self.subTest(sql=sql):
                con = database()
                con.execute(sql)
                self.assertFalse(self.materialize(con))

    def test_newer_contradictory_edr_evidence_preserved(self):
        for checked in ('2026-09-02',):
            con = database()
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,edr_status,edr_checked_at,edr_officer,synced_at)
              VALUES('12345678','Припинено',?,'EDR','old')""", (checked,))
            self.assertFalse(self.materialize(con))
            self.assertEqual(con.execute('SELECT edr_status FROM supplier_edr_profiles').fetchone()[0], 'Припинено')
        con = database()
        con.execute('''INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,snapshot_hash,snapshot_json,created_at)
          VALUES ('12345678','manual_edr','2026-09-02','EDR','manual','hash',
          '{"edr_status":"Припинено"}','2026-09-02')''')
        self.assertFalse(self.materialize(con))

    def test_older_profile_status_is_superseded_by_effective_admission(self):
        for status, checked in (('Неактуально', '2026-08-01'),
                                ('Немає інформації', '2026-08-01'),
                                ('', ''), ('Неактуально', '')):
            with self.subTest(status=status, checked=checked):
                con = database()
                con.execute('''INSERT INTO supplier_edr_profiles
                  (supplier_code,edr_status,edr_checked_at,edr_officer,synced_at)
                  VALUES('12345678',?,?,?,?)''', (status, checked, 'Old Officer', 'old'))
                self.assertTrue(self.materialize(con))
                row = con.execute('SELECT edr_status,edr_checked_at,edr_officer FROM supplier_edr_profiles').fetchone()
                self.assertEqual(tuple(row), ('Зареєстровано', '2026-08-31', 'Protocol Officer'))

    def test_older_authoritative_event_is_superseded_and_later_evidence_can_win(self):
        con = database()
        con.execute('''INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,snapshot_hash,snapshot_json,created_at)
          VALUES ('12345678','manual_edr','2026-08-01','EDR','manual','old-hash',
          '{"edr_status":"Неактуально"}','2026-08-01')''')
        self.assertTrue(self.materialize(con))
        con.execute("UPDATE supplier_edr_profiles SET edr_status='Неактуально',edr_checked_at='2026-09-02'")
        self.assertFalse(self.materialize(con))
        self.assertEqual(con.execute('SELECT edr_status FROM supplier_edr_profiles').fetchone()[0], 'Неактуально')

    def test_malformed_newer_authoritative_evidence_fails_closed(self):
        con = database()
        con.execute('''INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,snapshot_hash,snapshot_json,created_at)
          VALUES ('12345678','manual_edr','2026-09-02','EDR','manual','bad-hash',
          '{invalid-json','2026-09-02')''')
        self.assertFalse(self.materialize(con))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_profiles').fetchone()[0], 0)

    def test_transaction_rollback_removes_event_and_profile(self):
        con = database()
        con.commit()
        try:
            with con:
                self.assertTrue(self.materialize(con))
                raise RuntimeError('later sync failure')
        except RuntimeError:
            pass
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_profiles').fetchone()[0], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0], 0)

    def test_meddata_untouched(self):
        con = database()
        with patch('historical_applications.provenance', return_value={'legacy': True}):
            self.assertFalse(self.materialize(con))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_profiles').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
