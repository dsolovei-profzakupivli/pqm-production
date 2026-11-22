"""Compare UI grouping with the real pure server function without importing server/DB."""
import ast
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocumentSourceIndexes(unittest.TestCase):
    def test_frontend_indexes_match_server_grouping_with_duplicates_and_missing_keys(self):
        tree = ast.parse((ROOT / 'server.py').read_text(encoding='utf8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'grouped_application_documents')
        namespace = {'json': json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'pure_document_grouping', 'exec'), namespace)
        doc = lambda key, title: {'id': key, 'url': '/files/' + key, 'title': title}
        archive, signature, pdf = doc('z', 'a.zip'), doc('s', 'sign.p7s'), doc('p', 'mvs.pdf')
        cases = [([], []), ([archive, {}, signature, signature, pdf], [signature, doc('d', 'decision.pdf')]),
                 ([{'id': 'only-id', 'title': 'sign.p7s'}, pdf], [pdf]),
                 ([signature, {**signature, 'url': '/files/new-version'}], [])]
        script = "const ui=require('./application_documents_ui.js');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(ui.groups(JSON.parse(s)))));"
        for supplier, decision in cases:
            with self.subTest(supplier=supplier, decision=decision):
                server = namespace['grouped_application_documents'](
                    json.dumps(supplier), json.dumps(decision), None, 'pending', None)
                run = subprocess.run(['node', '-e', script], cwd=ROOT, input=json.dumps({
                    'supplierDocuments': supplier, 'decisionDocuments': decision}),
                    text=True, capture_output=True, check=True)
                actual = json.loads(run.stdout)
                offset = 0
                for group in ['supplier', 'decision']:
                    self.assertEqual([entry['document'] for entry in actual[group]], server[group])
                    self.assertEqual([entry['index'] for entry in actual[group]],
                                     list(range(offset, offset + len(server[group]))))
                    offset += len(server[group])


if __name__ == '__main__':
    unittest.main()
