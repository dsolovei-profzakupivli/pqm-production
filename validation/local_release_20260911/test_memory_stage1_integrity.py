"""Additive current-tree checks; parent exact-tree contracts remain pinned."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from validation.memory_stage1_history import accepted_stage1_root

ROOT = accepted_stage1_root(Path.cwd())
MANIFEST = ROOT / 'validation/memory_stage1_integrity.json'
MANIFEST_SHA256 = '4b4543ae2a901a1711e489e0447e88e5a86ceb33098240d04735b198491b662c'


def load_manifest():
    content = MANIFEST.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise AssertionError('Memory stage1 manifest changed')
    return json.loads(content)


def digest(content, relative):
    if Path(relative).suffix in {'.py', '.js', '.json', '.cjs'}:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


class MemoryStage1IntegrityTests(unittest.TestCase):
    def test_exact_files_and_negative_byte_mutations(self):
        manifest = load_manifest()
        self.assertEqual(manifest['baseline'], 'a53234f1d4a4c32032bc0b1c311b1a279ab17e22')
        for relative, expected in manifest['files'].items():
            with self.subTest(path=relative):
                content = (ROOT / relative).read_bytes()
                self.assertEqual(digest(content, relative), expected)
                self.assertNotEqual(digest(content + b'X', relative), expected)
                self.assertNotEqual(digest(content[:-1], relative), expected)
                changed = bytearray(content)
                changed[len(changed) // 2] ^= 1
                self.assertNotEqual(digest(changed, relative), expected)

    def test_sync_and_edr_projection_functions_are_unchanged(self):
        manifest = load_manifest()
        text = (ROOT / 'server.py').read_text(encoding='utf-8-sig')
        tree = ast.parse(text)
        for name, expected in manifest['unchanged_server_functions'].items():
            node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
            body = ast.get_source_segment(text, node).encode()
            self.assertEqual(hashlib.sha256(body).hexdigest(), expected, name)


if __name__ == '__main__':
    unittest.main()
