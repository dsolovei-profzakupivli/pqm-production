"""Current follow-up contract, separate from immutable accepted stage1 v1."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path.cwd()
MANIFEST_SHA256 = '7ccb52587b2b8ec0e96d89a22e2534bba31787b37d03371a6be97ae5fab852cf'


def sha(content, relative):
    if Path(relative).suffix in {'.py', '.js', '.cjs', '.json'}:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


class MemoryFollowupIntegrity(unittest.TestCase):
    def manifest(self):
        content = (ROOT / 'validation/memory_stage1_followup_integrity_v2.json').read_bytes()
        self.assertEqual(sha(content, 'manifest.json'), MANIFEST_SHA256)
        return json.loads(content)

    def test_exact_current_files_and_mutations(self):
        manifest = self.manifest()
        for name, expected in manifest['files'].items():
            with self.subTest(path=name):
                data = (ROOT / name).read_bytes()
                self.assertEqual(sha(data, name), expected)
                self.assertNotEqual(sha(data + b'X', name), expected)
                self.assertNotEqual(sha(data[:-1], name), expected)
                changed = bytearray(data)
                changed[len(changed) // 2] ^= 1
                self.assertNotEqual(sha(changed, name), expected)

    def test_business_schema_crypto_sync_edr_and_persistence_functions_unchanged(self):
        manifest = self.manifest()
        source = (ROOT / 'server.py').read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        for name, expected in manifest['unchanged_server_functions'].items():
            node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(), expected, name)


if __name__ == '__main__':
    unittest.main()
