import unittest
import io
import json
import urllib.parse

import sandbox_appeal_google_docs as docs
import sandbox_google_docs_access as access


def values():
    return {"report_id": "UA-2026-123", "protocol_number": "17",
            "customer_short_name": "Замовник", "supplier_short_name": "Постачальник",
            "supplier_code": "00123456", "rejection_date": "",
            "protocol_date": "03.10.2026", "refusal_outgoing_number": "55"}


class SandboxAppealDocsTests(unittest.TestCase):
    def test_exact_native_doc_filenames_and_destination(self):
        for protocol_type, marker in (("warning", "П"),
                                      ("decline_p49_1_2", "В"),
                                      ("decline_p49_3", "В")):
            with self.subTest(protocol_type=protocol_type):
                self.assertEqual(docs.document_name(protocol_type, values()),
                    f"UA-2026-123_17_{marker}_Замовник_Постачальник (00123456)")
                plan = docs.prepare_replacements(protocol_type, values(), "{{protocol_date}}")
                self.assertEqual(plan["template_id"], access.TEMPLATES[protocol_type])
                self.assertEqual(plan["destination_folder_id"], access.SANDBOX_FOLDER_ID)
                self.assertNotIn(".", plan["name"].split(" ")[-1])

    def test_short_names_are_required_without_fallback(self):
        for field in ("customer_short_name", "supplier_short_name"):
            incomplete = values(); incomplete[field] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                docs.prepare_replacements("warning", incomplete, "{{ report_id }}")

    def test_decline_1_2_without_rejection_date_uses_dash(self):
        plan = docs.prepare_replacements("decline_p49_1_2", values(),
            "{{ rejection_date }} {{ refusal outgoing number }}")
        self.assertEqual(plan["replacements"]["{{ rejection_date }}"], "—")
        self.assertEqual(plan["replacements"]["{{ refusal outgoing number }}"], "55")

    def test_required_rejection_scenario_fails_before_copy(self):
        with self.assertRaisesRegex(ValueError, "Rejection date"):
            docs.prepare_replacements("decline_p49_1_2", values(),
                                      "{{ rejection_date }}", rejection_required=True)

    def test_p49_3_never_adds_rejection_date(self):
        with self.assertRaisesRegex(ValueError, "must not acquire"):
            docs.prepare_replacements("decline_p49_3", values(), "{{ rejection_date }}")

    def test_unknown_placeholder_fails_preflight(self):
        with self.assertRaisesRegex(ValueError, "lack source values"):
            docs.prepare_replacements("warning", values(), "{{ unknown_field }}")

    def test_cyrillic_and_placeholder_request(self):
        plan = docs.prepare_replacements("warning", values(), "{{ customer_short_name }}")
        self.assertEqual(docs.replace_requests(plan["replacements"]), [{
            "replaceAllText": {"containsText": {"text": "{{ customer_short_name }}",
                                                "matchCase": True}, "replaceText": "Замовник"}}])
        docs.verify_rendered_text("Замовник")
        with self.assertRaises(RuntimeError):
            docs.verify_rendered_text("{{ customer_short_name }}")

    def test_native_copy_replaces_placeholders_and_never_edits_template(self):
        source_id = access.TEMPLATES["decline_p49_1_2"]
        generated_id = "sandbox_generated_doc_1234567890"
        source_text = "{{ report_id }} · {{ rejection_date }} · {{ customer_short_name }}"
        result_text = "UA-2026-123 · — · Замовник"
        requests = []; copied_ids = []
        def opener(request, timeout, generated_document_id=None):
            requests.append((request.full_url, request.get_method(), request.data))
            path = urllib.parse.urlsplit(request.full_url).path
            if request.get_method() == "POST" and path.endswith("/copy"):
                return io.BytesIO(json.dumps({"id": generated_id,
                    "mimeType": docs.DOCUMENT_MIME,
                    "parents": [access.SANDBOX_FOLDER_ID]}).encode())
            if request.get_method() == "POST":
                payload = json.loads(request.data)
                self.assertEqual(len(payload["requests"]), 3)
                return io.BytesIO(json.dumps({"replies": [{}] * 3}).encode())
            source = path.endswith(source_id)
            text = source_text if source else result_text
            return io.BytesIO(json.dumps({"documentId": source_id if source else generated_id,
                "revisionId": "source-rev" if source else "generated-rev",
                "tabs": [{"documentTab": {"body": {"content": [{"paragraph": {
                    "elements": [{"textRun": {"content": text}}]}}]}}}]}).encode())
        result = docs.create_document("decline_p49_1_2", values(), "test-token", opener,
            lambda copied_id, plan: copied_ids.append(copied_id))
        self.assertEqual(copied_ids, [generated_id])
        self.assertEqual(result["document_id"], generated_id)
        self.assertEqual(result["placeholders_replaced"], 3)
        writes = [(url, body) for url, method, body in requests if method == "POST"]
        self.assertEqual(len(writes), 2)
        self.assertIn(source_id + "/copy?fields=", writes[0][0])
        self.assertIn(access.SANDBOX_FOLDER_ID, writes[0][1].decode())
        self.assertIn(generated_id + ":batchUpdate", writes[1][0])
        self.assertFalse(any(source_id + ":batchUpdate" in url for url, _, _ in requests))


if __name__ == "__main__":
    unittest.main()
