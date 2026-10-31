"""Full additive product-tree guard; historical manifests are not changed."""
import hashlib,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).parent
MANIFEST='supplier_classification_contract_v1.json'
PINNED_SHA256='dd8e2d375b0ea0c6d7fb46715d33170f55eaa842c74535d12d2f00fe39da46d2'
BINARY={'.zip','.docx','.pdf','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2','.ttf','.exe','.dll','.sqlite3'}
def digest(relative,data):
    raw=data if Path(relative).suffix.lower() in BINARY else data.replace(b'\r\n',b'\n')
    return hashlib.sha256(raw).hexdigest()
def validate(manifest,actual):
    return set(actual)==set(manifest['files']) and all(actual[p]==v for p,v in manifest['files'].items())
class SupplierClassificationIntegrityTests(unittest.TestCase):
    def setUp(self):
        raw=(ROOT/MANIFEST).read_bytes().replace(b'\r\n',b'\n')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),PINNED_SHA256)
        self.manifest=json.loads(raw)
        self.actual={p:digest(p,(ROOT/p).read_bytes()) for p in self.manifest['files']}
    def test_exact_additive_tree(self):
        self.assertEqual(self.manifest['parent'],'6b9830b010ddd2339e316775572d88c630cdfb6b')
        self.assertTrue(validate(self.manifest,self.actual),[p for p,h in self.actual.items() if h!=self.manifest['files'][p]])
    def test_partial_or_extra_hashes_never_match(self):
        smaller=dict(self.actual);smaller.pop(next(iter(smaller)));self.assertFalse(validate(self.manifest,smaller))
        larger={**self.actual,'arbitrary-new.py':'0'*64};self.assertFalse(validate(self.manifest,larger))
    def test_one_byte_mutations_in_changed_and_independent_components_rejected(self):
        for p in self.manifest['mutation_targets']:
            data=(ROOT/p).read_bytes();self.assertTrue(data)
            for altered in [bytes([data[0]^1])+data[1:],data+b'X',data[:-1]]:
                actual=dict(self.actual);actual[p]=digest(p,altered)
                with self.subTest(path=p,size=len(altered)):self.assertFalse(validate(self.manifest,actual))
    def test_historical_contracts_have_unchanged_hashes(self):
        self.assertTrue(self.manifest['historical_manifests'])
        for p,expected in self.manifest['historical_manifests'].items():
            self.assertEqual(self.actual[p],expected,p)
    def test_semantic_country_or_reviewed_form_mutation_rejected(self):
        for p in ['supplier_country_catalog.json','supplier_classification.py']:
            raw=(ROOT/p).read_bytes();actual=dict(self.actual);actual[p]=digest(p,raw.replace(b'UA',b'PL',1) if b'UA' in raw else raw.replace(b'legal_entity',b'unknown',1))
            self.assertFalse(validate(self.manifest,actual))
