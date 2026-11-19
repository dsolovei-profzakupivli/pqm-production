import sqlite3
import unittest
from pathlib import Path
import auth_access
import server
import table_widths

def _project_root():
    return next(parent for parent in Path(__file__).resolve().parents if (parent / 'server.py').is_file())

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
    def test_shared_order_updates_without_losing_widths_or_visibility(self):
        key='edr-monitoring'
        table_widths.save(self.db,key,{'name':420,'status':150},'admin',['name','status'],['name','status'],['name','status'])
        updated=table_widths.save(self.db,key,{},'admin',order=['status','name'],columns=['name','status'])
        self.assertEqual({'name':420,'status':150},{key:updated[key] for key in ('name','status')})
        self.assertEqual(['name','status'],updated['__visible__'])
        self.assertEqual(['status','name'],updated['__order__'])
        self.assertEqual(['name','status'],updated['__columns__'])
    def test_legacy_records_remain_readable_and_new_columns_default_visible(self):
        self.db.execute("INSERT INTO system_table_widths VALUES (?,?,?,?)",('legacy','{"name":280,"__visible__":["name"]}','now','admin'))
        stored=table_widths.list_all(self.db)['legacy']
        self.assertEqual(280,stored['name'])
        self.assertEqual(['name'],stored['__visible__'])
        source=self._width_ui_source()
        self.assertIn("keys.filter(key=>!known.has(key))",source)
        self.assertIn("widths.__columns__",source)
    def test_shared_settings_writer_is_admin_only_even_for_direct_api_calls(self):
        self.assertTrue(server.mutation_allowed('admin','POST','/api/admin/table-widths'))
        self.assertFalse(server.mutation_allowed('viewer','POST','/api/admin/table-widths'))
        self.assertFalse(server.mutation_allowed('officer','DELETE','/api/admin/table-widths'))
        self.assertFalse(server.mutation_allowed('viewer','PATCH','/api/admin/table-widths'))
        self.assertTrue(server.admin_read_allowed('viewer','/api/table-widths'))
    def test_application_personal_profiles_remain_owner_scoped_for_all_roles(self):
        for role in ('admin','officer','viewer'):
            self.assertTrue(server.mutation_allowed(role,'POST','/api/application-profiles'))
            self.assertTrue(server.mutation_allowed(role,'PATCH','/api/application-profiles/owned-profile'))
        source=(_project_root()/'server.py').read_text(encoding='utf-8')
        self.assertIn('if current["is_system"] and self.auth_role != "admin"',source)
        self.assertIn('if not current["is_system"] and current["owner_key"] != _profile_owner(self.auth_user)',source)
        self.assertIn("personal_layout_write = (self.auth_role == 'viewer'",source)
        self.assertIn("if self.auth_role == 'viewer' and not set(payload).issubset({'columns'})",source)
        app=(_project_root()/'app.js').read_text(encoding='utf-8')
        self.assertIn("if(currentMe?.role!=='viewer'){payload.kpis=p.kpis;payload.sorts=p.sorts||multiSort}",app)
        self.assertIn("profiles.find(p=>!p.is_system&&p.source_system_profile_id===defaultSystem.id)",app)
    def test_width_control_is_scoped_to_visible_table_toolbar(self):
        source=self._width_ui_source()
        self.assertIn("if(table.id==='applicationsTable'||table.closest('#historyView'))return",source)
        self.assertIn("document.body.dataset.authRole!=='admin'||!isVisible(table)",source)
        self.assertIn("occupied.has(toolbar)",source)
        self.assertIn("data-visible",source)
        self.assertIn("visibility=!isPersonalTable(table)",source)
        self.assertIn("body.visible=visible",source)
        self.assertIn("request(`${API}/admin/table-widths`",source)
        self.assertIn("__order__",source)
        self.assertNotIn('pqm.table-widths.v2',source)
        self.assertNotIn(".module-heading')||",source)
    def test_only_admin_can_change_widths_or_open_width_editors(self):
        source=self._width_ui_source()
        self.assertIn("function canResize(table){return document.body.dataset.authRole==='admin'||(isPersonalTable(table)&&['admin','officer','viewer'].includes(document.body.dataset.authRole))}",source)
        self.assertIn("if(document.body.dataset.authRole!=='admin')return",source)
        self.assertIn("async function ensurePersonalApplicationProfile()",(_project_root()/'app.js').read_text(encoding='utf-8'))
    def test_supplier_widths_save_reload_and_visible_failure(self):
        key='suppliersView:supplierRegistryBody'
        table_widths.save(self.db,key,{'єдрпоу-рнокпп':240},'admin')
        self.assertEqual(table_widths.list_all(self.db)[key]['єдрпоу-рнокпп'],240)
        source=self._width_ui_source()
        self.assertIn("request(`${API}/admin/table-widths`",source)
        self.assertNotIn('pqm.table-widths.v2',source)
        self.assertIn("apply(table,saved[key])",source)
        self.assertIn("catch(error){toast(error.message||'Не вдалося зберегти колонки','error')}",source)
    @staticmethod
    def _width_ui_source():
        path=next(parent/'table_widths_ui.js' for parent in Path(__file__).resolve().parents
                  if (parent/'table_widths_ui.js').is_file())
        return path.read_text(encoding='utf-8')

if __name__=='__main__': unittest.main()
