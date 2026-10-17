"""Additive task-type filtering; synthetic DB and authorized read-only HTTP."""
from contextlib import closing
from http.server import ThreadingHTTPServer
import http.client
import gc
import json
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import server


class TaskTypeFilterUiTests(unittest.TestCase):
    def test_actual_handler_preserves_status_filters_kpi_and_toggles(self):
        run=subprocess.run(['node','validation/task_type_filter_unit.cjs'],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)


class TaskTypeFilterHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        def cleanup():
            gc.collect()  # Release request-scoped SQLite cycles before Windows unlink.
            self.tmp.cleanup()
        self.addCleanup(cleanup)
        self.db=Path(self.tmp.name)/'synthetic.sqlite3'
        with closing(sqlite3.connect(f'file:{Path(server.DB_PATH).as_posix()}?mode=ro',uri=True)) as source:
            definitions=[r[0] for r in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]
        with closing(sqlite3.connect(self.db)) as target:
            with target:
                for definition in definitions:target.execute(definition)
        self.patches=[patch.object(server,'DB_PATH',self.db),patch.object(server,'AUTH_ENABLED',False),patch.object(server,'LOCAL_ROLE_IMPERSONATION',True)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        with closing(server.db()) as con:
            with con:
                con.execute("INSERT INTO authorized_officers(id,full_name,active,created_at,updated_at) VALUES(42,'Synthetic Officer',1,'2026-10-18','2026-10-18')")
                self.rows=[]
                for i in range(16):self.rows.append(('completed','amcu_exclusion' if i<2 else 'warning_block' if i<5 else 'nazk_check','Контроль',42,'2026-10-18'))
                for kind in ['nazk_check','amcu_exclusion','warning_block']:
                    for status in ['new','in_progress','ready_for_document','awaiting_response','waiting_external','awaiting_sync']:
                        self.rows.append((status,kind,'Контроль',42,'2026-10-18'))
                    for name,officer,date in [('Чужа вибірка',42,'2026-10-18'),('Контроль',None,'2026-10-18'),('Контроль',42,'2020-01-01')]:
                        self.rows.append(('completed',kind,name,officer,date))
                for i,(status,kind,name,officer,date) in enumerate(self.rows):
                    con.execute('''INSERT INTO operational_tasks
                      (id,task_key,task_type,supplier_code,supplier_name_snapshot,status,assigned_officer_id,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?)''',(f'{i+1:032x}',f'test:{i}',kind,f'{i+1:08d}',name,status,officer,date,date))
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        def close_http():self.http.shutdown();self.http.server_close();self.thread.join(5)
        self.addCleanup(close_http)

    def get(self,**params):
        with closing(http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=10)) as client:
            client.request('GET','/api/operational-tasks?'+urlencode(params),headers={'X-PQM-Local-Role':'admin'})
            response=client.getresponse();self.assertEqual(response.status,200)
            return json.loads(response.read())

    def test_16_completed_then_two_amcu_then_clear_and_kpi_preserved(self):
        params=dict(status_group='completed',search='Контроль',officer='42',date_from='2026-10-17')
        before=self.get(**params);filtered=self.get(**params,type='amcu_exclusion');after=self.get(**params)
        self.assertEqual([before['total'],filtered['total'],after['total']],[16,2,16])
        self.assertEqual(filtered['status_group'],'completed');self.assertEqual(filtered['kpis'],before['kpis'])
        self.assertEqual(filtered['type_counts'],before['type_counts'])
        self.assertEqual({r['status'] for r in filtered['items']},{'completed'})

    def test_all_three_types_intersect_each_status_group_and_filters_without_writes(self):
        import operational_tasks
        with closing(server.db()) as con:before='\n'.join(con.iterdump())
        for group in ['active','needs_action','awaiting_response','ready_for_document','awaiting_sync','completed']:
            for kind in ['nazk_check','amcu_exclusion','warning_block']:
                expected=sum(status in operational_tasks.STATUS_GROUPS[group] and typ==kind and name=='Контроль' and officer==42 and date>='2026-10-17'
                             for status,typ,name,officer,date in self.rows)
                result=self.get(status_group=group,type=kind,search='Контроль',officer='42',date_from='2026-10-17')
                self.assertEqual(result['total'],expected);self.assertEqual(result['status_group'],group)
                self.assertTrue(all(r['task_type']==kind and r['status'] in operational_tasks.STATUS_GROUPS[group] for r in result['items']))
        with closing(server.db()) as con:self.assertEqual(before,'\n'.join(con.iterdump()))
