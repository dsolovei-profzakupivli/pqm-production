"""Read-only admission evidence shared by exports and optional EDR projections.

No EDR projection, officer assignment, Google transport, migration or writes.
"""
import json
import re
from datetime import datetime, timezone


def source_instant(value):
    if not isinstance(value,str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})',value):
        return None
    offset=re.search(r'([+-])(\d{2}):(\d{2})$',value)
    if offset and (int(offset[2])>14 or int(offset[3])>59 or (int(offset[2])==14 and int(offset[3])!=0)):
        return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,OverflowError):return None


def object_json(value):
    try:result=json.loads(value or '{}')
    except (ValueError,TypeError):return {}
    return result if isinstance(result,dict) else {}


def qualification_stamp(status,qualification_id,submission_id,raw_json):
    raw=object_json(raw_json)
    stamp=raw.get('date')
    if (status=='active' and raw.get('status')=='active' and qualification_id and submission_id
            and raw.get('id')==qualification_id and raw.get('submissionID')==submission_id
            and source_instant(stamp) is not None):
        return stamp
    return ''


def event_instant(value):
    parsed=source_instant(value)
    if parsed is not None:return parsed
    # Existing baseline parser is used only for legacy persisted evidence.
    # No changes to the Google datetime contract are required by this module.
    from google_verification_contract import verification_instant
    legacy=verification_instant(value)
    return legacy['value'] if legacy['kind']=='datetime' else None


def historical_admission_stamp(event):
    if event.get('event_type')!='admission' or not event_instant(event.get('occurred_at')):return ''
    sid=event.get('source_submission_id')
    if not sid:return ''
    proof=object_json(event.get('snapshot_json'))
    if proof.get('submission_id')==sid and proof.get('decision')=='admit':return event['occurred_at']
    from google_verification_contract import verified_admission_signature
    return event['occurred_at'] if verified_admission_signature(event) else ''


def _columns(con,table):
    # All callers supply fixed table names, never request parameters.
    return {r[1] for r in con.execute('PRAGMA table_info('+table+')')}


def batches(codes):
    values=sorted(set(codes))
    for i in range(0,len(values),400):yield values[i:i+400]


def current_admissions(con,codes):
    if not {'id','status','submission_id','raw_json'}<=_columns(con,'qualifications'):return []
    if not {'id','supplier_code','qualification_id'}<=_columns(con,'submissions'):return []
    result=[]
    for batch in batches(codes):
        marks=','.join('?' for _ in batch)
        for row in con.execute(f'''SELECT s.supplier_code,s.id submission_id,q.id qualification_id,
          q.status,q.raw_json FROM submissions s JOIN qualifications q
          ON q.id=s.qualification_id AND q.submission_id=s.id
          WHERE q.status='active' AND s.supplier_code IN ({marks})''',batch):
            row=dict(row)
            stamp=qualification_stamp(row['status'],row['qualification_id'],row['submission_id'],row['raw_json'])
            if stamp:result.append({'supplier_code':row['supplier_code'],'event_type':'admission',
              'occurred_at':stamp,'source_submission_id':row['submission_id'],
              'qualification_id':row['qualification_id'],'source':'Prozorro qualification.date'})
    return result


def admission_events(con,codes):
    result=current_admissions(con,codes)
    if not _columns(con,'supplier_edr_verification_events'):return result
    for batch in batches(codes):
        marks=','.join('?' for _ in batch)
        for raw in con.execute(f'''SELECT * FROM supplier_edr_verification_events
          WHERE event_type='admission' AND supplier_code IN ({marks})''',batch):
            event=dict(raw)
            if historical_admission_stamp(event):result.append(event)
    return result
