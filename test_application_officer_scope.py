"""Full filtered-set protocol-officer KPIs, never page or review-officer counts."""
from contextlib import nullcontext
import unittest
from unittest.mock import patch
import test_supplier_filter_excel as fixture


class OfficerScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.SupplierFilterExcelTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.con=self.fixture.con
        for i in range(83):
            officer='Олена ЄРЬОМІНА' if i<2 else 'Тетяна ФЕДЧЕНКО' if i<28 else 'Дмитро САВВА'
            code='1531000'+str(i) if i<2 else f'{1000+i:010d}'
            self.fixture.add('k'+str(i),code=code)
            self.con.execute('INSERT INTO application_fields(submission_id,protocol_officer,review_officer) VALUES(?,?,?)',('k'+str(i),officer,'Інша УО розгляду'))
    def stats(self,**query):
        with patch.object(fixture.server,'db',side_effect=lambda:nullcontext(self.con)):
            return fixture.server.application_stats({k:[v] for k,v in query.items()})
    def test_search_1531_only_two_yeriomina(self):
        result=self.stats(search='1531');self.assertEqual(result['applications'],2)
        self.assertEqual(result['officers'],[{'officer':'Олена ЄРЬОМІНА','applications':2}])
    def test_active_officer_filter_has_only_its_26_rows(self):
        result=self.stats(officer='Тетяна ФЕДЧЕНКО',page='2',size='10')
        self.assertEqual(result['applications'],26)
        self.assertEqual(result['officers'],[{'officer':'Тетяна ФЕДЧЕНКО','applications':26}])
    def test_empty_and_other_filters_combine(self):
        self.assertEqual(self.stats(search='1531',officer='Дмитро САВВА')['officers'],[])
        self.assertEqual(self.stats(search='never-exists')['applications'],0)
        self.assertEqual(self.stats(status='Очікує рішення')['officers'],[])
        self.assertEqual(sum(item['applications'] for item in self.stats()['officers']),83)
