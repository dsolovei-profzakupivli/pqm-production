"""Read-only supplier list scope, independent of the XLSX admission selector."""


def values(params, key):
    raw = params.get(key, [])
    if isinstance(raw, str):
        raw = [raw]
    return sorted({part.strip() for value in raw
                   for part in str(value or '').split(',') if part.strip()})


def predicate(params):
    """Both groups apply to the same joined framework, before aggregation."""
    clauses, args = [], []
    for key, column in (('dk_code', 'f.dk_code'), ('framework_id', 'f.id')):
        selected = values(params, key)
        if selected:
            clauses.append(column + ' IN (' + ','.join('?' for _ in selected) + ')')
            args.extend(selected)
    return ' AND '.join(clauses) or '1=1', args
