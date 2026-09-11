import unittest
import server
import formed_protocols
from test_formed_protocols import FormedProtocolTests

class BulkClearFilterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FormedProtocolTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def ids(self, **params):
        where, args = server.application_filter({k: [v] for k, v in params.items()})
        with server.db() as con:
            return [r[0] for r in con.execute('SELECT s.id FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id LEFT JOIN frameworks f ON f.id=s.framework_id LEFT JOIN qualifications q ON q.id=s.qualification_id WHERE '+where+' ORDER BY s.id', args)]

    def test_exact_number_combines_and_empty_resets(self):
        self.assertEqual(['s0','s1','s2','s3','s4'], self.ids(protocol_number='100'))
        self.assertEqual([], self.ids(protocol_number='10'))
        self.assertEqual(['s2'], self.ids(protocol_number='100', submission_id='s2'))
        self.assertEqual([], self.ids(protocol_number='101', submission_id='s2'))
        self.assertEqual(8, len(self.ids(protocol_number='')))
        self.assertEqual([], self.ids(protocol_number="100' OR 1=1 --"))

    def test_explicit_clear_cannot_bypass_formed_lock(self):
        result = self.fixture.generate()
        with server.db() as con:
            for field in ('protocol_number','protocol_date','protocol_officer'):
                with self.assertRaises(ValueError):
                    formed_protocols.guard_edit(con, 's0', {field:''})
            formed_protocols.cancel(con, result['protocol_id'], 'test', True, 'test')
            for field in ('protocol_number','protocol_date','protocol_officer'):
                formed_protocols.guard_edit(con, 's0', {field:''})

if __name__ == '__main__':
    unittest.main()
