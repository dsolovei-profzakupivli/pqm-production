"""Explicit WEB-only history repair. No server import, startup hook or network.

Plan is read-only. Apply requires its SHA-256, an unchanged input snapshot and
an operator-verified maintenance backup. Never accepts a LOCAL business DB.
Ambiguous history is retained as non-factual legacy_imported, not guessed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nazk_workflow import normalize_name, registry_fact_date, _date_value

PREFIX = 'web_nazk_history:v1:'
ACTOR = 'PQM WEB history migration 20260911'
RECEIPT = 'web_history_migration_completed_v1'
OPEN = {'needs_review', 'waiting_response', 'request_to_supplier', 'request_to_nazk'}

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()

def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]

def receipt(con):
    r = con.execute('SELECT details_json FROM supplier_nazk_check_events WHERE event_type=?', (RECEIPT,)).fetchone()
    return json.loads(r[0]) if r else None

def input_snapshot(con):
    # Include human edits, correspondence and manager/registry changes in the
    # precondition. A stale plan must fail, not overwrite concurrent work.
    tables = ['supplier_nazk_reviews', 'supplier_nazk_checks', 'supplier_nazk_check_matches',
              'supplier_nazk_check_events', 'supplier_nazk_check_documents', 'supplier_nazk_check_requests',
              'supplier_managers', 'nazk_registry', 'supplier_registry_summary']
    snapshot = {t: rows(con, f'SELECT * FROM {t} ORDER BY rowid') for t in tables}
    snapshot['operational_tasks'] = rows(con, "SELECT * FROM operational_tasks WHERE task_type='nazk_check' ORDER BY id")
    for t in ('operational_task_events', 'operational_task_responses', 'operational_task_channels'):
        snapshot[t] = rows(con, f"SELECT * FROM {t} WHERE task_id IN (SELECT id FROM operational_tasks WHERE task_type='nazk_check') ORDER BY rowid")
    return snapshot

def plan(con):
    done = receipt(con)
    if done:
        return {'already_applied': done}
    data = input_snapshot(con)
    registry = defaultdict(list)
    for r in data['nazk_registry']:
        registry[normalize_name(r['full_name'])].append(r)
    entries = []
    for r in data['supplier_nazk_reviews']:
        code, person = r['supplier_code'], normalize_name(r['manager_name'])
        key = PREFIX + code + ':' + str(r['source_row'])
        if any(c['legacy_key'] == key for c in data['supplier_nazk_checks']):
            raise RuntimeError('Partial import without receipt: manual review required')
        managers = [m for m in data['supplier_managers'] if m['supplier_code'] == code and normalize_name(m['manager_name']) == person]
        current = [m for m in managers if m['is_current']]
        manager = current[0] if len(current) == 1 else managers[0] if len(managers) == 1 else None
        matches = registry.get(person, []) if person else []
        checked, decision = _date_value(r['checked_at']), _date_value(r['decision_date'])
        case = re.sub(r'\s+', '', r['case_number'] or '').casefold()
        strict = [m for m in matches if case and decision and
                  re.sub(r'\s+', '', m['court_case_number'] or '').casefold() == case and
                  _date_value(m['sentence_date']) == decision]
        # Deliberately conservative: multi-fact and undated cases stay pending.
        factual = bool(len(matches) == len(strict) == 1 and r['evidence_url'].strip() and checked and
                       registry_fact_date(strict[0]) and checked >= registry_fact_date(strict[0]))
        result = (r['result'] or '').strip().casefold()
        same_checks = [c for c in data['supplier_nazk_checks'] if c['supplier_code'] == code and
                       normalize_name(c['manager_name']) == person]
        opened = [c for c in same_checks if c['workflow_status'] in OPEN and not c['result']]
        entry = dict(key=key, source=r, source_sha256=digest(r), manager_id=manager['id'] if manager else None,
                     registry_ids=[str(m['source_id']) for m in strict] if factual else [],
                     registry_fact_date=registry_fact_date(strict[0]) if factual else None,
                     checked_date=checked or None, reuse_check_id=None, cancel_check_id=None, cancel_task_id=None,
                     workflow_status='legacy_imported', result=None, reason='unresolved_history_requires_review')
        if result in {'спростовано', 'підтверджено'} and factual:
            entry.update(workflow_status='completed', result={'спростовано':'refuted','підтверджено':'confirmed'}[result],
                         reason='single_exact_person_case_date_with_historical_evidence')
        elif result == 'не актуально':
            entry.update(workflow_status='legacy_archived', reason='non_factual_inactive_reason_unknown' if not r['comment'].strip() else 'non_factual_inactive_source_comment')
        elif result == 'на запит':
            entry.update(workflow_status='waiting_response', reason='historical_awaiting_external_response')
            if len(opened) == 1 and opened[0]['workflow_status'] == 'needs_review':
                target = opened[0]
                related = [t for t in data['operational_tasks'] if json.loads(t['source_context']).get('nazk_check_id') == target['id']]
                if len(related) == 1 and related[0]['status'] == 'in_progress' and not related[0]['resolution_code']:
                    entry.update(reuse_check_id=target['id'], waiting_task_id=related[0]['id'])
            if opened and not entry['reuse_check_id']:
                # Do not create a second open cycle or overwrite a user's action.
                entry.update(workflow_status='legacy_imported', reason='waiting_workflow_conflict_requires_review')
        if entry['result'] == 'refuted' and len(opened) == 1 and current and opened[0]['manager_id'] == current[0]['id']:
            target = opened[0]
            linked = {str(m['nazk_source_id']) for m in data['supplier_nazk_check_matches'] if m['check_id'] == target['id']}
            related = [t for t in data['operational_tasks'] if json.loads(t['source_context']).get('nazk_check_id') == target['id']]
            # Only an untouched non-factual review can be cancelled automatically.
            if (linked == set(entry['registry_ids']) and target['workflow_status'] == 'needs_review' and
                len(related) == 1 and related[0]['status'] == 'in_progress' and not related[0]['resolution_code'] and
                not any(d['check_id'] == target['id'] for d in data['supplier_nazk_check_documents']) and
                not any(d['check_id'] == target['id'] for d in data['supplier_nazk_check_requests']) and
                not any(d['task_id'] == related[0]['id'] for d in data['operational_task_responses']) and
                not any(d['task_id'] == related[0]['id'] and d['status'] != 'not_sent' for d in data['operational_task_channels'])):
                entry.update(cancel_check_id=target['id'], cancel_task_id=related[0]['id'])
        entries.append(entry)
    return dict(version=1, source='WEB supplier_nazk_reviews', input_sha256=digest(data), entries=entries,
                summary=dict(source_rows=len(entries), new_checks=sum(not e['reuse_check_id'] for e in entries),
                             factual_refuted=sum(e['result']=='refuted' for e in entries),
                             factual_confirmed=sum(e['result']=='confirmed' for e in entries),
                             duplicate_cycles_cancelled=sum(bool(e['cancel_check_id']) for e in entries),
                             waiting_restored=sum(bool(e['reuse_check_id']) for e in entries),
                             historical_states=dict(Counter(e['workflow_status'] for e in entries))))

def check_event(con, cid, kind, stamp, details, old=None, new=None, result=None):
    con.execute('''INSERT INTO supplier_nazk_check_events
      (check_id,event_type,event_at,event_by,old_workflow_status,new_workflow_status,new_result,details_json)
      VALUES(?,?,?,?,?,?,?,?)''', (cid,kind,stamp,ACTOR,old,new,result,packed(details)))

def apply(con, manifest, manifest_sha):
    if digest(manifest) != manifest_sha:
        raise RuntimeError('Manifest SHA mismatch')
    con.execute('BEGIN IMMEDIATE')
    try:
        done = receipt(con)
        if done:
            if done['plan_sha256'] != manifest_sha:
                raise RuntimeError('Different migration already applied')
            con.rollback()
            return {'already_applied': done, 'changes': 0}
        if plan(con) != manifest:
            raise RuntimeError('STOP: source changed since plan; regenerate and review')
        stamp = datetime.now(timezone.utc).isoformat()
        first = None
        for e in manifest['entries']:
            r, cid = e['source'], e['reuse_check_id']
            details = dict(migration='web_nazk_history_v1', plan_sha256=manifest_sha,
                           source_table='supplier_nazk_reviews', source_sha256=e['source_sha256'],
                           source_snapshot=r, reason=e['reason'], registry_source_ids=e['registry_ids'],
                           historical_check_date=e['checked_date'], fact_date=e['registry_fact_date'],
                           strict_cycle_scope=True, no_request_sent=True)
            if cid:
                con.execute("""UPDATE supplier_nazk_checks SET workflow_status='waiting_response',
                  legacy_key=?,legacy_source_row=?,updated_at=?,updated_by=? WHERE id=?""",
                  (e['key'],r['source_row'],stamp,ACTOR,cid))
            else:
                cid = con.execute('''INSERT INTO supplier_nazk_checks
                  (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
                   evidence_date,covered_nazk_date,comment,is_legacy,legacy_source_row,legacy_key,
                   created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)''',
                  (r['supplier_code'],e['manager_id'],r['manager_name'],e['workflow_status'],e['result'],
                   e['checked_date'] or stamp,e['checked_date'] if e['result'] else None,
                   None,e['checked_date'] if e['result'] else None,r['comment'],r['source_row'],e['key'],
                   stamp,ACTOR,stamp,ACTOR)).lastrowid
            first = first or cid
            check_event(con,cid,'web_legacy_history_imported_v1',stamp,details,
                        'needs_review' if e['reuse_check_id'] else None,e['workflow_status'],e['result'])
            for source_id in e['registry_ids'] if e['result'] else []:
                con.execute('INSERT INTO supplier_nazk_check_matches(check_id,nazk_source_id,match_status,created_at) VALUES(?,?,?,?)',
                            (cid,source_id,e['result'] or 'candidate',stamp))
            # Preserve the reference, not a new document/correspondence workflow.
            # Waiting/inactive/ambiguous sources remain in the immutable event.
            if e['result'] and r['evidence_url']:
                con.execute('''INSERT INTO supplier_nazk_check_documents
                  (check_id,document_type,title,url,source,created_at,created_by)
                  VALUES(?,'legacy_evidence','Історичне WEB-посилання: дата документа не встановлена',?,'web_legacy_review',?,?)''',
                  (cid,r['evidence_url'],stamp,ACTOR))
            tid = e.get('waiting_task_id') or e['cancel_task_id']
            if not tid:
                continue
            task = dict(con.execute('SELECT * FROM operational_tasks WHERE id=?',(tid,)).fetchone())
            meta, context = json.loads(task['metadata']), json.loads(task['source_context'])
            provenance = dict(details, covering_factual_check_id=cid if e['cancel_check_id'] else None,
                              historical_check_id=cid, redundant_check_id=e['cancel_check_id'])
            if e['cancel_check_id']:
                meta['duplicate_cycle_provenance'] = context['duplicate_cycle_provenance'] = provenance
                con.execute("""UPDATE operational_tasks SET status='cancelled',resolution_code='duplicate_cycle_existing_factual',
                  resolution_text='Історичний factual refuted однозначно покриває цей цикл; зайву задачу скасовано.',
                  resolved_at=?,resolved_by=?,metadata=?,source_context=?,updated_at=?,version=version+1 WHERE id=?""",
                  (stamp,ACTOR,packed(meta),packed(context),stamp,tid))
                con.execute("UPDATE supplier_nazk_checks SET workflow_status='legacy_archived',updated_at=?,updated_by=? WHERE id=?",
                            (stamp,ACTOR,e['cancel_check_id']))
                check_event(con,e['cancel_check_id'],'duplicate_cycle_reconciled_to_existing_factual',stamp,
                            provenance,'needs_review','legacy_archived')
                kind, new = 'duplicate_cycle_reconciled_to_existing_factual', 'cancelled:duplicate_cycle_existing_factual'
            else:
                meta['legacy_waiting_provenance'] = provenance
                con.execute("UPDATE operational_tasks SET status='awaiting_response',metadata=?,updated_at=?,version=version+1 WHERE id=?",
                            (packed(meta),stamp,tid))
                kind, new = 'legacy_waiting_workflow_restored', 'awaiting_response'
            con.execute('''INSERT INTO operational_task_events(task_id,event_type,created_at,actor,old_value,new_value,metadata)
                           VALUES(?,?,?,?,?,?,?)''',(tid,kind,stamp,ACTOR,task['status'],new,packed(provenance)))
        result = dict(plan_sha256=manifest_sha, applied_at=stamp, summary=manifest['summary'])
        if first:
            check_event(con,first,RECEIPT,stamp,result)
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        con.commit()
        return result
    except BaseException:
        con.rollback()
        raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    p.add_argument('--plan',required=True)
    p.add_argument('--apply-sha256')
    p.add_argument('--maintenance-backup-sha256')
    a = p.parse_args()
    os.umask(0o077)
    path = Path(a.db).resolve()
    con = sqlite3.connect(path.as_uri() + ('?mode=rw' if a.apply_sha256 else '?mode=ro'),uri=True)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    if a.apply_sha256:
        if not re.fullmatch('[0-9a-f]{64}',a.maintenance_backup_sha256 or ''):
            p.error('Verified maintenance backup SHA is required')
        result = apply(con,json.loads(Path(a.plan).read_text()),a.apply_sha256)
    else:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        report = plan(con)
        Path(a.plan).write_text(packed(report))
        result = {'plan_sha256':digest(report),'summary':report.get('summary'),'already_applied':report.get('already_applied')}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    con.close()

if __name__ == '__main__':
    main()
