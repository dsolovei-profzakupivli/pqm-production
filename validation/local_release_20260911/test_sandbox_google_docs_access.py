"""SANDBOX Google Docs access checks are exact-ID and read-only."""
import io
import json
import unittest
import urllib.request
from unittest.mock import patch

import sandbox_google_docs_access as docs
import sandbox_runtime


class SandboxGoogleDocsAccessTests(unittest.TestCase):
    def test_only_four_metadata_reads_are_allowed(self):
        with patch.dict(sandbox_runtime.os.environ, {"PQM_SANDBOX": "1"}):
            for file_id in (*docs.TEMPLATES.values(), docs.SANDBOX_FOLDER_ID):
                self.assertEqual(sandbox_runtime.validate_google_request(
                    docs.metadata_url(file_id), "GET"), sandbox_runtime.GOOGLE_DRIVE_HOST)
            for url, method in (
                (docs.metadata_url(docs.SANDBOX_FOLDER_ID), "POST"),
                (docs.metadata_url(docs.SANDBOX_FOLDER_ID).replace(
                    docs.SANDBOX_FOLDER_ID, docs.WORKING_FOLDER_ID), "GET"),
                (docs.metadata_url(docs.WARNING_TEMPLATE_ID).replace("fields=", "alt=media&fields="), "GET"),
                (f"https://www.googleapis.com/drive/v3/files/{docs.WORKING_FOLDER_ID}/copy?fields=id%2Cname%2CmimeType%2Cparents", "POST"),
                (docs.metadata_url(docs.WARNING_TEMPLATE_ID).replace(docs.WARNING_TEMPLATE_ID, "PROD"), "GET"),
            ):
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    sandbox_runtime.validate_google_request(url, method)

    def test_capability_check_reads_all_sources_without_creating_documents(self):
        seen = []

        def opener(request, timeout):
            self.assertEqual(request.get_method(), "GET")
            seen.append(request.full_url)
            file_id = request.full_url.split("/files/", 1)[1].split("?", 1)[0]
            is_folder = file_id == docs.SANDBOX_FOLDER_ID
            return io.BytesIO(json.dumps({
                "id": file_id,
                "mimeType": ("application/vnd.google-apps.folder" if is_folder
                             else "application/vnd.google-apps.document"),
                "isAppAuthorized": True,
                "capabilities": {"canAddChildren": True} if is_folder else {"canCopy": True},
            }).encode())

        result = docs.check_access("test-only-token", opener)
        self.assertEqual(len(seen), 4)
        self.assertEqual(result["documents_created"], 0)
        self.assertEqual(result["destination_folder_id"], docs.SANDBOX_FOLDER_ID)
        self.assertFalse(result["production_folder_used"])
        self.assertTrue(result["ready_for_single_generation_test"])

    def test_access_check_fails_closed_on_missing_capability(self):
        def opener(request, timeout):
            file_id = request.full_url.split("/files/", 1)[1].split("?", 1)[0]
            return io.BytesIO(json.dumps({"id": file_id,
                "mimeType": "application/vnd.google-apps.document",
                "isAppAuthorized": True,
                "capabilities": {"canCopy": False}}).encode())
        with self.assertRaises(PermissionError):
            docs.check_access("test-only-token", opener)

    def test_picker_grant_requires_exact_resource_identity_and_app_authorization(self):
        def opener(request, timeout):
            file_id = request.full_url.split("/files/", 1)[1].split("?", 1)[0]
            return io.BytesIO(json.dumps({"id": file_id,
                "mimeType": "application/vnd.google-apps.document",
                "isAppAuthorized": False,
                "capabilities": {"canCopy": True}}).encode())
        with self.assertRaises(PermissionError):
            docs.check_resource("test-only-token", opener, "warning")
        with self.assertRaises(PermissionError):
            docs.check_resource("test-only-token", opener, "arbitrary")
        with self.assertRaises(PermissionError):
            docs.metadata_url(docs.WORKING_FOLDER_ID)

    def test_picker_grant_never_trusts_returned_wrong_id_or_mime(self):
        for item in ({"id": "wrong", "isAppAuthorized": True,
                      "mimeType": "application/vnd.google-apps.document", "capabilities": {"canCopy": True}},
                     {"id": docs.WARNING_TEMPLATE_ID, "isAppAuthorized": True,
                      "mimeType": "application/vnd.google-apps.folder", "capabilities": {"canCopy": True}}):
            with self.subTest(item=item), self.assertRaises(PermissionError):
                docs.check_resource("test-only-token", lambda request, timeout: io.BytesIO(
                    json.dumps(item).encode()), "warning")

    def test_copy_and_edit_guard_never_target_original_or_working_folder(self):
        copy_url = f"https://www.googleapis.com/drive/v3/files/{docs.WARNING_TEMPLATE_ID}/copy?fields=id%2Cname%2CmimeType%2Cparents"
        generated = "generated_sandbox_document_id_123"
        with patch.dict(sandbox_runtime.os.environ, {"PQM_SANDBOX": "1"}):
            self.assertEqual(sandbox_runtime.validate_google_request(copy_url, "POST"),
                             sandbox_runtime.GOOGLE_DRIVE_HOST)
            good = urllib.request.Request(copy_url, method="POST", data=json.dumps({
                "name": "test", "parents": [docs.SANDBOX_FOLDER_ID]}).encode())
            sandbox_runtime.validate_google_document_body(good)
            bad = urllib.request.Request(copy_url, method="POST", data=json.dumps({
                "name": "test", "parents": [docs.WORKING_FOLDER_ID]}).encode())
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_google_document_body(bad)
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_google_request(
                    f"https://docs.googleapis.com/v1/documents/{docs.WARNING_TEMPLATE_ID}:batchUpdate",
                    "POST", generated_document_id=docs.WARNING_TEMPLATE_ID)
            self.assertEqual(sandbox_runtime.validate_google_request(
                f"https://docs.googleapis.com/v1/documents/{generated}:batchUpdate",
                "POST", generated_document_id=generated), sandbox_runtime.GOOGLE_DOCS_HOST)


if __name__ == "__main__":
    unittest.main()
