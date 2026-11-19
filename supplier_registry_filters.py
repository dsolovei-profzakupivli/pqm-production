"""Read-model scope helpers; string CPV codes retain leading zeroes."""
import supplier_selection


def values(params, key):
    return sorted({part.strip() for value in params.get(key, [])
                   for part in str(value or '').split(',') if part.strip()})


def dk_scope(params, alias='f'):
    codes=values(params,'dk_code')
    return (alias+'.dk_code IN ('+','.join('?' for _ in codes)+')', codes) if codes else ('1=1', [])


def selection(params):
    # Keep the shared XLSX admission selector untouched. Extend only the list's
    # qualification scope; DK/framework/status intersect before aggregation.
    sql,args=supplier_selection.selection_sql({**params,'dk_code':['']})
    predicate,codes=dk_scope(params)
    token="(?='' OR f.dk_code=?)"
    assert sql.count(token)==1
    return sql.replace(token,predicate), [*codes,*args[2:]]
