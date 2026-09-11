import json
import tempfile
import unittest
from pathlib import Path
import server
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer


class FunctionalPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old=server.DB_PATH
        server.DB_PATH=Path(self.temp.name)/'test.sqlite3'
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as c:
            for i in range(3):
                c.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,raw_json,synced_at) VALUES (?,?,?,?,'{}','2026-09-01')",(f'f{i}',f'UA-F-{i}',f'Відбір {i}',f'123{i}'))
                c.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,?,?,?,'{}','2026-09-01')",(f'q{i}',f'f{i}',f's{i}','pending'))
                c.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,qualification_id,documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,?,?,'{}','2026-09-01')",(f's{i}',f'f{i}','12345678','Тест постачальника',f'2026-09-0{i+1}',f'q{i}','[]'))
                c.execute('INSERT INTO application_fields(submission_id,manager_name,protocol_officer,contract_details,protocol_remarks) VALUES (?,?,?,?,?)',(f's{i}','КЕРІВНИК','Історична УО','Договір 77','Причина'))
            c.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES ('final','f0','s0','unsuccessful','{}','2026-09-01')")

    def tearDown(self):
        server.DB_PATH=self.old
        self.temp.cleanup()

    def test_history_cross_framework_filters_and_pagination(self):
        result=server.application_history({'code':['12345678'],'contract':['77'],'size':['2']})
        self.assertEqual(result['total'],3)
        self.assertEqual([x['id'] for x in result['items']],['s2','s1'])
        self.assertEqual(server.application_history({'status':['unsuccessful']})['items'][0]['id'],'s0')
        self.assertEqual(server.application_history({'from':['2026-09-02'],'cpv':['1231']})['total'],1)
        self.assertEqual(server.application_history({'code':['999']})['total'],0)
        self.assertEqual(server.application_history({'officer':['Історична'],'manager':['керівник']})['total'],3)

    def test_three_level_sort_uses_sql_and_keeps_stable_tiebreak(self):
        sorts=[{'key':'participant','direction':'asc'},{'key':'receivedDate','direction':'asc'},{'key':'dkCode','direction':'desc'}]
        result=server.list_applications({'sorts':[json.dumps(sorts)]})
        self.assertEqual([x['id'] for x in result['items']],['s0','s1','s2'])

    def test_history_sort_before_pagination_and_remarks_fragment(self):
        with server.db() as c:
            c.execute("UPDATE application_fields SET protocol_remarks='Інша причина' WHERE submission_id='s1'")
            c.execute("UPDATE application_fields SET protocol_remarks='',compliance_comments='Резервний текст' WHERE submission_id='s2'")
        sorts=json.dumps([{'key':'supplier','direction':'asc'},{'key':'date','direction':'asc'},{'key':'cpv','direction':'desc'}])
        result=server.application_history({'sorts':[sorts],'size':['1'],'page':['2']})
        self.assertEqual(result['total'],3)
        self.assertEqual(result['items'][0]['id'],'s1')
        self.assertEqual(server.application_history({'remarks':['ША ПРИЧ']})['items'][0]['id'],'s1')
        self.assertEqual(server.application_history({'remarks':['резервний']})['items'][0]['id'],'s2')
        self.assertEqual(server.application_history({'remarks':['неіснуючий']})['total'],0)
        for bad in ('{}','[{"key":"sql injection","direction":"asc"}]','[{"key":"date","direction":"oops"}]'):
            with self.assertRaises(ValueError):server.history_order_sql(bad)

    def test_profile_json_multisort_validation(self):
        sorts=[{'key':'receivedDate','direction':'desc'}]
        layout=json.loads(server._profile_layout_json([{'key':'participant'}],[],sorts))
        self.assertEqual(layout['sorts'],sorts)
        with self.assertRaises(ValueError):server.validated_application_sorts([{'key':'SQL injection'}])

    def test_schema_inventory_has_no_values(self):
        data=server.pqm_schema_metadata()
        self.assertTrue(any(x['table']=='submissions' and x['key']=='supplier_code' for x in data['items']))
        self.assertNotIn('Тест постачальника',json.dumps(data,ensure_ascii=False))
        self.assertFalse(server.admin_read_allowed('viewer','/api/admin/schema'))
        self.assertFalse(server.mutation_allowed('viewer','PATCH','/api/applications/s0'))

    def test_actual_dispatch_denies_viewer_mutations(self):
        old_auth,old_local=server.AUTH_ENABLED,server.LOCAL_ROLE_IMPERSONATION
        server.AUTH_ENABLED=False;server.LOCAL_ROLE_IMPERSONATION=True
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{http.server_port}/api/applications/s0',data=b'{}',method='PATCH',headers={'X-PQM-Local-Role':'viewer','Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403)
        finally:
            http.shutdown();http.server_close();thread.join()
            server.AUTH_ENABLED=old_auth;server.LOCAL_ROLE_IMPERSONATION=old_local
