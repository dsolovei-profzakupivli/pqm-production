"""Portable UI callbacks plus source safety contracts; real Chromium is separate."""
import pathlib
import subprocess
import unittest


class UiFinalTests(unittest.TestCase):
    def test_task_kpi_resets_and_safe_presentation(self):
        result=subprocess.run(['node','validation/ui_final_unit.cjs'],cwd=pathlib.Path(__file__).parent,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_read_only_api_and_no_schema_management(self):
        source=(pathlib.Path(__file__).parent/'audit_reader.py').read_text(encoding='utf-8')
        self.assertIn('?mode=ro',source);self.assertIn('PRAGMA query_only=ON',source)
        for statement in ['CREATE TABLE','CREATE INDEX','ALTER TABLE','INSERT INTO','UPDATE audit_log','DELETE FROM']:
            self.assertNotIn(statement,source)
