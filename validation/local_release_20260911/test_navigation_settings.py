import sqlite3, unittest
from pathlib import Path
import auth_access, navigation_settings

class NavigationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');navigation_settings.migrate(self.con)
    def tearDown(self): self.con.close()
    def test_global_roundtrip_and_reset(self):
        saved=navigation_settings.save(self.con,{'historyNav':{'iconKey':'audit','displayMode':'icon-text','order':3,'visible':False}},'Admin')
        self.assertEqual(saved['overrides']['historyNav']['iconKey'],'audit')
        self.assertEqual(navigation_settings.get(self.con)['updated_by'],'Admin')
        self.assertEqual(navigation_settings.reset(self.con)['overrides'],{})
    def test_rendered_builtin_icon_keys_are_valid_for_save(self):
        browser = (Path(navigation_settings.__file__).resolve().parent / "nav_icons.js").read_text(encoding="utf-8")
        for item_id,key in (('frameworksNav','frameworksTarget'),('edrMonitoringNav','edrSearch')):
            with self.subTest(item_id=item_id):
                self.assertIn(f"id:'{item_id}'", browser)
                self.assertIn(f"iconKey:'{key}'", browser)
                self.assertIn(f"{key}:", browser)
                self.assertEqual(navigation_settings.ITEM_DEFAULTS[item_id][0],key)
                saved=navigation_settings.save(self.con,{item_id:{'iconKey':key,'visible':False}},'Admin')
                self.assertEqual(saved['overrides'][item_id]['visible'],False)
        with self.assertRaisesRegex(ValueError,'Невідома іконка'):
            navigation_settings.save(self.con,{'frameworksNav':{'iconKey':'not_a_real_icon'}},'Admin')
    def test_rejects_system_fields_unknown_icons_and_duplicate_order(self):
        for value in ({'historyNav':{'route':'bad'}},{'historyNav':{'iconKey':'raw-svg'}},{'historyNav':{'order':2}}):
            with self.assertRaises(ValueError): navigation_settings.validate(value)
    def test_write_and_reset_are_admin_only_routes(self):
        for method in ('POST','DELETE'):
            self.assertEqual(auth_access.permission_key(method,'/api/admin/navigation-settings'),'admin.manage')
            self.assertFalse(__import__('server').mutation_allowed('officer',method,'/api/admin/navigation-settings'))
            self.assertFalse(__import__('server').mutation_allowed('viewer',method,'/api/admin/navigation-settings'))
            self.assertTrue(__import__('server').mutation_allowed('admin',method,'/api/admin/navigation-settings'))
    def test_custom_svg_is_sanitized_and_can_be_selected(self):
        icon=navigation_settings.save_icon(self.con,{'icon_key':'safe_one','name':'Безпечна','svg':'<svg viewBox="0 0 24 24"><path d="M1 1h2"/></svg>'},'Admin')
        self.assertEqual(icon['icon_key'],'safe_one')
        saved=navigation_settings.save(self.con,{'historyNav':{'iconKey':'safe_one'}},'Admin')
        self.assertEqual(saved['overrides']['historyNav']['iconKey'],'safe_one')
    def test_svg_rejects_scripts_events_and_external_references(self):
        unsafe=['<svg><script>alert(1)</script></svg>','<svg onload="alert(1)"><path d="M1 1"/></svg>','<svg><path fill="url(https://bad.test/x)"/></svg>','<svg><foreignObject/></svg>']
        for svg in unsafe:
            with self.assertRaises(ValueError): navigation_settings.save_icon(self.con,{'icon_key':'unsafe','name':'X','svg':svg},'Admin')
    def test_custom_icon_write_is_admin_only(self):
        self.assertEqual(auth_access.permission_key('POST','/api/admin/navigation-icons'),'admin.manage')

if __name__=='__main__': unittest.main()
