"""Resolve current EDR names and safe fallbacks for newly generated documents."""
import document_quotes


def resolve(item, normalize):
    verified=item.get('supplier_verified') or {}
    def usable(value):
        text=str(value or '').strip()
        return '' if text in {'—','–','-'} else text
    defendant=usable(item.get('defendant_name'))
    def value(text,source,path):
        return {'value':document_quotes.normalize_output_quotes(text),'source':source,'source_path':path,
                'source_label':{'edr':'З ЄДР (збережені дані PQM)',
                  'prozorro_violation':'Зі звернення Prozorro',
                  'missing':'Не визначено'}[source]}
    edr_full=usable(verified.get('full_name'))
    edr_short=usable(verified.get('short_name'))
    full_raw=edr_full or defendant
    full=value(normalize(full_raw),
               'edr' if edr_full else ('prozorro_violation' if defendant else 'missing'),
               'supplier_edr_profiles.full_name' if edr_full else 'defendants[0]')
    if edr_short:
        short=value(normalize(edr_short),'edr','supplier_edr_profiles.short_name')
    else:
        short={**full,'value':normalize(full['value'])}
    filename_raw=edr_short or edr_full or defendant
    if edr_short:
        filename=value(normalize(filename_raw),'edr','supplier_edr_profiles.short_name')
    elif edr_full:
        filename=value(normalize(filename_raw),'edr','supplier_edr_profiles.full_name')
    else:
        filename=value(normalize(filename_raw),'prozorro_violation' if filename_raw else 'missing','defendants[0]')
    return {'full_name':full,'short_name':short,'filename_name':filename,
            'uses_fallback':any(v['source']=='prozorro_violation' for v in (full,short,filename))}
