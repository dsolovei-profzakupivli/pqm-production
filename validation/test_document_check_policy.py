"""UI-002 policy/count regressions. Disposable fixtures; never live data/services."""
import copy
import json
import unittest
from unittest.mock import patch

import server
from validation.local_release_20260911 import test_document_signature_verification as signatures
from validation.local_release_20260911 import test_sandbox_functionality_repair as functionality


class NewAnalysisTests(unittest.TestCase):
    setUp = signatures.SignatureAnalysisTests.setUp
    tearDown = signatures.SignatureAnalysisTests.tearDown
    seed = signatures.SignatureAnalysisTests.seed

    def test_new_mvs_has_seven_checks_no_seal_download_or_verification(self):
        documents = [{'id': 'pdf', 'title': 'mvs.pdf', 'url': 'https://example.test/pdf'},
                     {'id': 'seal', 'title': 'mvs.p7s', 'url': 'https://example.test/seal'}]
        self.seed(documents=documents)
        selection = {'0': ['mvs'], '1': ['mvs_signature']}
        before = copy.deepcopy(selection)
        with patch.object(server, 'download_document', return_value=b'%PDF synthetic') as download, \
             patch.object(server, 'pdf_text', return_value='Синтетичний текст витягу'), \
             patch.object(server, '_needs_ukrainian_ocr', return_value=False), \
             patch.object(server, 'pdf_has_unreadable_pages', return_value=False), \
             patch.object(server, 'verify_prozorro_eds') as verify:
            result = server.analyze_application_documents('s', selection)
        self.assertEqual(selection, before)
        self.assertEqual([call.args[0]['id'] for call in download.call_args_list], ['pdf'])
        verify.assert_not_called()
        self.assertEqual(result['document_check_policy_version'], 2)
        self.assertEqual(result['selected_categories'], ['mvs'])
        self.assertEqual(len(result['checks']), 7)
        self.assertNotIn('mvs_seal', [item['key'] for item in result['checks']])
        self.assertEqual(result['counts'], server.document_check_status(result['checks'])[0])

    def test_legacy_seal_only_selection_performs_no_download_or_signature_request(self):
        self.seed()
        with patch.object(server, 'download_document') as download, \
             patch.object(server, 'verify_prozorro_eds') as verify:
            result = server.analyze_application_documents('s', {'0': ['mvs_signature']})
        download.assert_not_called()
        verify.assert_not_called()
        self.assertEqual(result['checks'], [])
        self.assertEqual(sum(result['counts'].values()), 0)

    def test_signature_algorithm_and_selected_source_remain_unchanged(self):
        self.seed()
        evidence = signatures.SignatureAnalysisTests.eds()
        with patch.object(server, 'download_document', return_value=b'bytes'), \
             patch.object(server, 'verify_prozorro_eds', return_value=evidence) as verify:
            result = server.analyze_application_documents('s', {'0': ['signature', 'mvs_signature']})
        verify.assert_called_once_with('https://example.test/sign.p7s')
        self.assertEqual(result['signature']['technical_status'], 'success')
        self.assertEqual(result['signature']['code_comparison'], 'match')
        self.assertEqual(result['checked_signature_document']['index'], 0)
        self.assertEqual(len(result['checks']), 9)


class PolicyCountsTests(unittest.TestCase):
    def test_experience_never_affects_new_totals_for_any_severity(self):
        for status in ['ok', 'warning', 'error', 'neutral']:
            checks = [{'key': 'signer', 'status': 'ok'}, {'key': 'contract_experience', 'status': status}]
            self.assertEqual(server.document_check_status(server.document_check_summary_checks(checks, 2))[0],
                             {'ok': 1, 'warning': 0, 'error': 0, 'neutral': 0})
            self.assertEqual(server.document_check_summary_checks(checks), checks)

    def test_new_mvs_indicator_ignores_seal_without_rewriting_historical_category(self):
        old = self.legacy()
        old['category_results']['mvs'] = self.category([{'key': 'mvs_extract', 'status': 'ok'}, {'key': 'mvs_seal', 'status': 'error'}])
        before = copy.deepcopy(old)
        self.assertEqual(server.document_check_category_summaries(old)['mvs'], 'error')
        new = dict(old, document_check_policy_version=2)
        self.assertEqual(server.document_check_category_summaries(new)['mvs'], 'ok')
        self.assertEqual(old, before)
        self.assertEqual(new['category_results'], old['category_results'])

    def category(self, checks):
        counts, status = server.document_check_status(checks)
        return {'checks': checks, 'counts': counts, 'status': status, 'checked_at': 'original'}

    def legacy(self):
        categories = {
            'signature': self.category([{'key': 'signer', 'status': 'ok'}]),
            'mvs': self.category([{'key': 'mvs_person', 'status': 'error'}, {'key': 'mvs_seal', 'status': 'warning'}]),
            'experience': self.category([{'key': 'contract_experience', 'status': 'neutral', 'search_status': 'none'}]),
        }
        checks = [item for category in categories.values() for item in category['checks']]
        return {'category_results': categories, 'checks': checks,
                'counts': server.document_check_status(checks)[0], 'mvs_seal': {'technical_status': 'legacy'},
                'signature': {'signer': 'original'}, 'document_fingerprints': {'signature': 'sig', 'mvs': 'mvs'}}

    def test_historical_seal_checks_and_counts_read_without_mutating_input(self):
        old = self.legacy()
        before = copy.deepcopy(old)
        self.assertEqual(server.document_result_for_current_sources('s', old), old)
        visible = server.current_document_check_result(old)
        self.assertEqual(visible['counts'], old['counts'])
        self.assertEqual(visible['counts']['warning'], 1)
        self.assertEqual(old, before)

    def test_signature_only_keeps_historical_mvs_and_experience_but_new_totals_exclude_seal(self):
        old = self.legacy()
        before = copy.deepcopy(old)
        result = server.merge_document_check_results(old, {
            'document_check_policy_version': 2, 'selected_categories': ['signature'],
            'checks': [{'key': 'signer', 'status': 'ok', 'detail': 'new signature'}]})
        for category in ['mvs', 'experience']:
            self.assertEqual(result['category_results'][category], before['category_results'][category])
        self.assertEqual(result['mvs_seal'], old['mvs_seal'])
        self.assertEqual(result['counts'], {'ok': 1, 'warning': 0, 'error': 1, 'neutral': 0})
        self.assertEqual(server.current_document_check_result(result)['counts'], result['counts'])
        self.assertEqual(result['category_results']['mvs']['counts']['warning'], 1)
        self.assertEqual(old, before)

    def test_mvs_only_replaces_mvs_and_preserves_signature_experience_and_fingerprint(self):
        old = self.legacy()
        result = server.merge_document_check_results(old, {
            'document_check_policy_version': 2, 'selected_categories': ['mvs'],
            'checks': [{'key': 'mvs_person', 'status': 'ok'}],
            'document_fingerprints': {'mvs': 'new'}})
        for category in ['signature', 'experience']:
            self.assertEqual(result['category_results'][category], old['category_results'][category])
        self.assertEqual(result['signature'], old['signature'])
        self.assertEqual(result['document_fingerprints'], {'signature': 'sig', 'mvs': 'new'})
        self.assertNotIn('mvs_seal', [c['key'] for c in result['checks']])
        self.assertEqual(result['counts']['warning'], 0)

    def test_legacy_merge_without_policy_retains_original_seal_count(self):
        old = self.legacy()
        result = server.merge_document_check_results(old, {'selected_categories': ['signature'],
                    'checks': [{'key': 'signer', 'status': 'ok'}]})
        self.assertEqual(result['counts'], old['counts'])

    def test_experience_update_keeps_new_policy_and_other_categories(self):
        old = self.legacy()
        old['document_check_policy_version'] = 2
        result = server.merge_document_check_results(old, {'selected_categories': ['experience'],
             'checks': [{'key': 'contract_experience', 'status': 'neutral', 'search_status': 'found'}]})
        self.assertEqual(result['document_check_policy_version'], 2)
        self.assertEqual(result['counts']['warning'], 0)
        for category in ['signature', 'mvs']:
            self.assertEqual(result['category_results'][category], old['category_results'][category])


class PartialStorageTests(unittest.TestCase):
    setUp = functionality.SandboxFunctionalityTests.setUp
    seed = functionality.SandboxFunctionalityTests.seed

    def test_manual_mvs_repeat_preserves_unselected_categories_in_stored_json(self):
        self.seed()
        old = PolicyCountsTests().legacy()
        saved = server._store_document_check_result('s', old, 'fixture')
        current = {'document_check_policy_version': 2, 'selected_categories': ['mvs'],
                   'checks': [{'key': 'mvs_person', 'status': 'ok'}]}
        result = server._store_document_check_result('s', current, 'fixture', require_editable=True)
        for category in ['signature', 'experience']:
            self.assertEqual(result['category_results'][category], saved['category_results'][category])
        with server.db() as con:
            stored = json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual(stored, result)
        self.assertEqual(stored['counts']['warning'], 0)
