"""Supplier filters and admission-only, supplier-deduplicated XLSX selection."""
from datetime import datetime, timezone
import json
import supplier_activity
import admission_resolver


def registry_members(con, framework_ids=None):
    """Existing agreement-contract cache is proof of membership, not of its date.

    Never read Bids or refresh Prozorro here. Keep unknown contract states visible.
    """
    ids=sorted(set(framework_ids or []))
    clause=' WHERE rc.framework_id IN ('+','.join('?' for _ in ids)+')' if ids else ''
    rows=[]
    for raw in con.execute('''SELECT rc.id contract_id,rc.framework_id,rc.supplier_code,
      rc.status contract_status,rc.raw_json contract_raw,rc.milestones_json,
      q.id qualification_id,q.status qualification_status,q.raw_json qualification_raw,
      s.id submission_id,s.supplier_name,s.raw_json submission_raw
      FROM registry_contracts rc
      LEFT JOIN qualifications q ON q.id=rc.qualification_id AND q.framework_id=rc.framework_id
      LEFT JOIN submissions s ON s.id=COALESCE(q.submission_id,json_extract(rc.raw_json,'$.submissionID')) AND s.framework_id=rc.framework_id
        AND s.supplier_code=rc.supplier_code'''+clause,ids):
        row=dict(raw)
        contract=json.loads(row['contract_raw'] or '{}')
        supplier=(contract.get('suppliers') or [{}])[0]
        row['supplier_name']=row['supplier_name'] or supplier.get('name') or (supplier.get('identifier') or {}).get('legalName') or ''
        row['admission_at']=admission_resolver.qualification_stamp(row['qualification_status'],
          row['qualification_id'],row['submission_id'],row['qualification_raw'])
        row['scope_status']=row['contract_status']
        row['identity_missing']=not bool(str(row['supplier_code'] or '').strip())
        rows.append(row)
    return rows


def registry_counts(con):
    groups={}
    for raw in con.execute('SELECT framework_id,supplier_code,status,id FROM registry_contracts'):
        row=dict(raw)
        groups.setdefault((row['framework_id'],row['supplier_code'] or '@'+row['id']),set()).add(row['status'] or '')
    result={}
    for (fid,code),states in groups.items():
        counts=result.setdefault(fid,dict(total=0,active=0,suspended=0,terminated=0,other=0,issues=[]))
        counts['total']+=1
        if len(states)==1 and not code.startswith('@'):
            state=next(iter(states))
        else:
            rows=[r for r in registry_members(con,[fid]) if r['supplier_code']==code]
            if rows and all(r['admission_at'] for r in rows):
                latest=max(datetime.fromisoformat(r['admission_at'].replace('Z','+00:00')) for r in rows)
                latest_states={r['contract_status'] for r in rows if datetime.fromisoformat(r['admission_at'].replace('Z','+00:00'))==latest}
                state=next(iter(latest_states)) if len(latest_states)==1 else 'ambiguous'
            else:state='ambiguous'
        if state in {'active','suspended','terminated'}:counts[state]+=1
        else:
            counts['other']+=1
            counts['issues'].append({'supplier_code':code,'statuses':sorted(states),'reason':state})
    return result


def selection_sql(params):
    get = lambda key: str(params.get(key, [''])[0] or '').strip()
    dk, framework, status = get('dk_code'), get('framework_id'), get('status')
    frameworks=sorted({str(v).strip() for v in params.get('framework_id',[]) if str(v).strip()})
    framework_clause=('f.id IN ('+','.join('?' for _ in frameworks)+')') if frameworks else '1=1'
    if status not in {'','active','suspended','terminated','not_registered'}:
        raise ValueError('Невідомий статус постачальника')
    active = supplier_activity.effective_active_sql('rc','f')
    # Choose an effective admission before a newer pending/rejected application.
    # A suspended membership remains a current qualification, not a fresh admission.
    sql = f'''WITH linked AS (
      SELECT s.id submission_id,s.supplier_code,s.supplier_name,s.raw_json submission_raw,
        s.date_published,s.framework_id,f.pretty_id,f.dk_code,
        q.id qualification_id,q.status qualification_status,q.raw_json qualification_raw,
        rc.id contract_id,rc.status contract_status,
        CASE WHEN q.status='active' AND {active} THEN 2
             WHEN q.status='active' AND rc.status='suspended' AND f.status='active'
              AND (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
                OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now')) THEN 1
             ELSE 0 END current_rank,
        CASE WHEN {active} THEN 'active' WHEN rc.status='suspended' THEN 'suspended'
             WHEN rc.id IS NOT NULL THEN 'terminated' ELSE 'not_registered' END scope_status
      FROM submissions s JOIN frameworks f ON f.id=s.framework_id
      LEFT JOIN qualifications q ON q.id=s.qualification_id AND q.submission_id=s.id
      LEFT JOIN registry_contracts rc ON rc.qualification_id=q.id AND rc.framework_id=s.framework_id
        AND rc.supplier_code=s.supplier_code
      WHERE trim(COALESCE(s.supplier_code,''))<>'' AND (?='' OR f.dk_code=?) AND {framework_clause}
    ), ranked AS (
      SELECT *,row_number() OVER(PARTITION BY framework_id,supplier_code ORDER BY
        current_rank DESC,
        CASE WHEN current_rank>0 THEN julianday(json_extract(qualification_raw,'$.date')) END DESC,
        julianday(date_published) DESC,submission_id DESC,contract_id DESC) position
      FROM linked
    ) SELECT * FROM ranked WHERE position=1 AND (?='' OR scope_status=?)'''
    return sql, [dk,dk,*frameworks,status,status]


def export_rows(con, params, allowed_codes):
    from supplier_contacts import contact_from_submission
    evidence=admission_resolver.admission_events(con,allowed_codes)
    admission_times={}
    for event in evidence:
        sid=event.get('source_submission_id')
        stamp=event.get('occurred_at')
        instant=admission_resolver.event_instant(stamp)
        if sid and instant and (sid not in admission_times or instant>admission_times[sid][0]):
            admission_times[sid]=(instant,stamp)
    # Export is an admission register, not the application's current-row list.
    # Keep the UI selector unchanged; rank every proven admission across scopes.
    sql,args=selection_sql({**params,'status':['']})
    sql=sql.split('), ranked AS (',1)[0]+') SELECT * FROM linked'
    selected={}
    registry_only=params.get('registry_only')==['1']
    source=registry_members(con,params.get('framework_id')) if registry_only else con.execute(sql,args[:-2])
    for raw in source:
        row=dict(raw)
        if row['supplier_code'] not in allowed_codes:
            continue
        # Reuse canonical admission evidence, including proven historical snapshots.
        # A later non-active qualification.date is never a former admission date.
        if row['submission_id'] not in admission_times:
            if not registry_only:continue
            stamp=row['admission_at']
        else:stamp=admission_times[row['submission_id']][1]
        if registry_only and not stamp:
            raise ValueError('Не підтверджено дату допуску; експорт реєстру зупинено без підміни timestamp')
        try:
            parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if parsed.tzinfo is None:continue
        except (ValueError,TypeError,AttributeError):
            if not registry_only:continue
            parsed=datetime.min.replace(tzinfo=timezone.utc)
        key=row['supplier_code']
        if registry_only and (not key or row['identity_missing']):raise ValueError('Відсутній код постачальника в реєстрі')
        if registry_only and key in selected and (not stamp or not selected[key][2]):
            raise ValueError('Не підтверджено дату для вибору останнього допуску постачальника')
        rank=(parsed.astimezone(timezone.utc),row['qualification_id'],row['contract_id'] or '')
        if (registry_only and key in selected and rank[0]==selected[key][0][0]
                and row['scope_status']!=selected[key][1]['scope_status']):
            raise ValueError('Неоднозначний поточний статус для однакової дати допуску')
        if key not in selected or rank>selected[key][0]:selected[key]=(rank,row,stamp)
    result=[]
    status=params.get('status',[''])[0]
    for key,(_,row,stamp) in sorted(selected.items()):
        if status and row['scope_status']!=status:continue
        if registry_only and row['scope_status'] not in {'active','suspended','terminated'}:
            raise ValueError('Невідомий статус договору реєстру; експорт зупинено')
        contact=contact_from_submission(row['submission_raw'])
        label=({'active':'Активний','suspended':'Призупинений','terminated':'Неактивний'}
               .get(row['scope_status']) or {'active':'Допущено','unsuccessful':'Відхилено'}
               .get(row['qualification_status'],'Неактивний'))
        result.append({'framework_id':row['framework_id'],'submission_id':row['submission_id'],
          'values':[row['supplier_code'],row['supplier_name'] or '',stamp,label,contact['email'],contact['telephone']]})
    return result
