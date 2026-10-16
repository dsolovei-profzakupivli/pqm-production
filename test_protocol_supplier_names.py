"""Name provenance must describe, never reprioritize or gate, protocol values."""
import copy,itertools,subprocess,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import server,protocol_supplier_names


class ProtocolNameTests(unittest.TestCase):
    def resolve(self,item):return protocol_supplier_names.resolve(item,server.normalize_document_name)

    def test_edr_names_are_distinct_from_qualification_and_report(self):
        item={'supplier_verified':{'full_name':'Повна ЄДР','short_name':'Коротка ЄДР'},
              'defendant_name':'Звернення','submission_supplier_name':'Кваліфікаційна заявка'}
        n=self.resolve(item)
        self.assertEqual(n['full_name']['value'],'Повна ЄДР');self.assertEqual(n['short_name']['value'],'Коротка ЄДР')
        self.assertTrue(all(n[k]['source']=='edr' for k in ('full_name','short_name','filename_name')))
        self.assertFalse(n['uses_fallback'])

    def test_no_edr_uses_defendants_not_qualification_submission(self):
        n=self.resolve({'defendant_name':'ІЗ ЗВЕРНЕННЯ','submission_supplier_name':'НЕ ЗВІДСИ'})
        for key in ('full_name','short_name','filename_name'):
            self.assertEqual(n[key]['value'],'ІЗ ЗВЕРНЕННЯ')
            self.assertEqual(n[key]['source'],'prozorro_violation')
            self.assertEqual(n[key]['source_label'],'Зі звернення Prozorro')
            self.assertEqual(n[key]['source_path'],'defendants[0]')

    def test_partial_sources_and_filename_priority_remain_separate(self):
        n=self.resolve({'supplier_verified':{'full_name':'Повна ЄДР'},'defendant_name':'Із звернення'})
        self.assertEqual(n['full_name']['source'],'edr');self.assertEqual(n['short_name']['value'],'Повна ЄДР')
        self.assertEqual(n['filename_name']['value'],'Із звернення');self.assertTrue(n['uses_fallback'])
        n=self.resolve({'supplier_verified':{'short_name':'Коротка ЄДР'},'defendant_name':'Із звернення'})
        self.assertEqual(n['full_name']['source'],'prozorro_violation');self.assertEqual(n['short_name']['source'],'edr')

    def test_exact_legacy_selection_matrix_including_whitespace(self):
        for full,short,report in itertools.product((None,'','  ','Повна "ЄДР"'),(None,'',' ','Коротка ЄДР'),('','Із "звернення"')):
            item={'supplier_verified':{'full_name':full,'short_name':short},'defendant_name':report}
            n=self.resolve(item)
            old_full=server.normalize_document_name(full or report or '')
            old_short=server.normalize_document_name(short or old_full)
            old_filename=next((str(v).strip() for v in (short,report) if v is not None and str(v).strip()),'')
            self.assertEqual([n[k]['value'] for k in ('full_name','short_name','filename_name')],[old_full,old_short,old_filename])

    def test_missing_names_do_not_use_qualification_or_manual_payload(self):
        n=self.resolve({'submission_supplier_name':'Заявка','manual_supplier_name':'Непогоджена зміна пріоритетів'})
        self.assertEqual(n['full_name']['source'],'missing');self.assertEqual(n['full_name']['value'],'')

    def item(self):
        return {'id':'fixture','report_id':'UA-D-2026-10-06-000002','reason':'contractBreach',
            'author_name':'Замовник','author_code':'11111111','defendant_name':'Зі звернення',
            'defendant_code':'22222222','description':'Опис','defendant_statements':[],
            'deadline_control':{'supplier_ready':True},
            'procurement_context':{'available':True,'winner_selected_at':'2026-09-28',
                'tender_date_published':'2026-09-28','day_5_shifted':True,'rejection_present':True,
                'rejection_date':'2026-10-06','rejection_title':'Підстава','rejected_before_deadline':False},
            'review':{'internal_decision':'warning','assigned_officer':'УО','protocol_number':'1',
                'protocol_date':'2026-10-16','decision_justification':'Збережений текст'}}

    def test_no_edr_no_google_row_does_not_block_readiness(self):
        with patch.object(server,'violation_protocol_declensions',return_value=[]):
            gate=server.violation_protocol_readiness(self.item())
        self.assertTrue(gate['ready'],gate['reasons'])

    def test_existing_required_requisites_still_block(self):
        for field in ('protocol_number','protocol_date','decision_justification','assigned_officer'):
            item=self.item();item['review'][field]=''
            with patch.object(server,'violation_protocol_declensions',return_value=[]):
                self.assertFalse(server.violation_protocol_readiness(item)['ready'],field)
        item=self.item();item['deadline_control']['supplier_ready']=False
        with patch.object(server,'violation_protocol_declensions',return_value=[]):
            self.assertFalse(server.violation_protocol_readiness(item)['ready'])

    def test_prepared_document_names_match_display_and_no_history_writes(self):
        item=self.item();item['supplier_verified']={'full_name':'Повна ЄДР'};before=copy.deepcopy(item)
        with patch.object(server,'require_local_violation_report_owned'),patch.object(server,'require_owned_violation_report'), \
             patch.object(server,'violation_report_detail',return_value=item), \
             patch.object(server,'violation_protocol_declensions',return_value=[]), \
             patch.object(server,'_resolve_violation_protocol_metadata',return_value={}), \
             patch.object(server,'db',side_effect=AssertionError('Unexpected DB write/read')), \
             patch.object(server,'build_violation_protocol_docx',side_effect=AssertionError('Historical document touched')), \
             patch.object(server,'decline_name',side_effect=lambda value,entity,case:SimpleNamespace(value=value,status='resolved',source='fixture',original=value,entity_type=entity)):
            result=server.generate_violation_protocol('fixture',{},prepare_only=True)
        display=self.resolve(item)
        self.assertEqual(result['values']['supplier_name'],display['full_name']['value'])
        self.assertEqual(result['values']['supplier_short_name'],display['short_name']['value'])
        self.assertIn('Зі звернення',result['metadata']['protocol_download']['filename'])
        self.assertEqual(item,before)

    def test_ui_provenance_and_generation_are_not_gated_by_fallback(self):
        root=Path(__file__).parent
        result=subprocess.run(['node','validation/protocol_supplier_names_ui.cjs'],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
