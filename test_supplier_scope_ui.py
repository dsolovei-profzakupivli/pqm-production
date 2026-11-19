"""Synthetic read-only supplier queries: scope before supplier aggregation."""
import unittest
import test_supplier_filter_excel as fixture


class SupplierScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.SupplierFilterExcelTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.con = self.fixture.con

    def query(self, **params):
        return fixture.server.list_qualified_suppliers(params, connection=self.con)

    def test_multiple_dk_codes_or_and_framework_intersection(self):
        self.fixture.add('a', code='0001', fid='f1')
        self.fixture.add('b', code='0002', fid='f2')
        self.fixture.add('c', code='0003', fid='f3')
        self.assertEqual(self.query(dk_code=['03110000-1','03220000-2'])['total'],3)
        rows=self.query(dk_code=['03110000-1,03220000-2'],framework_id=['f1','f2'])
        self.assertEqual({r['code'] for r in rows['items']},{'0001','0002'})
        self.assertEqual(self.query(dk_code=['03220000-2'],framework_id=['f1'])['total'],0)

    def test_status_and_dk_do_not_match_different_memberships(self):
        self.fixture.add('a', fid='f1', contract='terminated')
        self.fixture.add('b', fid='f2', contract='active')
        self.assertEqual(self.query(dk_code=['03110000-1'],status=['active'])['total'],0)
        self.assertEqual(self.query(dk_code=['03110000-1'],status=['terminated'])['total'],1)

    def test_universal_cpv_search_uses_all_related_qualifications(self):
        self.fixture.add('a', fid='f1', contract='terminated')
        self.fixture.add('b', fid='f2')
        # The displayed scope has only f2's CPV, but search includes f1's qualification.
        for search in ['03110000-1','0311','0000000123','тест']:
            self.assertEqual(self.query(search=[search],framework_id=['f2'])['total'],1)
        self.assertEqual(self.query(search=['003110'])['total'],0)

    def test_search_precedes_pagination_and_preserves_zeroes(self):
        for i in range(23):
            self.fixture.add(str(i),code=f'{i:010d}',fid='f1')
        page=self.query(search=['0311'],page=['2'],size=['10'])
        self.assertEqual(page['total'],23)
        self.assertEqual(len(page['items']),10)
        self.assertEqual(len({r['code'] for r in page['items']}),10)
        self.assertTrue(all(r['code'].startswith('0') for r in page['items']))

    def test_query_has_no_writes(self):
        self.fixture.add('a')
        statements=[]
        self.con.set_trace_callback(statements.append)
        self.query(search=['031'],dk_code=['03110000-1'],framework_id=['f1'])
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP')) for s in statements))

    def test_universal_framework_name_and_full_or_partial_ua_f(self):
        self.fixture.add('ua',fid='f1')
        for term in ['UA-F-f1','ua-f-f','Відбір f1']:
            self.assertEqual(self.query(search=[term])['total'],1)
        self.assertEqual(self.query(search=['UA-F-f2'])['total'],0)
