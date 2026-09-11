"""Download routing regression; no initialization, generators or real DB writes."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server


class TemplateDownloadTests(unittest.TestCase):
    def request(self, key, role='admin'):
        handler = object.__new__(server.Handler)
        handler.path = '/api/admin/templates/' + key + '/download'
        handler.command = 'GET'
        handler.headers = {}
        handler.auth_user = 'fixture'
        handler.auth_role = role
        handler.auth_officer_id = None
        handler.wfile = io.BytesIO()
        headers = {}
        status = []
        handler.send_response = status.append
        handler.send_header = lambda k, v: headers.update({k: v})
        handler.end_headers = lambda: None
        # Keep the real permission/role gates; isolate identity and database only.
        with patch.object(handler, '_authorize', return_value=True), \
             patch.object(server, 'db', side_effect=lambda: contextlib.nullcontext(None)), \
             patch.object(server.auth_access, 'effective', return_value={
                 'active': True, 'permissions': {'admin.read': role == 'admin', 'admin.manage': role == 'admin'}}):
            handler.do_GET()
        return status[0], headers, handler.wfile.getvalue()

    def test_all_existing_templates_bytes_and_headers(self):
        for key in ('warning', 'decline_p49_1_2', 'decline_p49_3', 'application_protocol'):
            with self.subTest(key=key):
                path = server.TEMPLATES[key]
                before = path.read_bytes()
                status, headers, body = self.request(key)
                self.assertEqual(status, 200)
                self.assertEqual(body, before)
                self.assertEqual(headers['Content-Type'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                self.assertEqual(headers['Content-Disposition'], f'attachment; filename="{path.name}"')
                self.assertEqual(int(headers['Content-Length']), len(before))
                self.assertEqual(path.read_bytes(), before)

    def test_missing_key_and_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(server.TEMPLATES, {'missing_file': Path(folder)/'absent.docx'}):
                for key in ('missing_file', 'unknown_template'):
                    status, _, body = self.request(key)
                    self.assertEqual(status, 404)
                    self.assertEqual(json.loads(body)['error'], 'Шаблон не знайдено')

    def test_invalid_keys(self):
        for key in ('..%2Fwarning', '%22bad', 'UPPER', 'a'*65):
            status, _, body = self.request(key)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)['code'], 'invalid_template_key')

    def test_non_admin_for_all_templates(self):
        for role in ('viewer', 'officer'):
            for key in server.TEMPLATES:
                self.assertEqual(self.request(key, role)[0], 403)


if __name__ == '__main__':
    unittest.main()
