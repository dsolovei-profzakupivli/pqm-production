"""Disposable synthetic setup only. Never called by the preview endpoint."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import server
import nazk_workflow


def build(path):
    previous = server.DB_PATH
    server.DB_PATH = Path(path)
    try:
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with closing(server.db()) as con, con:
            for number in range(1, 12):
                code = f'{number:08d}'; name=f'Синтетичний постачальник {number}'
                person=f'ТЕСТОВА ОСОБА {number}'
                active=0 if number in {8,9} else 2
                con.execute('INSERT INTO supplier_registry_summary(supplier_code,supplier_name,active_count,refreshed_at) VALUES (?,?,?,?)', (code,name,active,'2026-01-01'))
                con.execute('INSERT INTO supplier_edr_profiles(supplier_code,manager_name,full_name,synced_at) VALUES (?,?,?,?)', (code,person,name,'2026-01-01'))
                if number != 10:
                    con.execute('''INSERT INTO supplier_managers(id,supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
                      VALUES (?,?,?,?,1,'synthetic','2026-01-01','2026-01-01')''', (number,code,person,nazk_workflow.normalize_name(person)))
                con.execute('INSERT INTO nazk_registry(source_id,full_name,sentence_date,raw_json) VALUES (?,?,?,?)', (f'SYN-{number}',person,'2026-01-01','{}'))
                f=f'F-{number}'
                con.execute('INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at) VALUES (?,?,?,?,?)', (f,f,'active','{}','2026-01-01'))
                for index in range(2 if number != 8 else 0):
                    s=f'S-{number}-{index}';q=f'Q-{number}-{index}'
                    if number != 7:
                        con.execute('INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,raw_json,synced_at) VALUES (?,?,?,?,?,?)', (s,f,code,name,'{}','2026-01-01'))
                        con.execute('INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,?,?,?,?,?)',(q,f,s,'active','{}','2026-01-01'))
                        con.execute('UPDATE submissions SET qualification_id=? WHERE id=?',(q,s))
                    con.execute('INSERT INTO registry_contracts(id,qualification_id,framework_id,supplier_code,status,raw_json,synced_at) VALUES (?,?,?,?,?,?,?)',(f'RC-{number}-{index}',q,f,code,'active','{}','2026-01-01'))
                if number in {2,3,4,5,6}:
                    status='waiting_response' if number==2 else 'completed' if number in {3,4} else 'needs_review'
                    result='refuted' if number==3 else 'confirmed' if number==4 else None
                    con.execute('''INSERT INTO supplier_nazk_checks(id,supplier_code,manager_id,manager_name,workflow_status,result,
                      started_at,completed_at,evidence_date,covered_nazk_date,created_at,created_by,updated_at,updated_by)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,'synthetic',?,'synthetic')''',
                      (number,code,number,person,status,result,'2026-01-01','2026-02-01' if result else None,'2026-02-01' if result else None,'2026-02-01' if result else None,'2026-01-01','2026-01-01'))
                    con.execute('INSERT INTO supplier_nazk_check_matches(check_id,nazk_source_id,match_status,created_at) VALUES (?,?,?,?)',(number,f'SYN-{number}','candidate','2026-01-01'))
                if number in {2,5,11}:
                    status='awaiting_response' if number==2 else 'completed' if number==11 else 'in_progress'
                    con.execute('''INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,supplier_name_snapshot,status,created_at,updated_at,source_context)
                      VALUES (?,?,?,?,?,?,?,?,?)''',(f'{number:032x}',f'nazk_check:{code}:{number}:SYN-{number}','nazk_check',code,name,status,'2026-01-01','2026-01-01',json.dumps({'nazk_check_id':number if number!=11 else None})))
        return Path(path)
    finally:
        server.DB_PATH = previous
