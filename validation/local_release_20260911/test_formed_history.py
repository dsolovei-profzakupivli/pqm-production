import unittest
import server
import formed_protocols as fp
from test_formed_protocols import FormedProtocolTests

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=FormedProtocolTests();self.fixture.setUp()
        with server.db() as con:
            con.execute("UPDATE application_fields SET protocol_number='999' WHERE submission_id IN ('s5','s6','s7')")
    def tearDown(self): self.fixture.tearDown()
    def test_chain_snapshots_and_archived_files(self):
        ids=[]
        for number in ('100','101','102'):
            with server.db() as con:
                con.execute("UPDATE application_fields SET protocol_number=? WHERE submission_id IN ('s0','s1','s2','s3','s4')",(number,))
            result=self.fixture.generate(number);ids.append(result['protocol_id'])
            if number!='102':
                with server.db() as con:fp.cancel(con,ids[-1],'test-admin',True,'Наступне формування')
        with server.db() as con:
            # Audit-only entries must not invent formations.
            fp.audit(con,'s0','test','formed_protocol_created','','missing-record')
            detail=fp.detail(con,ids[-1],server.PROTOCOLS_DIR)
            self.assertEqual(ids,[x['id'] for x in detail['history']])
            self.assertEqual(['cancelled','cancelled','active'],[x['status'] for x in detail['history']])
            for number,entry in zip(('100','101','102'),detail['history']):
                self.assertEqual(5,len(entry['items']))
                self.assertTrue(all(x['protocol_number']==number for x in entry['items']))
                self.assertTrue(entry['document_available']);self.assertTrue(entry['download_url'])
            # Missing path is reported, never reconstructed.
            con.execute("UPDATE formed_protocols SET document_path='missing.docx' WHERE id=?",(ids[0],))
            missing=fp.detail(con,ids[-1],server.PROTOCOLS_DIR)['history'][0]
            self.assertFalse(missing['document_available']);self.assertIsNone(missing['download_url'])
        unrelated=self.fixture.generate('999')
        with server.db() as con:
            self.assertEqual(1,len(fp.detail(con,unrelated['protocol_id'])['history']))

if __name__=='__main__':unittest.main()
