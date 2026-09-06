import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import contextmanager, closing

@contextmanager
def database(*args, **kwargs):
    with closing(sqlite3.connect(*args, **kwargs)) as con:
        with con:
            yield con

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('migration',ROOT/'migrations/additive.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
TARGET=json.loads((ROOT/'migrations/target_schema.json').read_text(encoding='utf-8'))

class AdditiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'web.sqlite3'
        missing={'formed_protocols','formed_protocol_members','formed_protocol_events','auth_roles','auth_role_permissions','auth_user_roles','application_protocol_remark_selections','application_view_profiles','system_table_widths'}
        with database(self.db) as con:
            for t in TARGET['tables']:
                if t['name'] not in missing:
                    sql=t['sql']
                    if t['name']=='auth_users':
                        parts=[d for d in m.definitions(sql) if not d.startswith('last_seen_at ')]
                        sql='CREATE TABLE auth_users ('+','.join(parts)+')'
                    con.execute(sql)
            con.execute("INSERT INTO authorized_officers(id,full_name,active,created_at,updated_at) VALUES (1,'Synthetic Officer',1,'before','before')")
            con.execute("INSERT INTO auth_users(username,password_hash,role,officer_id,created_at,updated_at,created_by) VALUES ('fixture-account','synthetic-not-a-real-hash','admin',1,'before','before','fixture')")
            con.execute("INSERT INTO user_preferences(username,display_name,updated_at) VALUES ('fixture-account','Synthetic Display','before')")
            con.execute("INSERT INTO chat_threads(id,title,is_group,created_by,created_at,updated_at) VALUES (1,'Synthetic',0,'fixture-account','before','before')")
            con.execute("INSERT INTO chat_members(chat_id,username,joined_at) VALUES (1,'fixture-account','before')")
            con.execute("INSERT INTO chat_messages(id,chat_id,sender_username,body,submission_id,created_at) VALUES (1,1,'fixture-account','Synthetic message','fixture-submission','before')")
            con.execute("CREATE TABLE web_sessions(id TEXT PRIMARY KEY,value BLOB)")
            con.execute("INSERT INTO web_sessions VALUES ('fixture-session',X'010203')")
            con.execute("INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES ('fixture-framework','UA-F-SYNTHETIC','active','{}','before')")
            con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,raw_json,synced_at) VALUES ('fixture-submission','fixture-framework','00000000','Synthetic Supplier','{}','before')")
            con.execute("INSERT INTO application_fields(submission_id,protocol_number,protocol_remarks,notes) VALUES ('fixture-submission','SYNTHETIC','Manual remarks retained','Manual note retained')")
    def tearDown(self):self.tmp.cleanup()
    def test_preserves_all_old_rows_and_idempotent(self):
        result=m.migrate(self.db,TARGET,self.root/'backup')
        self.assertTrue(result['existing_data_identical']);self.assertEqual(result['before'],result['after'])
        self.assertEqual(0,result['foreign_key_violations']);self.assertTrue(Path(result['backup_path']).exists())
        with database(self.db) as con:
            self.assertEqual(([],[]),m.plan(con,TARGET))
            self.assertEqual('synthetic-not-a-real-hash',con.execute('SELECT password_hash FROM auth_users').fetchone()[0])
            self.assertEqual('Manual remarks retained',con.execute('SELECT protocol_remarks FROM application_fields').fetchone()[0])
        self.assertEqual([],m.migrate(self.db,TARGET,self.root/'backup')['applied_statements'])
    def test_incompatible_schema_stops_before_any_write(self):
        target=json.loads(json.dumps(TARGET))
        t=next(t for t in target['tables'] if t['name']=='auth_users')
        next(c for c in t['columns'] if c['name']=='role')['type']='INTEGER'
        with database(self.db) as con:before=m.fingerprints(con)[1]
        with self.assertRaises(RuntimeError):m.migrate(self.db,target,self.root/'backup')
        with database(self.db) as con:self.assertEqual(before,m.fingerprints(con)[1])
    def test_unique_index_failure_rolls_back_additive_work(self):
        with database(self.db) as con:
            con.execute("INSERT INTO auth_users(username,password_hash,role,officer_id,created_at,updated_at,created_by) VALUES ('second-fixture','fake','officer',1,'before','before','fixture')")
        with self.assertRaises(sqlite3.IntegrityError):m.migrate(self.db,TARGET,self.root/'backup')
        with database(self.db) as con:
            self.assertNotIn('formed_protocols',m.tables(con))
            self.assertEqual(2,con.execute('SELECT count(*) FROM auth_users').fetchone()[0])
if __name__=='__main__':unittest.main()
