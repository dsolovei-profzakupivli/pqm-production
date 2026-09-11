import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import violation_protocol_docx as templates

class TemplateRuntimeTests(unittest.TestCase):
    def test_default_runtime_templates_are_outside_source_tree(self):
        self.assertEqual(templates.TEMPLATE_DIR, Path(templates.DATA_DIR) / "templates" / "violation_protocols")
        self.assertNotEqual(templates.TEMPLATE_DIR.resolve(), templates.PACKAGED_TEMPLATE_DIR.resolve())

    def test_all_four_templates_are_managed_and_application_validates(self):
        items=templates.template_metadata()
        self.assertEqual({'warning','decline_p49_1_2','decline_p49_3','application_protocol'},
                         {x['key'] for x in items})
        self.assertTrue(all(x['exists'] for x in items))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            paths={key:root/(key+'.docx') for key in templates.TEMPLATES}
            for key,path in paths.items():path.write_bytes(templates.TEMPLATES[key].read_bytes())
            with patch.object(templates,'TEMPLATES',paths),patch.object(templates,'TEMPLATE_DIR',root),patch.object(templates,'ensure_runtime_templates'):
                for key,path in paths.items():
                    before=path.read_bytes()
                    self.assertTrue(templates.replace_runtime_template(key,path).exists())
                    self.assertEqual(path.read_bytes(),before)

if __name__=='__main__': unittest.main()
