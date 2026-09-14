import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
import formed_protocols as fp

class FormedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db,self.old_dir=server.DB_PATH,server.PROTOCOLS_DIR
        server.DB_PATH=Path(self.tmp.name)/'db.sqlite3';server.PROTOCOLS_DIR=Path(self.tmp.name)/'protocols'
        server.init_db()
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES ('f','UA-F-TEST','Тестовий відбір','12300000-0','active','{}','now')")
            for i in range(8):
                sid=f's{i}';number='100' if i<5 else '101';officer='Тетяна ФЕДЧЕНКО' if i<5 else 'Олена ЄРЬОМІНА'
                con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,documents_json,raw_json,synced_at) VALUES (?,'f',?,'pending','[]','{}','now')",('q'+sid,sid))
                con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,qualification_id,date_published,raw_json,synced_at) VALUES (?,'f',?,?,?,'2026-09-05T10:00:00','{}','now')",(sid,str(10000000+i),'Тестовий учасник '+str(i),'q'+sid))
                con.execute("""INSERT INTO application_fields(submission_id,protocol_number,protocol_date,protocol_officer,
                  manager_name,protocol_decision,protocol_remarks,compliance_status) VALUES (?,?,'2026-09-05',?,'Керівник','admit','Без зауважень','approved')""",(sid,number,officer))
    def tearDown(self):
        server.DB_PATH,self.old_db=self.old_db,server.DB_PATH
        server.PROTOCOLS_DIR=self.old_dir
        self.tmp.cleanup()
    def generate(self,number='100'):
        return server.generate_protocol({'protocol_number':number},'acceptance-admin')
    def test_merge_5_plus_3_and_version_history(self):
        a,b=self.generate(),self.generate('101')
        self.assertEqual((5,3),(a['total'],b['total']))
        with server.db() as con:
            originals=[tuple(r) for r in con.execute('SELECT submission_id,protocol_number,protocol_date,protocol_officer,protocol_decision,protocol_remarks FROM application_fields ORDER BY submission_id')]
            con.execute('BEGIN IMMEDIATE')
            fp.cancel(con,a['protocol_id'],'admin',True,'Об’єднання');fp.cancel(con,b['protocol_id'],'admin',True,'Об’єднання')
            self.assertEqual(originals,[tuple(r) for r in con.execute('SELECT submission_id,protocol_number,protocol_date,protocol_officer,protocol_decision,protocol_remarks FROM application_fields ORDER BY submission_id')])
            con.execute("UPDATE application_fields SET protocol_number='100',protocol_officer='Тетяна ФЕДЧЕНКО' WHERE submission_id IN ('s5','s6','s7')")
        new=self.generate();self.assertEqual(8,new['total']);self.assertNotEqual(a['protocol_id'],new['protocol_id'])
        with server.db() as con:
            d=fp.detail(con,new['protocol_id']);self.assertEqual(2,d['version']);self.assertEqual(8,len(d['items']))
            self.assertEqual(5,len(fp.detail(con,a['protocol_id'])['items']))
            self.assertEqual('cancelled',fp.detail(con,a['protocol_id'])['status'])
            self.assertEqual(8,con.execute('SELECT COUNT(*) FROM formed_protocol_members WHERE active=1').fetchone()[0])
            self.assertEqual([],con.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual('ok',con.execute('PRAGMA integrity_check').fetchone()[0])
            paths=[server.PROTOCOLS_DIR/r[0] for r in con.execute('SELECT document_path FROM formed_protocols')]
            self.assertTrue(all(p.is_file() for p in paths));self.assertEqual(3,len(set(paths)))
    def test_error_does_not_create_members_or_markers(self):
        with patch('server.build_protocol_docx',side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):self.generate()
        with server.db() as con:
            self.assertEqual(0,con.execute('SELECT COUNT(*) FROM formed_protocols').fetchone()[0])
            self.assertEqual(0,con.execute("SELECT COUNT(*) FROM application_fields WHERE COALESCE(protocol_generated_at,'')<>''").fetchone()[0])
    def test_membership_positions_follow_protocol_sort_order(self):
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES ('f034','UA-F-034','03410000-7 - Лісоматеріали','03410000-7','active','{}','now')")
            con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES ('f314','UA-F-314','31430000-9 — Акумулятори','31430000-9','active','{}','now')")
            assignments = (
                ('s0', 'f314', '2026-09-05T08:00:00'),
                ('s1', 'f034', '2026-09-05T10:00:00'),
                ('s2', 'f034', '2026-09-05T09:00:00'),
                ('s3', 'f034', '2026-09-05T10:00:00'),
                ('s4', 'f314', '2026-09-04T08:00:00'),
            )
            for submission_id, framework_id, submitted_at in assignments:
                con.execute(
                    "UPDATE submissions SET framework_id=?, date_published=? WHERE id=?",
                    (framework_id, submitted_at, submission_id),
                )
                con.execute("UPDATE qualifications SET framework_id=? WHERE submission_id=?", (framework_id, submission_id))
        result = self.generate()
        with server.db() as con:
            detail = fp.detail(con, result['protocol_id'])
            stored_positions = [tuple(row) for row in con.execute(
                'SELECT submission_id, position FROM formed_protocol_members WHERE protocol_id=? ORDER BY position',
                (result['protocol_id'],),
            )]
        self.assertEqual(['s2', 's1', 's3', 's4', 's0'], [item['id'] for item in detail['items']])
        self.assertEqual(
            [('s2', 0), ('s1', 1), ('s3', 2), ('s4', 3), ('s0', 4)],
            stored_positions,
        )
    def test_duplicate_and_edit_are_blocked(self):
        a=self.generate()
        with self.assertRaises(ValueError):self.generate()
        with server.db() as con:
            with self.assertRaises(ValueError):fp.guard_edit(con,'s0',{'protocol_number':'NEW'})
            self.assertEqual(a['protocol_id'],fp.active(con,'s0')['id'])
    def test_legacy_confirmation_audit_and_status(self):
        with server.db() as con:
            con.execute("UPDATE application_fields SET generated_protocol_number='OLD',protocol_generated_at='old' WHERE submission_id IN ('s0','s1')")
        with self.assertRaises(ValueError):self.generate()
        with server.db() as con:
            with self.assertRaises(ValueError):fp.release_legacy(con,'s0','admin',False,'reason')
            con.execute("UPDATE qualifications SET status='active' WHERE id='qs1'")
            with self.assertRaises(ValueError):fp.release_legacy(con,'s1','admin',True,'reason')
            fp.release_legacy(con,'s0','admin',True,'reason')
            self.assertEqual('100',con.execute("SELECT protocol_number FROM application_fields WHERE submission_id='s0'").fetchone()[0])
            self.assertTrue(fp.legacy(con,'s1'));self.assertFalse(fp.legacy(con,'s0'))
            self.assertEqual(0,con.execute('SELECT COUNT(*) FROM formed_protocols').fetchone()[0])
            self.assertEqual(1,con.execute("SELECT COUNT(*) FROM audit_log WHERE field_name='legacy_protocol_cancelled'").fetchone()[0])
    def test_status_change_blocks_entire_cancellation(self):
        a=self.generate()
        with server.db() as con:con.execute("UPDATE qualifications SET status='unsuccessful' WHERE id='qs1'")
        with server.db() as con:
            with self.assertRaises(ValueError):fp.cancel(con,a['protocol_id'],'admin',True,'reason')
            self.assertEqual('active',fp.detail(con,a['protocol_id'])['status'])
    def test_viewer_and_wrong_officer_cannot_generate(self):
        for role in ('viewer','officer'):
            with self.assertRaises(PermissionError):server.generate_protocol({'protocol_number':'100'},'outsider',role,None)
    def test_stale_snapshot_cannot_generate(self):
        original=server.protocol_readiness
        def stale(payload):
            result=original(payload)
            with server.db() as con:con.execute("UPDATE application_fields SET manager_name='Інший' WHERE submission_id='s0'")
            return result
        with patch('server.protocol_readiness',side_effect=stale):
            with self.assertRaises(ValueError):self.generate()
    def test_additive_migration_does_not_touch_legacy(self):
        with server.db() as con:
            con.execute("UPDATE application_fields SET protocol_generated_at='old' WHERE submission_id='s0'")
            before=[tuple(r) for r in con.execute('SELECT * FROM application_fields')]
            fp.migrate(con);fp.migrate(con)
            self.assertEqual(before,[tuple(r) for r in con.execute('SELECT * FROM application_fields')])

if __name__=='__main__':unittest.main()
