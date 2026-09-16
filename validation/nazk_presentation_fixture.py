"""Loopback-only synthetic browser fixture; never opens a WEB/LOCAL business DB."""
import json
import os
from pathlib import Path
import sys

os.environ.update(PQM_SAFE_MODE='1', PQM_RELEASE_SCHEMA_ONLY='1', PQM_ENABLE_NAZK_WORKFLOW='0')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_smoke as web
import nazk_workflow as workflow
import historical_applications

web.fixture()
cases = [
    ('rejected-empty', 'unsuccessful', '', False, '', '2464907793'),
    ('decision-empty', 'pending', 'reject', False, '', '90000002'),
    ('historical-empty', 'unsuccessful', '', True, '', '90000003'),
    ('rejected-refuted', 'unsuccessful', '', False, 'refuted', '90000004'),
    ('rejected-confirmed', 'unsuccessful', '', False, 'confirmed', '90000005'),
    ('rejected-unfinished', 'unsuccessful', '', False, 'needs_check', '90000006'),
    ('historical-refuted', 'unsuccessful', '', True, 'refuted', '90000007'),
    ('active-control', 'pending', '', False, 'needs_check', '90000008'),
    ('active-empty', 'pending', '', False, '', '90000009'),
    ('decision-unfinished', 'pending', 'reject', False, 'needs_check', '90000010'),
]
historical_applications.manifest = lambda: {
    'version': 1, 'applications': {sid: {'source_system': 'MedData', 'source_row': index + 2}
                                for index, (sid, _, _, historical, _, _) in enumerate(cases) if historical}}
with web.server.db() as con:
    for sid, status, decision, historical, state, code in cases:
        manager = 'SYNTHETIC PERSON ' + code
        document = {'id': 'doc-' + sid, 'title': 'Synthetic certificate', 'url': 'https://example.invalid/' + sid}
        con.execute('''INSERT INTO submissions
            (id,framework_id,supplier_name,supplier_code,date_published,qualification_id,documents_json,raw_json,synced_at)
            VALUES (?,'framework',?,?,?, ?,?,'{}','fixture')''',
                    (sid, 'SYNTHETIC ' + sid, code, '2023-01-01' if historical else '2026-09-16',
                     'q-' + sid, json.dumps([document])))
        con.execute('''INSERT INTO qualifications
            (id,framework_id,submission_id,status,raw_json,synced_at)
            VALUES (?,'framework',?,?,'{}','fixture')''', ('q-' + sid, sid, status))
        con.execute('''INSERT INTO application_fields (submission_id,manager_name,protocol_decision)
            VALUES (?,?,?)''', (sid, manager, decision))
        if state:
            con.execute("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES (?,?,'{}')", ('source-' + sid, manager))
            workflow.ensure_submission_nazk_control(con, sid)
            if state in {'refuted', 'confirmed'}:
                outcome = workflow.complete_submission_nazk_check(
                    con, sid, document_id=document['id'], document_url=document['url'],
                    evidence_date='2026-09-16', checked_by='Synthetic officer')
                if state == 'confirmed':
                    con.execute("UPDATE supplier_nazk_checks SET result='confirmed' WHERE id=?", (outcome['check_id'],))

print('READY: loopback synthetic NAZK presentation fixture, 10 cases, safe mode', flush=True)
web.server.ThreadingHTTPServer(('127.0.0.1',18817), web.server.Handler).serve_forever()
