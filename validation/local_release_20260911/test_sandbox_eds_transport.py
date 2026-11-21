"""Confinement tests: no external EDS calls and no live data."""
import json
import os
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import sandbox_eds as eds
import sandbox_runtime as policy

class EdsPolicyTests(unittest.TestCase):
    def test_only_exact_verify_endpoint_and_schema(self):
        body=json.dumps({'sign_url':'https://documents.prozorro.gov.ua/synthetic'}).encode()
        self.assertEqual(eds.validate_verification_request(eds.ENDPOINT,'POST',body),'https://documents.prozorro.gov.ua/synthetic')
        for url,method,data in [(eds.ENDPOINT,'GET',body),('https://example.test/','POST',body),
                                (eds.ENDPOINT+'?extra','POST',body),(eds.ENDPOINT,'POST',b'{"sign":"other"}')]:
            with self.assertRaises((RuntimeError,ValueError)):eds.validate_verification_request(url,method,data)

    def test_signature_url_rejects_credentials_http_private_ip_and_fragments(self):
        with patch.object(eds.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            for url in ['http://example.test/sign','https://u:p@example.test/sign','https://127.0.0.1/sign','https://example.test/sign#fragment']:
                with self.assertRaises(ValueError):eds.validate_sign_url(url)
        with patch.object(eds.socket,'getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            self.assertEqual(eds.validate_sign_url('https://documents.prozorro.gov.ua/synthetic'),'https://documents.prozorro.gov.ua/synthetic')

    def test_unscoped_and_changed_process_are_denied(self):
        expected=(('node','--import','file:///approved.mjs','adapter.mjs'),'fixture',{'PATH':'fixed'})
        with patch.dict(os.environ,{'PQM_SANDBOX':'1'}):
            self.assertFalse(eds.permitted_process('subprocess.Popen',('node',list(expected[0]),'fixture',expected[2])))
            eds._launch.expected=expected
            try:
                self.assertTrue(eds.permitted_process('subprocess.Popen',('node',list(expected[0]),'fixture',expected[2])))
                for args in [('node',['node','-e','arbitrary'],'fixture',expected[2]),
                             ('node',list(expected[0]),'elsewhere',expected[2]),
                             ('node',list(expected[0]),'fixture',{'PATH':'inherited','SECRET':'no'})]:
                    self.assertFalse(eds.permitted_process('subprocess.Popen',args))
                self.assertFalse(eds.permitted_process('os.system',('node',list(expected[0]),'fixture',expected[2])))
            finally:eds._launch.expected=None

    def test_python_global_guard_still_denies_arbitrary_child(self):
        with patch.dict(os.environ,{'PQM_SANDBOX':'1'}):
            with self.assertRaisesRegex(RuntimeError,'child processes'):policy.outbound_audit('subprocess.Popen',('node',['node','-e','arbitrary'],None,{}))

    def test_network_scope_is_cleared_on_open_failure(self):
        request=eds.urllib.request.Request(eds.ENDPOINT,data=b'{"sign_url":"https://example.test/sign"}',method='POST')
        with patch.object(eds.urllib.request,'build_opener') as build:
            build.return_value.open.side_effect=TimeoutError('synthetic')
            with self.assertRaises(TimeoutError):
                with eds.verification_open(request,1):pass
        self.assertFalse(policy._egress.active);self.assertFalse(policy._egress.eds_verify);self.assertFalse(policy._egress.addresses)

    def test_parallel_child_admission_is_capped(self):
        self.assertTrue(eds._SLOTS.acquire(False));self.assertTrue(eds._SLOTS.acquire(False))
        try:self.assertFalse(eds._SLOTS.acquire(False))
        finally:eds._SLOTS.release();eds._SLOTS.release()

    def test_real_official_adapter_with_fake_service_and_real_guard(self):
        import sys
        root=Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
        result=subprocess.run([sys.executable,'-B',str(root/'validation/sandbox_eds_roundtrip.py')],
                              cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('3 roundtrips PASS',result.stdout)

if __name__=='__main__':unittest.main()
