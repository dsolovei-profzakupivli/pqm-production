"""Shared latest-submission contacts for supplier card and document context."""
import json
import re


def supplier_contacts(con, supplier_code):
    current = None
    history = []
    seen = set()
    for index, row in enumerate(con.execute("""SELECT s.id,s.date_published,s.raw_json,
      COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id
      FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
      WHERE DIGITS(s.supplier_code)=?
      ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""",
      (re.sub(r'\D', '', str(supplier_code or '')),))):
        try:
            payload = json.loads(row['raw_json'] or '{}')
        except (TypeError, json.JSONDecodeError):
            payload = {}
        tenderers = payload.get('tenderers') or [] if isinstance(payload, dict) else []
        contact = tenderers[0].get('contactPoint') if tenderers and isinstance(tenderers[0], dict) else {}
        contact = contact if isinstance(contact, dict) else {}
        values = tuple(' '.join(str(contact.get(field) or '').split())
                       for field in ('name', 'email', 'telephone', 'fax', 'url'))
        item = dict(zip(('name', 'email', 'telephone', 'fax', 'url'), values))
        item.update(submission_id=row['id'], submission_date=row['date_published'], framework_id=row['framework_id'])
        key = tuple(value.casefold() for value in values)
        if index == 0:
            current = item  # Even empty contacts belong to the latest submission.
        elif any(values) and key not in seen:
            history.append(item)
        seen.add(key)
    return {'current': current, 'history': history}


def supplier_email(con, supplier_code):
    """Document resolver; existing card context can reuse current.email directly."""
    return (supplier_contacts(con, supplier_code)['current'] or {}).get('email') or None
