from contextlib import closing
import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import auth_access
import chat_annotations as chat


class ChatAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'synthetic.sqlite'
        self.con = self.connect()
        self.con.execute('CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY)')
        auth_access.migrate(self.con)
        self.con.executescript('''
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,dk_code TEXT);
          CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_name TEXT,supplier_code TEXT,framework_id TEXT);
          INSERT INTO frameworks VALUES ('framework-target','15610000-7');
          INSERT INTO submissions VALUES ('submission-target','ФОП Заклевський Віталій Леонідович','2908003312','framework-target');
        ''')
        for id in (7, 42):
            self.con.execute('INSERT INTO chat_threads VALUES (?,?,?,?,?,?)',
                             (id, 'Довільний чат', 1, 'alice', 'old', 'old'))
            for user in ('alice','bob'):
                self.con.execute('INSERT INTO chat_members VALUES (?,?,?,0)', (id,user,'old'))
            self.con.execute('INSERT INTO chat_messages VALUES (?,?,?,?,?,?)',
                             (id,id,'alice','Перевірити заявку','submission-target' if id==7 else '000-id','original'))
        self.con.commit()
        chat.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def connect(self):
        con=sqlite3.connect(self.path,timeout=10)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con

    def change(self,payload,user='alice',id=7,room=7):
        with self.con:
            return chat.change(self.con,room,id,user,payload)

    def select(self,mark='all',room=7,**params):
        return chat.select_messages(self.con,room,'alice',{'mark':[mark],**{key:[str(value)] for key,value in params.items()}})

    def test_migration_repeat_preserves_all_original_messages(self):
        old=[tuple(row) for row in self.con.execute('SELECT * FROM chat_messages')]
        chat.migrate(self.con)
        self.assertEqual(old,[tuple(row) for row in self.con.execute('SELECT * FROM chat_messages')])

    def test_reactions_coexist_and_repeat_is_idempotent(self):
        for user in ('alice','bob'):
            for kind in ('support','seen'):
                for _ in range(2):self.change({'kind':kind,'active':True},user)
        self.assertEqual(4,len(chat.marks(self.con,7)['reactions']))
        self.change({'kind':'support','active':False})
        self.assertEqual(3,len(chat.marks(self.con,7)['reactions']))

    def test_work_exclusivity_history_and_empty_reset(self):
        self.change({'kind':'support','active':True})
        for state,version in [('working',0),('done',1),('',2)]:
            result=self.change({'kind':'work','state':state,'version':version})
            self.assertEqual(state,result['work']['state'])
        self.assertEqual(3,self.con.execute('SELECT COUNT(*) FROM chat_work_history').fetchone()[0])
        self.assertEqual(1,len(result['reactions']))
        self.assertEqual('original',self.con.execute('SELECT created_at FROM chat_messages WHERE id=7').fetchone()[0])

    def test_conflicting_user_update_is_rejected_without_history_loss(self):
        self.change({'kind':'work','state':'working','version':0})
        with self.assertRaises(chat.ChatError) as raised:
            self.change({'kind':'work','state':'done','version':0},'bob')
        self.assertEqual(409,raised.exception.status)
        self.assertEqual('working',chat.marks(self.con,7)['work']['state'])
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM chat_work_history').fetchone()[0])

    def test_work_retry_no_duplicate_audit_event(self):
        payload={'kind':'work','state':'working','version':0}
        self.change(payload);self.change(payload)
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM chat_work_history').fetchone()[0])

    def test_other_room_and_nonmember_are_never_accessible(self):
        for id,room,user in [(7,42,'alice'),(7,7,'outsider')]:
            with self.assertRaises(chat.ChatError) as raised:
                self.change({'kind':'support','active':True},user,id,room)
            self.assertEqual(404,raised.exception.status)
        with self.assertRaises(chat.ChatError):chat.select_messages(self.con,7,'outsider',{})

    def test_filters_current_work_not_history_and_no_cross_chat_leak(self):
        self.change({'kind':'work','state':'working','version':0})
        self.change({'kind':'work','state':'done','version':1})
        self.assertEqual([],self.select('working')[0])
        self.assertEqual([7],[row['id'] for row in self.select('done')[0]])
        self.assertEqual([],self.select('done',room=42)[0])
        self.assertEqual([42],[row['id'] for row in self.select('unmarked',room=42)[0]])

    def test_unmarked_requires_absence_of_both_reactions_and_current_work(self):
        for kind in ('support','seen'):
            self.change({'kind':kind,'active':True});self.assertEqual([],self.select('unmarked')[0])
            self.change({'kind':kind,'active':False})
        self.change({'kind':'work','state':'done','version':0});self.assertEqual([],self.select('unmarked')[0])
        self.change({'kind':'work','state':'','version':1});self.assertEqual(1,len(self.select('unmarked')[0]))

    def test_read_queries_work_in_query_only_mode_without_writes(self):
        self.con.execute('PRAGMA query_only=ON')
        before=self.con.total_changes
        for mark in chat.FILTERS:self.select(mark,search='ПЕРЕВІРИТИ')
        chat.marks(self.con,7)
        self.assertEqual(before,self.con.total_changes)

    def test_unicode_search_and_current_chat(self):
        self.assertEqual([7],[row['id'] for row in self.select(search='ПЕРЕВІРИТИ')[0]])
        self.assertEqual([],self.select(search='немає')[0])

    def test_search_finds_linked_application_fields_across_unloaded_history(self):
        # The target is older than the default first page and must be found by SQL search.
        self.con.executemany('INSERT INTO chat_messages VALUES (?,7,?,?,?,?)',
            [(100+i,'bob',f'Не пов’язане повідомлення {i}','','old') for i in range(210)])
        self.con.commit()
        for term in ('15610000-7','2908003312','Заклевський','Віталій','submission-target'):
            rows,meta,_=self.select(search=term)
            self.assertEqual([7],[row['id'] for row in rows],term)
            self.assertEqual(1,meta['total'],term)
        rows,_,_=self.select(search='15610000-7 * 2908003312 * Заклевський Віталій')
        self.assertEqual([7],[row['id'] for row in rows])
        self.assertEqual([],self.select(search='Заклевський',room=42)[0])
        self.change({'kind':'support','active':True})
        self.assertEqual([7],[row['id'] for row in self.select('support',search='2908003312')[0]])

    def test_annotation_survives_reconnect_and_is_shared(self):
        self.change({'kind':'support','active':True})
        with closing(self.connect()) as second:
            self.assertEqual('alice',chat.marks(second,7)['reactions'][0]['username'])

    def test_cursor_pagination_and_visible_refresh_are_chat_scoped(self):
        self.con.executemany('INSERT INTO chat_messages VALUES (?,7,?,?,?,?)',
            [(100+i,'alice',f'Історія {i}','','old') for i in range(210)])
        self.con.commit()
        latest=self.select()[0];self.assertEqual(100,len(latest))
        older=self.select(before=latest[0]['id'])[0]
        self.assertEqual(100,len(older));self.assertLess(older[-1]['id'],latest[0]['id'])
        rows,meta,updates=self.select(since=300,known='7,42')
        self.assertEqual(9,meta['new_count']);self.assertEqual([7],[row['id'] for row in updates])
        delta,metadata,_=self.select(after=100)
        self.assertEqual(list(range(101,201)),[row['id'] for row in delta])
        self.assertTrue(metadata['has_more'])
        self.assertTrue(all(row['chat_id']==7 for row in delta))

    def test_invalid_marks_and_cursor_are_rejected(self):
        for payload in [{'kind':[]},{'kind':'work','state':[],'version':0},{'kind':'bad'},{'kind':'support','active':1},{'kind':'work','state':'done','version':True}]:
            with self.assertRaises(chat.ChatError):self.change(payload)
        for params in [dict(before=-1),dict(page='oops'),dict(known='7,BOGUS')]:
            with self.assertRaises(chat.ChatError):self.select(**params)

    def test_future_chat_works_without_special_id_title_or_members(self):
        self.con.execute("INSERT INTO chat_threads VALUES (931,'Новий чат',0,'eve','now','now')")
        self.con.execute("INSERT INTO chat_members VALUES (931,'eve','now',0)")
        self.con.execute("INSERT INTO chat_messages VALUES (932,931,'eve','Нове','','now')")
        self.con.commit()
        result=self.change({'kind':'seen','active':True},'eve',932,931)
        self.assertEqual('eve',result['reactions'][0]['username'])

    def test_parallel_work_updates_have_one_winner(self):
        def write(user,state):
            con=self.connect()
            try:
                with con:return chat.change(con,7,7,user,{'kind':'work','state':state,'version':0})['work']['state']
            except chat.ChatError as error:return error.status
            finally:con.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda args:write(*args),[('alice','working'),('bob','done')]))
        self.assertEqual(1,results.count(409))
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM chat_work_history').fetchone()[0])


if __name__=='__main__':unittest.main()
