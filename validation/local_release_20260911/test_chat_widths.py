import sqlite3
import unittest
from pathlib import Path
import auth_access
import table_widths

class ChatAndWidthsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY)')
        auth_access.migrate(self.db);table_widths.migrate(self.db)
    def tearDown(self): self.db.close()
    def test_web_compatible_chat_schema(self):
        names={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'auth_users','user_preferences','user_avatars','chat_threads','chat_members','chat_messages','chat_attachments'}<=names)
    def test_system_widths_preserve_other_columns_and_reset(self):
        table_widths.save(self.db,'requests',{'date':90,'supplier':300},'admin')
        self.assertEqual(300,table_widths.list_all(self.db)['requests']['supplier'])
        table_widths.reset(self.db,'requests');self.assertNotIn('requests',table_widths.list_all(self.db))
    def test_web_viewer_can_chat_but_cannot_change_business_records(self):
        # Agreed WEB policy: account-owned messages are available to all users.
        permissions=auth_access.effective(self.db,'viewer','viewer')['permissions']
        self.assertTrue(permissions['messages.write'])
        self.assertFalse(permissions['applications.edit'])
    def test_shared_settings_persist_visibility_and_clamp_widths(self):
        saved=table_widths.save(self.db,'edr-monitoring',{'supplier_name':5000,'edr_status':20},'admin',['supplier_name'])
        self.assertEqual(saved['supplier_name'],1200)
        self.assertEqual(saved['edr_status'],40)
        self.assertEqual(saved['__visible__'],['supplier_name'])
        self.assertEqual(table_widths.list_all(self.db)['edr-monitoring']['__visible__'],['supplier_name'])
    def test_width_control_is_scoped_to_visible_table_toolbar(self):
        source=self._width_ui_source()
        self.assertIn("if(table.closest('#applicationsView,#historyView'))return",source)
        self.assertIn("if(document.body.dataset.authRole!=='admin'||!isVisible(table))return",source)
        self.assertIn("occupied.has(toolbar)",source)
        self.assertIn("data-visible",source)
        self.assertIn("visibilityControl",source)
        self.assertNotIn(".module-heading')||",source)
    def test_supplier_widths_save_reload_and_visible_failure(self):
        key='suppliersView:supplierRegistryBody'
        table_widths.save(self.db,key,{'єдрпоу-рнокпп':240},'admin')
        self.assertEqual(table_widths.list_all(self.db)[key]['єдрпоу-рнокпп'],240)
        source=self._width_ui_source()
        self.assertIn("request(`${API}/admin/table-widths`,{method:'POST'",source)
        self.assertIn("apply(table,saved[key])",source)
        self.assertIn("catch(error){toast(error.message||'Не вдалося зберегти колонки','error')}",source)
    @staticmethod
    def _width_ui_source():
        path=next(parent/'table_widths_ui.js' for parent in Path(__file__).resolve().parents
                  if (parent/'table_widths_ui.js').is_file())
        return path.read_text(encoding='utf-8')

if __name__=='__main__': unittest.main()
