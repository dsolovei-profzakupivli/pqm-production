import shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import template_runtime as t,schema_catalog

class AtomicReplacementTests(unittest.TestCase):
    @staticmethod
    def replacement_fixtures(folder):
        root=Path(__file__).parent
        source=root/'data'/'templates'/'nazk_supplier_request.docx'
        candidate=Path(folder)/'candidate.docx'
        shutil.copy2(source,candidate)
        # A ZIP comment changes the candidate hash without changing DOCX content.
        # This keeps the atomic-write test hermetic and exercises a real replace.
        with ZipFile(candidate,'a') as archive:archive.comment=b'atomic-replace-test'
        return candidate,source.read_bytes()

    def test_registered_template_is_migrated_once_without_overwriting_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder)/'runtime'
            source=Path(folder)/'source'
            source.mkdir()
            (source/'nazk_supplier_request.docx').write_bytes(b'current-source-version')
            with patch.object(t,'TEMPLATE_ROOT',runtime),patch.object(t,'SOURCE_TEMPLATE_ROOT',source):
                first=t.template_path('nazk_supplier_request')
                self.assertEqual(first.read_bytes(),b'current-source-version')
                first.write_bytes(b'operator-version')
                self.assertEqual(t.template_path('nazk_supplier_request').read_bytes(),b'operator-version')

    def test_failure_rollback_success_repeat(self):
        schema=schema_catalog.catalog('data/pqm.sqlite3')
        with tempfile.TemporaryDirectory() as folder,patch.object(t,'TEMPLATE_ROOT',Path(folder)):
            candidate,original=self.replacement_fixtures(folder)
            target=Path(folder)/'nazk_supplier_request.docx';target.write_bytes(original)
            d={}
            with patch.object(t.os,'replace',side_effect=PermissionError('locked')):
                with patch.object(t.time,'sleep'):
                    with self.assertRaises(PermissionError):t.replace('nazk_supplier_request',candidate,schema,diagnostics=d)
            self.assertEqual(d['failure_stage'],'atomic_replace');self.assertEqual(target.read_bytes(),original)
            self.assertEqual(list((Path(folder)/'_versions').iterdir()),[])
            def fail(path):raise RuntimeError('audit unavailable')
            with self.assertRaises(RuntimeError):t.replace('nazk_supplier_request',candidate,schema,finalize=fail)
            self.assertEqual(target.read_bytes(),original)
            for _ in range(2):
                t.replace('nazk_supplier_request',candidate,schema)
                self.assertEqual(target.read_bytes(),candidate.read_bytes())
            bad=Path(folder)/'bad.docx';bad.write_bytes(b'not a docx')
            with self.assertRaises(ValueError):t.replace('nazk_supplier_request',bad,schema)
            self.assertEqual(target.read_bytes(),candidate.read_bytes())

    def test_transient_windows_lock_is_retried_without_partial_state(self):
        schema=schema_catalog.catalog('data/pqm.sqlite3')
        with tempfile.TemporaryDirectory() as folder,patch.object(t,'TEMPLATE_ROOT',Path(folder)):
            candidate,original=self.replacement_fixtures(folder)
            target=Path(folder)/'nazk_supplier_request.docx';target.write_bytes(original)
            real_replace=t.os.replace;calls=0
            def transient(source,destination):
                nonlocal calls
                calls+=1
                if calls<3:raise PermissionError(5,'Access is denied',str(destination))
                return real_replace(source,destination)
            with patch.object(t.os,'replace',side_effect=transient),patch.object(t.time,'sleep'):
                t.replace('nazk_supplier_request',candidate,schema)
            self.assertEqual(calls,3)
            self.assertEqual(target.read_bytes(),candidate.read_bytes())
            self.assertEqual(list(Path(folder).glob('*.tmp.docx')),[])

if __name__=='__main__':unittest.main()
