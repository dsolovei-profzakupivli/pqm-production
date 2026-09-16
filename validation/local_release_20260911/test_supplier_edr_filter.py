import re
import sqlite3
import unittest
from unittest.mock import patch
import server
import edr_sync_v2


class SupplierEdrFilterTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.create_function('DIGITS',1,lambda v:re.sub(r'\D','',v or ''))
        self.con.create_function('CASEFOLD',1,lambda v:(v or '').casefold())
        self.con.create_function('NORMALIZE_NAME',1,lambda v:(v or '').casefold())
        source=sqlite3.connect('file:data/pqm.sqlite3?mode=ro',uri=True)
        try:
            for sql, in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"):
                self.con.execute(sql)
        finally:source.close()
        for code in ('3038301896','30067771'):
            self.add_current_contract(code)
            self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,qualifications_count,refreshed_at) VALUES(?,?,1,1,'fixture')",(code,'Fixture '+code))
            self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_status,edr_checked_at,synced_at) VALUES(?,'✅ Зареєстровано','03.09.2026','2026-09-09T19:58:00Z')",(code,))
        self.con.commit()
        self.mock=patch.object(server,'db',return_value=self.con);self.mock.start();self.addCleanup(self.mock.stop)
    def add_current_contract(self,code):
        self.con.execute("INSERT OR IGNORE INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES('current-filter-fixture','current-filter-fixture','active','{}','fixture')")
        self.con.execute("INSERT INTO registry_contracts(id,framework_id,supplier_code,status,raw_json,synced_at) VALUES(?,'current-filter-fixture',?,'active','{}','fixture')",('rc-'+code,code))
    def listing(self,**params):return server.list_qualified_suppliers({k:[str(v)] for k,v in params.items()})
    def test_distinct_and_current_transition_fop_and_legal(self):
        self.assertEqual(self.listing()['edr_statuses'],['✅ Зареєстровано'])
        for code in ('3038301896','30067771'):
            self.assertEqual(self.listing(search=code,edr_status='✅ Зареєстровано')['total'],1)
            # Actual importer, isolated DB and mocked read-only Sheets; no real sync.
            headers=list(edr_sync_v2.HEADERS);values=['']*len(headers)
            for key,value in {'Код ЄДРПОУ':code,'Статус в реєстрі (ЄДР)':'🔴 Припинено',
                              'Дата перевірки':'07.09.2026','УО':'Тестова УО'}.items():values[headers.index(key)]=value
            sheet=[headers,values]
            sheet_read=lambda name: sheet if name=='ЮО' else [list(edr_sync_v2.HEADERS)]
            with patch.object(server,'_google_sheet_values',side_effect=sheet_read),patch.object(server,'SUPPLIER_EDR_SHEETS',{'ФОП':'fixture','ЮО':'fixture'}),patch.object(server,'SUPPLIER_EDR_SYNC_STATE',{}),patch.object(server,'now_iso',return_value='2026-09-10T10:00:00Z'):
                fingerprint=server.supplier_edr_source_snapshot()['source_fingerprint']
                server.supplier_edr_sync_worker(fingerprint,'test')
                self.assertEqual(server.SUPPLIER_EDR_SYNC_STATE['last_result'],'completed')
            self.assertEqual(self.listing(search=code,edr_status='✅ Зареєстровано')['total'],0)
            data=self.listing(search=code,edr_status='🔴 Припинено')
            self.assertEqual(data['total'],1)
            self.assertEqual(data['items'][0]['edr_profile']['edr_checked_at'],'2026-09-07')
    def test_and_filters_empty_and_injection(self):
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано',status='active')['total'],2)
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано',status='terminated')['total'],0)
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано',search='absent')['total'],0)
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано',risk='amcu')['total'],0)
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано',dk_code='none')['total'],0)
        self.assertEqual(self.listing(edr_status="' OR 1=1 --")['total'],0)
        self.assertEqual(self.listing(edr_status='')['total'],2)
    def test_filtered_counts_and_pagination(self):
        for i in range(15):
            code=str(90000000+i)
            self.add_current_contract(code)
            self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES(?,'Page fixture',1,'fixture')",(code,))
            self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_status,synced_at) VALUES(?,'Новий статус із джерела','fixture')",(code,))
        data=self.listing(edr_status='Новий статус із джерела',size=10,page=2)
        self.assertEqual((data['total'],data['registered_total'],data['active'],data['pages'],len(data['items'])),(15,15,15,2,5))
        self.assertIn('Новий статус із джерела',data['edr_statuses'])
        self.assertTrue(all(x['edr_profile']['edr_status']=='Новий статус із джерела' for x in data['items']))
    def test_cpv_positive_intersection(self):
        self.con.execute("INSERT INTO frameworks(id,pretty_id,status,dk_code,raw_json,synced_at) VALUES('fixture','fixture','active','12345678-9','{}','fixture')")
        self.con.execute("INSERT INTO registry_contracts(id,framework_id,supplier_code,status,raw_json,synced_at) VALUES('r1','fixture','30067771','active','{}','fixture')")
        result=self.listing(edr_status='✅ Зареєстровано',status='active',dk_code='12345678-9')
        self.assertEqual([x['code'] for x in result['items']],['30067771'])
    def test_missing_snapshot_excluded_from_selected_status(self):
        self.con.execute("DELETE FROM supplier_edr_profiles WHERE supplier_code='30067771'")
        self.assertEqual(self.listing()['total'],2)
        self.assertEqual(self.listing(edr_status='✅ Зареєстровано')['total'],1)

    def test_canonical_freshness_and_verification_date_filters(self):
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,source_submission_id,source_sheet,
           source_row,changed_fields,snapshot_hash,snapshot_json,created_at)
          VALUES('30067771','google_clarity','2026-09-03','Тестова УО','Google Sheets','',
                 'ЮО',2,'[]','freshness-fixture','{}','2026-09-03T10:00:00Z')""")
        self.con.commit()
        recent=self.listing(freshness='lt30',verification_from='2026-09-01',verification_to='2026-09-04')
        self.assertEqual([row['code'] for row in recent['items']],['30067771','3038301896'])
        self.assertEqual(recent['items'][0]['edr_freshness_marker'],'🟢 <30 днів')
        self.assertEqual(recent['items'][0]['edr_verification_officer'],'Тестова УО')
        self.assertEqual(self.listing(freshness='not_checked')['total'],0)

    def test_entity_type_shared_semantics_and_intersection(self):
        self.assertEqual(self.listing(entity_type='')['total'],2)
        for kind,code in [('individual_entrepreneur','3038301896'),('legal_entity','30067771')]:
            result=self.listing(entity_type=kind,edr_status='✅ Зареєстровано',status='active',search=code)
            self.assertEqual([row['code'] for row in result['items']],[code])
            self.assertEqual((result['total'],result['active'],result['pages']),(1,1,1))
        self.assertEqual(self.listing(entity_type='legal_entity',search='3038301896')['total'],0)
        self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES('303-830-1896','Formatted',1,'fixture')")
        self.add_current_contract('303-830-1896')
        self.assertEqual(self.listing(entity_type='individual_entrepreneur')['total'],2)
        with self.assertRaises(ValueError):self.listing(entity_type='invalid')

    def test_entity_type_pagination_and_cpv(self):
        for i in range(15):
            self.add_current_contract(str(80000000+i))
            self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES(?,'Type fixture',1,'fixture')",(str(80000000+i),))
        result=self.listing(entity_type='legal_entity',size=10,page=2)
        self.assertEqual((result['total'],result['pages'],len(result['items'])),(16,2,6))
        self.test_cpv_positive_intersection()
        self.assertEqual(self.listing(entity_type='legal_entity',dk_code='12345678-9')['total'],1)
        self.assertEqual(self.listing(entity_type='individual_entrepreneur',dk_code='12345678-9')['total'],0)

    def test_clarity_export_preserves_contract_and_defaults_to_monitored_population(self):
        rows=server.build_supplier_edr_export_rows('ФОП',today=__import__('datetime').date(2026,9,15))
        self.assertEqual(len(rows),1)
        self.assertEqual(list(rows[0]),server.EDR_EXPORT_HEADERS)
        self.assertEqual(rows[0]['Код ЄДРПОУ'],'3038301896')
        self.assertEqual(server.EDR_EXPORT_HEADERS,['Код ЄДРПОУ','Стара Назва','Старий Статус','Старий ПІБ Керівника','Фактична дата перевірки ЄДР'])
        filtered=server.build_supplier_edr_export_rows('ФОП',today=__import__('datetime').date(2026,9,15),
          filters={'prozorro_statuses':{'Активний'},'freshness_bucket':'not_checked'})
        self.assertEqual([row['Код ЄДРПОУ'] for row in filtered],[])

    def test_clarity_csv_matches_real_input_shape(self):
        import csv,io
        text=server.supplier_edr_export_csv('ФОП').decode('utf-8-sig')
        parsed=list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0],server.EDR_EXPORT_HEADERS)
        self.assertTrue(all(len(row)==5 for row in parsed))
        self.assertIn(',',text.splitlines()[0])
        combined=server.supplier_edr_export_csv('ALL').decode('utf-8-sig')
        self.assertEqual(len(list(csv.DictReader(io.StringIO(combined)))),2)

    def test_last_admission_date_filter(self):
        self.con.execute("INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,date_published,documents_json,raw_json,synced_at) VALUES('admit-filter','current-filter-fixture','qa','30067771','Fixture','2026-09-05','[]','{}','fixture')")
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_decision,protocol_date,protocol_officer) VALUES('admit-filter','admit','2026-09-06','УО')")
        self.con.commit()
        self.assertEqual(self.listing(admission_from='2026-09-01',admission_to='2026-09-10')['total'],1)
        self.assertEqual(self.listing(admission_from='2026-09-07')['total'],0)

    def test_export_uses_application_manager_fallback(self):
        self.con.execute("INSERT INTO submissions(id,framework_id,qualification_id,supplier_code,supplier_name,date_published,documents_json,raw_json,synced_at) VALUES('manager-fallback','current-filter-fixture','qm','30067771','APPLICATION NAME','2026-09-05','[]','{}','fixture')")
        self.con.execute("INSERT INTO application_fields(submission_id,manager_name,protocol_decision) VALUES('manager-fallback','КЕРІВНИК ІЗ ЗАЯВКИ','admit')")
        self.con.commit()
        rows=server.build_supplier_edr_export_rows('ЮО',today=__import__('datetime').date(2026,9,15),
          filters={'supplier_codes':{'30067771'},'selected_mode':True})
        self.assertEqual(rows[0]['Старий ПІБ Керівника'],'КЕРІВНИК ІЗ ЗАЯВКИ')

    def test_filtered_code_projection_returns_all_matches_not_current_page(self):
        result=self.listing(entity_type='legal_entity',_include_codes='1',size=10,page=1)
        self.assertEqual(set(result['filtered_codes']),{'30067771'})


if __name__=='__main__':unittest.main()
