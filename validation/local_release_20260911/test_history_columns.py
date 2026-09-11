import sqlite3,unittest
from unittest.mock import patch
import server

class HistoryColumnsTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute('''CREATE TABLE application_view_profiles(id TEXT PRIMARY KEY,owner_key TEXT,name TEXT,is_system INTEGER,source_system_profile_id TEXT,columns_json TEXT,created_at TEXT,updated_at TEXT,created_by TEXT,updated_by TEXT,UNIQUE(owner_key,name))''')
        self.p=patch.object(server,'db',return_value=self.c);self.p.start()
        self.columns=[dict(key=k,width=100,visible=True) for k in server.HISTORY_COLUMN_KEYS]
    def tearDown(self):self.p.stop();self.c.close()
    def test_personal_roundtrip(self):
        self.columns.reverse();self.columns[0]['width']=440;self.columns[1]['visible']=False
        server.history_column_settings('first',self.columns)
        restored=server.history_column_settings('first')['columns']
        self.assertEqual(restored[0]['width'],440);self.assertFalse(restored[1]['visible'])
        self.assertEqual(server.history_column_settings('second')['columns'],[])
        self.assertEqual(server.list_application_view_profiles('first')['items'],[])
    def test_invalid_payload(self):
        with self.assertRaises(ValueError):server.history_column_settings('first',[{'key':'bad'}])
    def test_viewer_only_own_presentation(self):
        self.assertTrue(server.mutation_allowed('viewer','POST','/api/history-columns'))
        self.assertFalse(server.mutation_allowed('viewer','PATCH','/api/applications/one'))
    def test_latest_supplier_name_by_submission_date(self):
        self.c.create_function('DIGITS',1,lambda s:''.join(x for x in (s or '') if x.isdigit()))
        self.c.execute('CREATE TABLE submissions(id TEXT,supplier_code TEXT,supplier_name TEXT,date_published TEXT)')
        self.c.executemany('INSERT INTO submissions VALUES(?,?,?,?)',[('a','123','Old','2026-09-01T10:00:00+03:00'),('b','123','Latest','2026-09-03T10:00:00+03:00'),('c','999','Other','2026-09-04T10:00:00+03:00')])
        self.assertEqual(server.latest_supplier_submission_name(self.c,'123'),'Latest')
        self.assertEqual(server.latest_supplier_submission_name(self.c,'000'),'')

if __name__=='__main__':unittest.main()
