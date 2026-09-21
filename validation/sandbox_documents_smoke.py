"""Explicit document routes, preserved permissions and real isolated Linux PDF."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import sandbox_smoke as base
import sandbox_documents as documents


class Policy(unittest.TestCase):
    def test_allowlist(self):
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_DOCUMENTS':'1'}):
            for path in ('/api/protocol/readiness','/api/protocol/generate'):
                self.assertTrue(documents.route_allowed('POST',path))
            for path in ('/api/sync','/api/operational-tasks/rebuild',
                         '/api/protocol/formed/123/cancel','/api/violation-reports/a/protocol/generate'):
                self.assertFalse(documents.route_allowed('POST',path))
            self.assertFalse(documents.permitted_process('subprocess.Popen',('sh',['sh'],None,None)))
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_DOCUMENTS':'0'}):
            self.assertFalse(documents.route_allowed('POST','/api/protocol/generate'))

    def test_real_worker_network_denial_and_pdf(self):
        if sys.platform != 'linux':
            self.skipTest('Actual seccomp/LibreOffice assertion runs in Linux container gate')
        script = '''
import hashlib, os, socket, sys
from pathlib import Path
from docx import Document
import sandbox_runtime as sandbox
import sandbox_pdf_worker as worker
import protocol_pdf
root=Path(sys.argv[1]); protocols=root/'protocols'; protocols.mkdir()
source=protocols/'synthetic.docx'
doc=Document();doc.add_paragraph('PQM SANDBOX synthetic PDF');doc.save(source)
digest=hashlib.sha256(source.read_bytes()).hexdigest()
os.environ.update(sandbox.POLICY,PQM_SANDBOX_LOCAL_FIXTURE='1',PQM_SANDBOX_DOCUMENTS='1',
                  PQM_DATA_DIR=str(root),PQM_DB_PATH=str(root/'pqm_sandbox.sqlite3'))
sandbox.install_outbound_guard()
result=protocol_pdf.ensure_pdf(source,protocols/'synthetic.pdf')
assert result.read_bytes().startswith(b'%PDF-')
assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
assert protocol_pdf.ensure_pdf(source,protocols/'synthetic.pdf')==result
os.environ['PQM_SANDBOX_DOCUMENTS']='0'
try: protocol_pdf.ensure_pdf(source,protocols/'synthetic.pdf')
except RuntimeError: pass
else: raise AssertionError('Disabled documents reused cached PDF')
os.environ['PQM_SANDBOX_DOCUMENTS']='1'
try: sandbox.sandbox_documents.export_pdf(source,root/'escaped.pdf')
except RuntimeError: pass
else: raise AssertionError('Output escaped owned protocols')
try:
    import subprocess
    subprocess.run(['sh','-c','true'])
except RuntimeError:
    pass
else:
    raise AssertionError('Arbitrary child process permitted')
worker.deny_network()
for family in (socket.AF_INET,socket.AF_INET6):
    try: socket.socket(family)
    except PermissionError: pass
    else: raise AssertionError('Internet socket permitted')
with socket.socket(socket.AF_UNIX): pass
'''
        with tempfile.TemporaryDirectory(prefix='pqm-pdf-test-') as folder:
            result = subprocess.run([sys.executable,'-B','-c',script,folder],
                                    cwd=base.ROOT, capture_output=True,text=True,timeout=150)
            self.assertEqual(0,result.returncode,result.stderr[-3000:])


class HTTP(base.SandboxHTTP):
    EXTRA_ENV = {'PQM_SANDBOX_DOCUMENTS':'1'}

    def test_21_readiness_rbac_and_generation(self):
        self.assertEqual(403,self.request('/api/protocol/generate','viewer','POST',{})[0])
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            con.execute("UPDATE application_fields SET protocol_number='SANDBOX-PDF-TEST',protocol_date='2026-09-21',manager_name='Тестовий керівник',protocol_decision='admit',protocol_remarks='Без зауважень',compliance_status='approved' WHERE submission_id='sandbox-pending'")
        payload={'protocol_number':'SANDBOX-PDF-TEST'}
        status, result, _ = self.request('/api/protocol/readiness','admin','POST',payload)
        self.assertEqual(200,status,result)
        self.assertTrue(result['ready'],result)
        status,result,_=self.request('/api/protocol/generate','admin','POST',payload)
        self.assertEqual(200,status,result)
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            self.assertEqual(1,con.execute('SELECT count(*) FROM formed_protocols').fetchone()[0])
            self.assertEqual(0,con.execute('SELECT count(*) FROM operational_tasks').fetchone()[0])
            self.assertEqual(0,con.execute('SELECT count(*) FROM supplier_nazk_checks').fetchone()[0])


if __name__=='__main__': unittest.main(verbosity=2)
