"""Read-only navigation counts; reuse canonical task groups and deadline control."""
from contextlib import closing
from pathlib import Path
import sqlite3

EXPIRED_REPORT_SQL = """authority_code='40996564' AND status='pending' AND PQM_RESPONSE_EXPIRED(defendant_period_end)=1
AND NOT EXISTS (SELECT 1 FROM violation_report_reviews r
 WHERE r.report_id=violation_reports.id
 AND (COALESCE(r.completed_at,'')<>'' OR r.review_status IN ('reviewed','completed')))"""


def install_deadline_function(con, deadline_control, moment):
    con.create_function('PQM_RESPONSE_EXPIRED', 1,
        lambda end: int(deadline_control({'defendant_period_end': end}, moment)['supplier_ready']))


def summary(db_path, kind, statuses, deadline_control, moment):
    with closing(sqlite3.connect(Path(db_path).resolve(strict=True).as_uri()+'?mode=ro',
                                uri=True, timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        if kind == 'tasks':
            values=sorted(statuses)
            count=con.execute('SELECT COUNT(*) FROM operational_tasks WHERE status IN ('+
                              ','.join('?' for _ in values)+')', values).fetchone()[0]
        elif kind == 'appeals':
            install_deadline_function(con, deadline_control, moment)
            count=con.execute('SELECT COUNT(*) FROM violation_reports WHERE '+EXPIRED_REPORT_SQL).fetchone()[0]
        else:
            raise ValueError('Unknown navigation counter')
    return {'count': count, 'calculated_at': moment.isoformat()}
