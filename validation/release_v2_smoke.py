"""September 10 deployment contract tests, isolated from live WEB data."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import web_smoke as web
from migrations.additive import fingerprints
import navigation_settings
import template_catalog
import template_runtime

class ReleaseV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()

    def test_additive_release_twice_preserves_every_existing_business_value(self):
        with web.server.db() as con:
            fields,before=fingerprints(con)
        # Navigation is the only explicitly approved replacement seed.
        fields={k:v for k,v in fields.items() if k not in {'navigation_settings','navigation_icons'}}
        before={k:v for k,v in before.items() if k in fields}
        args=[sys.executable,str(web.ROOT/'deploy_release.py'),'--db',str(web.server.DB_PATH),'--apply-navigation']
        for _ in range(2):
            result=subprocess.run(args,env=os.environ.copy(),capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            with web.server.db() as con:
                self.assertEqual(before,fingerprints(con,fields)[1])
                self.assertEqual('ok',con.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertFalse(con.execute('PRAGMA foreign_key_check').fetchall())
        seed=json.loads((web.ROOT/'config/navigation.release.json').read_text())
        with web.server.db() as con:
            self.assertEqual(seed['navigation'],json.loads(con.execute('SELECT overrides_json FROM navigation_settings WHERE id=1').fetchone()[0]))
            for icon in seed['icons']:
                self.assertEqual((icon['name'],icon['svg']),tuple(con.execute('SELECT name,svg FROM navigation_icons WHERE icon_key=?',(icon['icon_key'],)).fetchone()))

    def test_canonical_docx_template_and_metadata_valid(self):
        schema=web.server.pqm_schema_metadata()
        fields=template_catalog.validate(template_catalog.load(),schema)
        result=template_runtime.validate_template('nazk_supplier_request',fields)
        self.assertTrue(result['can_activate_canonical'])

    def test_protocol_scope_cross_assignment_and_denials(self):
        with web.server.db() as con:
            for officer in (1,2):
                web.server.assert_protocol_scope(con,['pending'],'officer',officer)
            with self.assertRaises(PermissionError):web.server.assert_protocol_scope(con,['pending'],'viewer',None)
            with self.assertRaises(PermissionError):web.server.assert_protocol_scope(con,['pending'],'officer',99999)

if __name__=='__main__':unittest.main(verbosity=2)
