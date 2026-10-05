"""Synthetic in-memory tests; no server, network or live Apply."""
import unittest
import edr_sync_v2 as sync
from test_edr_sync_v2 import database, row, snapshot

OFFICER = 'Тестова УО SANDBOX'


class SandboxCanonicalOfficerTests(unittest.TestCase):
    def fixture(self, count=1, current_officer=''):
        con = database()
        con.executescript("""CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT,role TEXT,active INTEGER);
          CREATE TABLE auth_users(username TEXT PRIMARY KEY,role TEXT,officer_id INTEGER,active INTEGER);""")
        con.execute('INSERT INTO authorized_officers VALUES(1,?,?,1)', (OFFICER, 'УО'))
        con.execute("INSERT INTO auth_users VALUES('sandbox.officer','officer',1,1)")
        rows = []
        for i in range(count):
            code = str(10000000 + i)
            con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,edr_officer,source_sheet,source_row,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (code, 'ПОВНА НАЗВА', 'СКОРОЧЕНА НАЗВА', '', 'Зареєстровано',
                         '2026-07-22', current_officer, 'ФОП', i+2, 'test'))
            rows.append(row(code=code, checked='22.07.2026', officer=OFFICER, manager=''))
        return con, snapshot(*rows)

    def test_canonical_officer_is_existing_active_account_not_login(self):
        con, _ = self.fixture()
        self.assertEqual(sync.canonical_sandbox_officer(con), OFFICER)
        con.execute("UPDATE auth_users SET active=0")
        self.assertEqual(sync.canonical_sandbox_officer(con), '')

    def test_4420_historical_normalizations_create_no_new_verification_events(self):
        con, source = self.fixture(4420)
        plan = sync.build_preview(con, source, sandbox_mode=True)
        self.assertEqual(plan['summary']['conflicts'], 0)
        self.assertEqual(plan['summary']['verification_event_changes'], 0)
        self.assertEqual(plan['summary']['same_date_officer_update_accepted'], 0)
        self.assertEqual(plan['summary']['sandbox_historical_officer_normalizations'], 4420)
        self.assertTrue(all(x['incoming']['edr_officer'] == '' for x in plan['items']))
        self.assertTrue(all(x['УО'] == OFFICER for x in source['rows']))
        result = sync.apply(con, source, source['source_fingerprint'], confirmed=True,
                            actor='synthetic test', synced_at='test', sandbox_mode=True)
        self.assertEqual(result['verification_events'], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_profiles WHERE edr_officer=?', (OFFICER,)).fetchone()[0], 0)
        self.assertEqual(sync.build_preview(con, source, sandbox_mode=True)['summary']['verification_event_changes'], 0)

    def test_actual_new_check_by_canonical_sandbox_officer_is_normal_verification(self):
        con, source = self.fixture()
        source['rows'][0]['Дата перевірки'] = '05.10.2026'
        plan = sync.build_preview(con, source, sandbox_mode=True)
        self.assertEqual(plan['summary']['conflicts'], 0)
        self.assertEqual(plan['summary']['verification_event_changes'], 1)
        self.assertFalse(plan['items'][0]['sandbox_historical_officer_normalization'])
        self.assertEqual(plan['items'][0]['incoming']['edr_officer'], OFFICER)

    def test_prod_has_no_sandbox_normalization(self):
        con, source = self.fixture()
        plan = sync.build_preview(con, source)
        self.assertNotIn('sandbox_historical_officer_normalizations', plan['summary'])
        self.assertFalse(plan['items'][0]['sandbox_historical_officer_normalization'])
        self.assertEqual(plan['items'][0]['incoming']['edr_officer'], OFFICER)
        self.assertEqual(plan['summary']['verification_event_changes'], 1)

    def test_historical_normalization_cannot_assert_new_factual_status(self):
        con, source = self.fixture()
        source['rows'][0]['Статус в реєстрі (ЄДР)'] = 'Припинено'
        plan = sync.build_preview(con, source, sandbox_mode=True)
        self.assertIn('historical_normalization_cannot_attest_factual_changes', plan['conflicts'][0]['reasons'])
        self.assertEqual(plan['summary']['verification_event_changes'], 0)

    def test_missing_canonical_account_blocks_without_creating_one(self):
        con, source = self.fixture()
        con.execute('DELETE FROM auth_users')
        plan = sync.build_preview(con, source, sandbox_mode=True)
        self.assertIn('sandbox_officer_identity_unavailable', plan['conflicts'][0]['reasons'])
        self.assertEqual(con.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0], 0)

    def test_nine_real_newer_verifications_stay_real(self):
        con, source = self.fixture(9)
        for raw in source['rows']:
            raw['Дата перевірки'] = '05.10.2026'
            raw['УО'] = 'Світлана НАМЯСЕНКО'
        plan = sync.build_preview(con, source, sandbox_mode=True)
        self.assertEqual(plan['summary']['conflicts'], 0)
        self.assertEqual(plan['summary']['newer_verification_accepted'], 9)
        self.assertEqual(plan['summary']['verification_event_changes'], 9)


if __name__ == '__main__':
    unittest.main()
