"""Only CRLF -> LF is permitted; all meaningful bytes remain protected."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import zipfile
import messages_integrity
import messages_crlf_test_integrity as crlf_guard
from test_sandbox_nazk_appeals_stabilization_v3_integrity import historical_text_bytes
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT=guard.ROOT


class HistoricalTextLineEndingTests(unittest.TestCase):
    def test_same_content_accepts_lf_crlf_and_mixed_endings(self):
        original=b'{\n  "status": "original",\n  "count": 1\n}\n'
        for variant in [original,original.replace(b'\n',b'\r\n'),original.replace(b'\n',b'\r\n',1)]:
            with self.subTest(variant=variant):
                self.assertEqual(historical_text_bytes(original),historical_text_bytes(variant))

    def test_single_content_byte_is_rejected(self):
        content=b'{\r\n  "key": "value"\r\n}\r\n'
        changed=content.replace(b'value',b'Value')
        self.assertNotEqual(historical_text_bytes(content),historical_text_bytes(changed))

    def test_added_or_deleted_character_is_rejected(self):
        content=b'{\n  "key": "value"\n}\n'
        for changed in [content+b' ',content[:-1],content.replace(b'value',b'values'),content.replace(b'value',b'valu')]:
            with self.subTest(changed=changed):
                self.assertNotEqual(historical_text_bytes(content),historical_text_bytes(changed))

    def test_changed_json_value_is_rejected(self):
        content=b'{\n  "enabled": true, "count": 1\n}\n'
        for changed in [content.replace(b'true',b'false'),content.replace(b'1',b'2')]:
            with self.subTest(changed=changed):
                self.assertNotEqual(historical_text_bytes(content),historical_text_bytes(changed))

    def test_spaces_key_order_case_and_bare_cr_are_not_normalized(self):
        content=b'{\n  "a": 1, "b": 2\n}\n'
        alternatives=[b'{\n "a": 1, "b": 2\n}\n',b'{\n  "b": 2, "a": 1\n}\n',
                      b'{\n  "A": 1, "b": 2\n}\n',content.replace(b'\n',b'\r')]
        for changed in alternatives:
            with self.subTest(changed=changed):
                self.assertNotEqual(historical_text_bytes(content),historical_text_bytes(changed))

    def test_real_failed_fixture_diff_is_exactly_line_endings(self):
        name='test_sandbox_nazk_appeals_stabilization_v2.json'
        with zipfile.ZipFile(ROOT/'validation/fixtures/messages_parent_c246edef.zip') as archive:
            fixture=archive.read(name)
        current=(ROOT/name).read_bytes()
        self.assertEqual(historical_text_bytes(fixture),historical_text_bytes(current))
        self.assertEqual(hashlib.sha256(historical_text_bytes(current)).hexdigest(),
                         '61512ea36622fd1173704c5123212471d4830831798af9be6595514cb381014c')
        changed=fixture.replace(b'variant_id',b'variant_iD',1)
        self.assertNotEqual(historical_text_bytes(changed),historical_text_bytes(current))

    def test_published_manifests_and_protected_product_entries_remain_immutable(self):
        contracts=guard.load_contracts()
        previous,current=contracts[-2:]
        self.assertEqual(previous['variant_id'],messages_integrity.VARIANT)
        self.assertEqual(current['variant_id'],crlf_guard.VARIANT)
        self.assertEqual(previous['protected_files'],current['protected_files'])
        self.assertEqual(messages_integrity.MANIFEST_SHA,
                         '1bb3bdbe99b3f041b6bc6dbdfaf4768a5b21f75c84d7f4a6a61351726a731143')
        for name,expected in current['historical_manifest_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),expected,name)
        parent=crlf_guard.parent_tree(ROOT)
        spec=importlib.util.spec_from_file_location('immutable_messages_v1_guard',
            parent/'validation/local_release_20260911/sandbox_protocol_integrity_variant.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        self.assertEqual(old.load_contracts(),contracts[:-1])
        self.assertTrue(guard.manifest_tree_matches(previous,parent))
        self.assertTrue(guard.manifest_tree_matches(current))


if __name__=='__main__':unittest.main()
