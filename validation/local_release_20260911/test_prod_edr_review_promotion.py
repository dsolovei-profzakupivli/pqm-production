import unittest

import edr_sync_review
import edr_sync_v2 as sync
try:
    from test_edr_sync_v2 import database, row, snapshot
except ImportError:
    from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


class ProdEdrReviewPromotionTests(unittest.TestCase):
    def test_complete_review_and_google_owned_clear_are_read_only(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,edr_status,edr_checked_at,edr_officer,
           termination_decision_details,edr_notes,synced_at)
          VALUES('12345678','OLD NAME','Неактуально','2026-09-15','OLD OFFICER',
                 'OLD TERMINATION','OLD NOTE','old')""")
        con.commit()
        google = row(checked='16.09.2026', officer='NEW OFFICER')
        google[6] = ''
        google[12] = ''
        before = con.total_changes
        preview = sync.build_preview(con, snapshot(google))
        details = edr_sync_review.details(preview)
        self.assertEqual(con.total_changes, before)
        self.assertEqual(next(x for x in details if x['field'] == 'verification_pair')['action'], 'accept_google_pair')
        self.assertEqual(next(x for x in details if x['field'] == 'termination_decision_details')['action'], 'clear')
        self.assertEqual(next(x for x in details if x['field'] == 'edr_notes')['action'], 'clear')
        self.assertEqual(edr_sync_review.summary_additions(preview, details)['m_note_clears'], 1)

    def test_state_digest_rejects_stale_pqm_before_business_write(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES('12345678','old')")
        source = snapshot(row())
        digest = sync.preview_state_digest(sync.build_preview(con, source))
        con.execute("UPDATE supplier_edr_profiles SET full_name='CHANGED' WHERE supplier_code='12345678'")
        before = con.total_changes
        with self.assertRaisesRegex(RuntimeError, 'PQM state changed'):
            sync.apply(con, source, source['source_fingerprint'], confirmed=True, actor='test',
                       synced_at='2026-09-27T10:00:00', expected_state_digest=digest)
        self.assertEqual(con.total_changes, before)

    def test_review_not_truncated_after_500_suppliers(self):
        con = database()
        google_rows = []
        for number in range(501):
            code = str(10000000 + number)
            con.execute('INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES (?,?)', (code, 'old'))
            google_rows.append(row(code=code))
        values = {'ФОП': [list(sync.HEADERS), *google_rows], 'ЮО': [list(sync.HEADERS)]}
        source = sync.source_snapshot(values)
        before = con.total_changes
        details = edr_sync_review.details(sync.build_preview(con, source))
        self.assertGreaterEqual(len({item['supplier_code'] for item in details}), 501)
        self.assertEqual(con.total_changes, before)


if __name__ == '__main__':
    unittest.main()
