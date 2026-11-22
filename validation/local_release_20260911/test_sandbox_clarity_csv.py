"""Eight-column ClarityChecker CSV: synthetic SQLite and real HTTP downloads."""
import base64
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import server
import edr_sync_v2

FIRST=['Код ЄДРПОУ','Стара Назва','Старий Статус','Старий ПІБ Керівника','Фактична дата перевірки ЄДР']
EXTRA=['Статус Prozorro','Дата останньої заявки','УО']

def parse(raw):return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))

class ClarityFormatTests(unittest.TestCase):
    def test_headers_append_only(self):self.assertEqual(server.EDR_EXPORT_HEADERS,FIRST+EXTRA)

    def test_precise_times_offsets_and_dst_fold_survive(self):
        for value in ['2026-10-29T16:50:47.123+02:00','2026-10-29T16:50:47.123456Z',
                      '2026-10-25T03:05:00.123456+03:00','2026-10-25T03:05:00.123456+02:00']:
            self.assertEqual(server._clarity_export_timestamp(value),value.replace('T',' '))

    def test_ukrainian_time_and_legacy_calendar_contract(self):
        self.assertEqual(server._clarity_export_timestamp('29.10.2026 16:50:47'),'2026-10-29 16:50:47')
        self.assertEqual(server._clarity_export_timestamp('29.10.2026'),'2026-10-29 00:00:00')

    def test_blank_and_invalid_do_not_become_a_fake_timestamp(self):
        for value in [None,'','bad','2026-10-29T25:50:47','2026-10-29T16:50:47.1234567']:
            self.assertEqual(server._clarity_export_timestamp(value),'')

    def test_canonical_prozorro_status_has_no_emoji(self):
        for value in ['Активний','Призупинений','Неактивний','Ще не в реєстрі']:
            self.assertEqual(server._clarity_prozorro_status('🟢 '+value),value)

    def test_monitoring_serialization_preserves_code_current_name_quoting_and_time(self):
        source=[dict(supplier_code='00400001',supplier_name='ТОВ «Синтетичний, тест»\nДруга лінія',
                     edr_status='Зареєстровано',manager_name='Керівник',
                     verification_date='2026-10-29T16:50:47.123+02:00',prozorro_status='Активний',
                     latest_application_date='2026-10-28',verification_officer='Перевіряла УО')]
        original=json.dumps(source,ensure_ascii=False)
        with patch.object(server,'_edr_monitoring_rows',return_value=source):
            raw=server.edr_monitoring_export_csv(['00400001','missing'])
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        rows=parse(raw);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['Код ЄДРПОУ'],'00400001')
        self.assertEqual(rows[0]['Стара Назва'],source[0]['supplier_name'])
        self.assertEqual(rows[0][FIRST[4]],'2026-10-29 16:50:47.123+02:00')
        self.assertEqual(rows[0]['УО'],'Перевіряла УО')
        self.assertEqual(json.dumps(source,ensure_ascii=False),original)


class ClarityEntrypointTests(unittest.TestCase):
    def test_final_historical_cli_uses_exact_parent_context(self):
        root=Path(os.environ['PQM_RELEASE_SOURCE_ROOT'])
        result=subprocess.run([sys.executable,'-B',str(root/'validation/sandbox_clarity_history.py'),
                               '-v','test_google_writer_integrated_candidate_integrity_v28'],
                              capture_output=True,text=True,encoding='utf-8',timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 6 tests',result.stderr)
        self.assertNotIn('Traceback',result.stderr)


class ClarityHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(server.__file__).parent
        with patch.dict(os.environ),patch.object(socket,'getfqdn',socket.getfqdn),patch.object(sys,'path',list(sys.path)):
            spec=importlib.util.spec_from_file_location('_clarity_web_fixture',root/'validation/web_smoke.py')
            cls.web=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.web)
        cls.addClassCleanup(cls.web.TEMP.cleanup)
        cls.folder=tempfile.TemporaryDirectory(prefix='pqm-clarity-export-');cls.addClassCleanup(cls.folder.cleanup)
        cls.enterClassContext(patch.object(server,'DB_PATH',Path(cls.folder.name)/'synthetic.sqlite3'))
        cls.enterClassContext(patch.object(server,'AUTH_ENABLED',True))
        with patch.dict(os.environ,{'PQM_RELEASE_SCHEMA_ONLY':'1'}):cls.web.fixture()
        cls.codes=['00400001','00000007','3012345678']
        with server.db() as con:
            edr_sync_v2.migrate(con)
            for n,code in enumerate(cls.codes):
                sid='csv-'+str(n);q='q-'+sid
                subject={'tenderers':[{'identifier':{'id':code,'scheme':'UA-IPN' if len(code)==10 else 'UA-EDR'},'address':{'countryName':'Україна'},'legalForm':'individual_entrepreneur' if len(code)==10 else 'legal_entity'}]}
                con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,qualification_id,raw_json,synced_at) VALUES(?,'framework',?,'Older application name','2026-10-28T09:10:11+02:00',?,?,'fixture')",(sid,code,q,json.dumps(subject)))
                con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,'framework',?,'active','{}','fixture')",(q,sid))
                con.execute("INSERT INTO application_fields(submission_id,protocol_officer,manager_name) VALUES(?,'Assigned application officer','Application director')",(sid,))
                con.execute("INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,milestones_json,raw_json,synced_at) VALUES(?,'framework',?,?,'active','[]','{}','fixture')",('rc-'+sid,q,code))
                con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,manager_name,edr_status,edr_checked_at,edr_officer,source_sheet,synced_at) VALUES(?,?,'Current director','Зареєстровано','2026-10-01','Old profile officer',?,'fixture')",(code,'СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК '+str(n),'ФОП' if len(code)==10 else 'ЮО'))
                con.execute("INSERT INTO supplier_edr_verification_events(supplier_code,event_type,occurred_at,officer,source,snapshot_hash,snapshot_json,created_at) VALUES(?,'manual_edr',?,'Latest EDR officer','Synthetic','fixture-hash','{}','fixture')",(code,'2026-10-29T16:50:47.123+02:00'))
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);cls.addClassCleanup(cls.http.server_close)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        def stop():cls.http.shutdown();cls.thread.join(5)
        cls.addClassCleanup(stop)

    def request(self,path,method='GET',payload=None,role='admin'):
        import http.client
        client=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=20)
        headers={'Authorization':'Basic '+base64.b64encode(('fixture-'+role+':'+self.web.PASSWORD).encode()).decode()}
        if payload is not None:headers['Content-Type']='application/json'
        client.request(method,path,json.dumps(payload) if payload is not None else None,headers)
        response=client.getresponse();raw=response.read();headers=dict(response.getheaders());status=response.status;client.close()
        return status,raw,headers

    def test_post_download_selected_has_exact_eight_columns_and_paired_officer(self):
        status,raw,headers=self.request('/api/supplier-edr-export','POST',{'supplier_codes':['00400001']})
        self.assertEqual(status,200,raw[:1000]);rows=parse(raw)
        self.assertEqual(list(rows[0]),FIRST+EXTRA)
        self.assertEqual(rows[0]['Код ЄДРПОУ'],'00400001')
        self.assertEqual(rows[0]['Стара Назва'],'СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК 0')
        self.assertEqual(rows[0]['УО'],'Latest EDR officer')
        self.assertEqual(rows[0]['Дата останньої заявки'],'2026-10-28')
        self.assertEqual(rows[0][FIRST[4]],'2026-10-29 16:50:47.123+02:00')
        self.assertIn('text/csv',headers['Content-Type']);self.assertIn('filename*=',headers['Content-Disposition'])
        self.assertEqual(int(headers['Content-Length']),len(raw))

    def test_get_monitoring_download_matches_current_filtered_population(self):
        status,listing,_=self.request('/api/edr-monitoring?search=00400001')
        self.assertEqual(status,200,listing[:1000]);listing=json.loads(listing)
        status,raw,_=self.request('/api/supplier-edr-export?type=ALL&view=edr_monitoring&search=00400001')
        self.assertEqual(status,200,raw[:1000]);rows=parse(raw)
        self.assertEqual([row['Код ЄДРПОУ'] for row in rows],[row['supplier_code'] for row in listing['items']])
        self.assertEqual(rows[0]['УО'],listing['items'][0]['verification_officer'])
        self.assertEqual(rows[0][FIRST[4]],listing['items'][0]['verification_date'].replace('T',' '))

    def test_selected_empty_and_limit_validation_unchanged(self):
        self.assertEqual(self.request('/api/supplier-edr-export','POST',{'supplier_codes':[]})[0],400)
        self.assertEqual(self.request('/api/supplier-edr-export','POST',{'supplier_codes':[str(10000000+n) for n in range(5001)]})[0],400)

    def test_current_population_and_original_first_four_fields_match_baseline(self):
        from validation.sandbox_clarity_history import historical_server
        baseline=historical_server(Path(os.environ['PQM_RELEASE_SOURCE_ROOT']))
        cases=[('ALL',{}),('ЮО',{}),('ФОП',{}),('ALL',{'supplier_codes':{'00400001'},'selected_mode':True}),
               ('ALL',{'prozorro_statuses':{'Неактивний'}}),
               ('ALL',{'verification_from':'2026-10-29','verification_to':'2026-10-29'}),
               ('ALL',{'freshness_bucket':'not_checked'})]
        with patch.object(baseline,'DB_PATH',server.DB_PATH):
            for sheet,filters in cases:
                old=baseline.build_supplier_edr_export_rows(sheet,filters=filters)
                new=server.build_supplier_edr_export_rows(sheet,filters=filters)
                self.assertEqual([row[FIRST[0]] for row in new],[row[FIRST[0]] for row in old])
                self.assertEqual([{key:row[key] for key in FIRST[:4]} for row in new],
                                 [{key:row[key] for key in FIRST[:4]} for row in old])

    def test_current_export_reflects_latest_edr_change_without_manual_cache_reset(self):
        code='00400001'
        try:
            with server.db() as con:
                con.execute("UPDATE supplier_edr_profiles SET full_name='СИНТЕТИЧНА АКТУАЛЬНА НАЗВА' WHERE supplier_code=?",(code,))
                con.execute("UPDATE supplier_edr_verification_events SET occurred_at='2026-10-29T17:01:02.456+02:00',officer='New EDR officer' WHERE supplier_code=?",(code,))
            for method,path,payload in [('POST','/api/supplier-edr-export',{'supplier_codes':[code]}),
                                        ('GET','/api/supplier-edr-export?type=ALL&view=edr_monitoring&search='+code,None)]:
                status,raw,_=self.request(path,method,payload)
                self.assertEqual(status,200,raw[:500]);row=parse(raw)[0]
                self.assertEqual(row['Стара Назва'],'СИНТЕТИЧНА АКТУАЛЬНА НАЗВА')
                self.assertEqual(row['УО'],'New EDR officer')
                self.assertEqual(row[FIRST[4]],'2026-10-29 17:01:02.456+02:00')
        finally:
            with server.db() as con:
                con.execute("UPDATE supplier_edr_profiles SET full_name='СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК 0' WHERE supplier_code=?",(code,))
                con.execute("UPDATE supplier_edr_verification_events SET occurred_at='2026-10-29T16:50:47.123+02:00',officer='Latest EDR officer' WHERE supplier_code=?",(code,))

    def test_read_only_export_has_no_external_requests_or_database_writes(self):
        with server.db() as con:before='\n'.join(con.iterdump())
        with patch.object(server,'api_get',side_effect=AssertionError('No external requests')),patch.object(server,'_google_sheet_values',side_effect=AssertionError('No Google reads')):
            self.assertEqual(self.request('/api/supplier-edr-export','POST',{'supplier_codes':self.codes})[0],200)
            self.assertEqual(self.request('/api/supplier-edr-export?type=ALL&view=edr_monitoring&search=00400001')[0],200)
        with server.db() as con:after='\n'.join(con.iterdump())
        self.assertEqual(before,after)

    def test_viewer_export_still_forbidden(self):
        status,_,_=self.request('/api/supplier-edr-export','POST',{'supplier_codes':['00400001']},role='viewer')
        self.assertEqual(status,403)
