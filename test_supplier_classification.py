"""Subject-nature regression on synthetic data only; no external services."""
import json
import sqlite3
import unittest
import subprocess
from pathlib import Path
from contextlib import nullcontext
from unittest import mock
import supplier_classification as sc

CASES=['СР919350','СР 918414','НВ411323','МЮ397338','КР935355','кн015121','ВО599107']
def org(code,country='Україна',name='ФОП Синтетичний',**extra):
    return {'identifier':{'id':code,'scheme':'UA-EDR','legalName':name},'name':name,
            'address':{'countryName':country},**extra}

class SupplierClassificationTests(unittest.TestCase):
    def test_planner_regressions(self):
        script=Path(__file__).parent/'validation/supplier_classification_planner.cjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_seven_reviewed_fop_exact_identifiers(self):
        for code in CASES:
            x=sc.classify(code,org(code));self.assertEqual(x['entity_type'],'individual_entrepreneur');self.assertEqual(x['supplier_code'],code);self.assertEqual(x['target_sheet'],'ФОП')
    def test_ordinary_legal_and_rnokpp_and_idcard(self):
        for code,name,kind in [('00123456','ТОВ «Тест»','legal_entity'),('0012345678','ФОП Тест','individual_entrepreneur'),('001234567','ФОП Тест','individual_entrepreneur')]:
            self.assertEqual(sc.classify(code,org(code,name=name))['entity_type'],kind)
    def test_nine_digit_joint_activity_is_not_fop(self):
        x=sc.classify('541645372',org('541645372',name='Договір про спільну діяльність'))
        self.assertEqual(x['entity_type'],'legal_entity');self.assertEqual(x['target_sheet'],'ЮО');self.assertEqual(x['subject_nature'],'not_fop')
    def test_branch_representative_and_other_nine_digit_entities(self):
        for name in ['Філія підприємства','Представництво підприємства','ТОВ «Тест»']:
            x=sc.classify('009227724',org('009227724',name=name));self.assertEqual(x['target_sheet'],'ЮО')
    def test_identifier_length_never_overrides_established_nature(self):
        self.assertEqual(sc.classify('00123456',org('00123456'))['target_sheet'],'ФОП')
        self.assertEqual(sc.classify('0012345678',org('0012345678',name='ТОВ «Тест»'))['target_sheet'],'ЮО')
    def test_code_alone_never_proves_nature(self):
        for code in ['00123456','001234567','0012345678','АБ 000123']:
            x=sc.classify(code,org(code,name='Невизначений учасник'));self.assertEqual(x['entity_type'],'unknown');self.assertFalse(x['append_allowed'])
    def test_unknown_country_no_scheme_or_name_fallback(self):
        for country in ['',None,'Невідомо']:
            x=sc.classify('0012345678',org('0012345678',country));self.assertFalse(x['append_allowed']);self.assertEqual(x['entity_type'],'unknown')
    def test_foreign_entity_never_appended(self):
        for country in ['Республіка Польща','Сполучені Штати Америки','PL']:
            x=sc.classify('00123456',org('00123456',country));self.assertEqual(x['classification_status'],'nonresident');self.assertIsNone(x['target_sheet'])
    def test_conflicting_country_is_review(self):
        o=org('00123456');o['address']['countryCode']='PL';self.assertEqual(sc.classify('00123456',o)['classification_status'],'conflict')
    def test_explicit_legal_form_conflict_not_ignored(self):
        x=sc.classify('001234567',org('001234567',legalForm='legal_entity'))
        self.assertEqual(x['classification_reason'],'subject_nature_evidence_conflict');self.assertFalse(x['append_allowed'])
    def test_established_nature_does_not_hide_primary_contradiction(self):
        x=sc.classify('541645372',org('541645372',name='ФОП Тест',legalForm='joint_activity'))
        self.assertEqual(x['classification_status'],'conflict')
    def test_unsupported_legal_form_is_blocked(self):
        self.assertFalse(sc.classify('00123456',org('00123456',legalForm={'code':'unmapped'}))['append_allowed'])
    def test_literal_text_is_unchanged(self):
        for code in ['  АБ 000001  ','кн015121','AB000001','001234567']:
            self.assertEqual(sc.classify(code,org(code))['supplier_code'],code)
    def test_primary_identifier_mismatch_blocks(self):
        self.assertEqual(sc.classify('СР 918414',org('СР918414'))['classification_status'],'conflict')
    def test_nontext_empty_identifier_not_coerced(self):
        for code in [None,123456789,'','   ']:self.assertFalse(sc.classify(code,org(code))['append_allowed'])
    def test_declared_names_are_anchored(self):
        self.assertEqual(sc.classify('00123456',org('00123456',name='ТОВ «ФОП СЕРВІС»'))['target_sheet'],'ЮО')
        self.assertFalse(sc.classify('00123456',org('00123456',name='ФОПСЕРВІС'))['append_allowed'])
    def test_ambiguous_abbreviations_do_not_establish_nature(self):
        for name in ['ПП Синтетичний','ФГ Синтетичний']:
            self.assertFalse(sc.classify('00123456',org('00123456',name=name))['append_allowed'])
    def test_index_get_reads_only_and_refreshes_synthetic_memory(self):
        with sqlite3.connect(':memory:') as con:
            con.executescript('CREATE TABLE submissions(id TEXT,supplier_code TEXT,raw_json TEXT,date_published TEXT)')
            con.execute('INSERT INTO submissions VALUES(?,?,?,?)',('s','001234567',json.dumps({'tenderers':[org('001234567')]}),'2026-10-01'))
            before=con.total_changes;idx=sc.build_index(con);self.assertEqual(con.total_changes,before);self.assertEqual(idx['001234567']['target_sheet'],'ФОП')
            con.execute('UPDATE submissions SET raw_json=?',(json.dumps({'tenderers':[org('001234567',name='ТОВ Тест')]}),))
            self.assertEqual(sc.build_index(con)['001234567']['target_sheet'],'ЮО')

class SupplierClassificationReadModelTests(unittest.TestCase):
    def setUp(self):
        # Import only under the existing release runner's disposable test root.
        import server
        self.server=server
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        with server.db() as seed:seed.backup(self.con)
        self.patch=mock.patch.object(server,'db',lambda:nullcontext(self.con));self.patch.start();self.addCleanup(self.patch.stop)
        self.con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES('type-f','TYPE-TEST','Типи','00000000-0','active','{}','fixture')")
        self.add('type-fop','СР 918414','ФОП Тест')
        self.add('type-other','541645372','Договір про спільну діяльність')
        self.add('type-foreign','FOREIGN 01','ТОВ Тест','Республіка Польща')
        self.add('type-unknown','001234567','Невідомий учасник')
        self.con.commit();server.EDR_MONITORING_CACHE.update(fingerprint=None,rows=[])
    def add(self,sid,code,name,country='Україна'):
        raw=json.dumps({'tenderers':[org(code,country,name)]},ensure_ascii=False)
        self.con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,status,qualification_id,raw_json,synced_at) VALUES(?,'type-f',?,?,'2026-10-01','complete',?,?,'fixture')",(sid,code,name,'q-'+sid,raw))
        self.con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,raw_json,synced_at) VALUES(?,'type-f',?,'active','2026-10-01','{}','fixture')",('q-'+sid,sid))
        self.con.execute("INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES(?,?,1,'fixture')",(code,name))
    def test_edr_list_and_filter_use_primary_nature(self):
        with mock.patch.object(self.server,'_edr_monitoring_revision',return_value='classification-test'):
            rows=self.server._edr_monitoring_rows()
        rows=[r for r in rows if r['supplier_code'] in {'СР 918414','541645372','FOREIGN 01','001234567'}]
        self.assertEqual({r['supplier_code'] for r in self.server._filter_edr_monitoring_rows(rows,{'entity_type':['individual_entrepreneur']})},{'СР 918414'})
        self.assertEqual({r['supplier_code'] for r in self.server._filter_edr_monitoring_rows(rows,{'entity_type':['legal_entity']})},{'541645372'})
    def test_clarity_export_keeps_literal_code(self):
        with mock.patch.object(self.server,'_edr_monitoring_revision',return_value='classification-export-test'):
            payload=self.server.edr_monitoring_export_csv({'СР 918414'})
        self.assertIn('СР 918414',payload.decode('utf-8-sig'))
    def test_registry_sql_filter_and_payload_agree(self):
        listing=self.server.list_qualified_suppliers({'entity_type':['individual_entrepreneur'],'size':['100']},connection=self.con)
        self.assertEqual({r['code'] for r in listing['items']},{'СР 918414'})
        self.assertTrue(all(r['entity_type']=='individual_entrepreneur' for r in listing['items']))
    def test_api_classifier_country_is_shared_and_readonly(self):
        import supplier_registry_integration as integration
        before=self.con.total_changes
        items={r['supplier_code']:r for r in integration.full_registry(self.con)['items']}
        self.assertEqual(items['СР 918414']['target_sheet'],'ФОП')
        self.assertEqual(items['541645372']['target_sheet'],'ЮО')
        self.assertFalse(items['FOREIGN 01']['append_allowed']);self.assertEqual(self.con.total_changes,before)

if __name__=='__main__':unittest.main()
