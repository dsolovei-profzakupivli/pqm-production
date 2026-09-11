import json
import re
import sqlite3
import unittest
from supplier_contacts import supplier_contacts, supplier_email


class SupplierContactsTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.create_function('DIGITS', 1, lambda x: re.sub(r'\D', '', x or ''))
        self.con.executescript('CREATE TABLE frameworks(id TEXT,pretty_id TEXT); CREATE TABLE submissions(id TEXT,date_published TEXT,synced_at TEXT,raw_json TEXT,supplier_code TEXT,framework_id TEXT);')

    def tearDown(self):
        self.con.close()

    def add(self, ident, date, contact):
        self.con.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?)', (ident,date,date,json.dumps({'tenderers':[{'contactPoint':contact}]}),'43897155','f'))

    def test_latest_changes_and_history_does_not_override(self):
        self.add('1','2026-08-01',{'email':'old@example.com'})
        self.add('2','2026-09-01',{'email':'opt@gurkit.com.ua'})
        self.assertEqual(supplier_email(self.con,'43897155'),'opt@gurkit.com.ua')
        self.add('3','2026-09-09',{'email':'new@example.com'})
        card=supplier_contacts(self.con,'43897155')
        self.assertEqual(supplier_email(self.con,'43897155'),card['current']['email'])
        self.assertEqual(card['current']['email'],'new@example.com')
        self.assertEqual(len(card['history']),2)
        import server
        self.assertIs(server.supplier_contacts,supplier_contacts)

    def test_missing_latest_email_no_fallback(self):
        self.add('1','2026-08-01',{'email':'old@example.com'})
        for contact in ({'name':'Current'}, {}):
            with self.subTest(contact=contact):
                self.con.execute("DELETE FROM submissions WHERE id='2'")
                self.add('2','2026-09-01',contact)
                self.assertIsNone(supplier_email(self.con,'43897155'))
                card=supplier_contacts(self.con,'43897155')
                self.assertEqual(card['current']['submission_id'],'2')
                self.assertEqual(card['history'][0]['email'],'old@example.com')

    def test_no_submissions(self):
        self.assertIsNone(supplier_email(self.con,'43897155'))

    def test_same_date_uses_existing_id_tiebreak(self):
        self.add('1','2026-09-01',{'email':'a@example.com'})
        self.add('2','2026-09-01',{'email':'b@example.com'})
        self.assertEqual(supplier_email(self.con,'43897155'),'b@example.com')
