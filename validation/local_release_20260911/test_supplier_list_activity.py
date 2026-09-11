from test_supplier_profile_activity import SupplierProfileActivityTests
import server


class SupplierListActivityTests(SupplierProfileActivityTests):
    def setUp(self):
        super().setUp()
        self.con.create_function('CASEFOLD',1,lambda v:str(v or '').casefold())

    def check(self,total,active):
        super().check(total,active)
        result=server.list_qualified_suppliers({'search':['3038301896']})
        self.assertEqual(result['active'],active)
        if total:
            row=result['items'][0]
            self.assertEqual([row[k] for k in ('qualifications_count','active_count','inactive_count')],[total,active,total-active])
            self.assertEqual(row['applications_count'],total)
        else:self.assertEqual(result['total'],0)
        filtered=server.list_qualified_suppliers({'search':['3038301896'],'status':['active']})
        self.assertEqual(filtered['total'],int(active>0))
        inactive=server.list_qualified_suppliers({'search':['3038301896'],'status':['terminated']})
        self.assertEqual(inactive['total'],int(total>0 and active==0))
