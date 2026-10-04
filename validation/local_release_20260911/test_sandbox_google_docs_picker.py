"""Fixed-ID SANDBOX Picker setup never broadens scopes or creates documents."""
import unittest
from unittest.mock import patch

import server
import sandbox_google_docs_access as docs


class SandboxGoogleDocsPickerTests(unittest.TestCase):
    def test_config_uses_existing_scope_and_exact_ids(self):
        with patch.object(server, "SANDBOX_MODE", True), \
             patch.dict(server.os.environ, {"PQM_SANDBOX_PICKER_API_KEY": "test-browser-key"}), \
             patch.object(server, "_google_oauth_client", return_value={"client_id": "785118226581-test.apps.googleusercontent.com"}), \
             patch.object(server, "_google_oauth_token", return_value={"scope": docs.DRIVE_FILE_SCOPE}), \
             patch.object(server, "_google_access_token", return_value="test-short-lived-token"):
            result = server.sandbox_docs_picker_config()
        self.assertEqual(result["app_id"], "785118226581")
        self.assertEqual(result["resources"], {**docs.TEMPLATES, "destination": docs.SANDBOX_FOLDER_ID})
        self.assertNotIn(docs.WORKING_FOLDER_ID, result["resources"].values())
        self.assertEqual(result["access_token"], "test-short-lived-token")
        self.assertNotIn("refresh_token", result)

    def test_config_fails_closed_on_environment_key_project_or_scope(self):
        common = [patch.object(server, "SANDBOX_MODE", True),
                  patch.object(server, "_google_access_token", return_value="test-token")]
        for candidate in common: candidate.start()
        try:
            cases = [({}, {"client_id": "785118226581-test"}, {"scope": docs.DRIVE_FILE_SCOPE}),
                     ({"PQM_SANDBOX_PICKER_API_KEY": "key"}, {"client_id": "wrong-test"}, {"scope": docs.DRIVE_FILE_SCOPE}),
                     ({"PQM_SANDBOX_PICKER_API_KEY": "key"}, {"client_id": "785118226581-test"}, {"scope": "spreadsheets"})]
            for environment, client, token in cases:
                with self.subTest(environment=environment, client=client, token=token), \
                     patch.dict(server.os.environ, environment, clear=True), \
                     patch.object(server, "_google_oauth_client", return_value=client), \
                     patch.object(server, "_google_oauth_token", return_value=token), \
                     self.assertRaises((RuntimeError, PermissionError)):
                    server.sandbox_docs_picker_config()
        finally:
            for candidate in reversed(common): candidate.stop()
        with patch.object(server, "SANDBOX_MODE", False), self.assertRaises(PermissionError):
            server.sandbox_docs_picker_config()


if __name__ == "__main__":
    unittest.main()
