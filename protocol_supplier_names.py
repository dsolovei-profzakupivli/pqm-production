"""Read-only provenance for the deployed protocol name selection rules.

No qualification-submission fallback, manual override, storage, or eligibility
rules are introduced. Document and download filename priorities differ on the
deployed baseline and must remain separate until explicitly approved otherwise.
"""


def resolve(item, normalize):
    verified=item.get('supplier_verified') or {}
    defendant=item.get('defendant_name') or ''
    def value(text,source,path):
        return {'value':text,'source':source,'source_path':path,
                'source_label':{'edr':'З ЄДР (збережені дані PQM)',
                  'prozorro_violation':'Зі звернення Prozorro',
                  'missing':'Не визначено'}[source]}
    full_raw=verified.get('full_name') or defendant
    full=value(normalize(full_raw),
               'edr' if verified.get('full_name') else ('prozorro_violation' if defendant else 'missing'),
               'supplier_edr_profiles.full_name' if verified.get('full_name') else 'defendants[0]')
    if verified.get('short_name'):
        short=value(normalize(verified['short_name']),'edr','supplier_edr_profiles.short_name')
    else:
        short={**full,'value':normalize(full['value'])}
    # Filename first_name() ignores whitespace-only strings; document selection
    # above retains the deployed truthiness + normalization behavior exactly.
    filename_raw=next((str(v).strip() for v in (verified.get('short_name'),defendant)
                       if v is not None and str(v).strip()),'')
    if str(verified.get('short_name') or '').strip():
        filename=value(filename_raw,'edr','supplier_edr_profiles.short_name')
    else:
        filename=value(filename_raw,'prozorro_violation' if filename_raw else 'missing','defendants[0]')
    return {'full_name':full,'short_name':short,'filename_name':filename,
            'uses_fallback':any(v['source']=='prozorro_violation' for v in (full,short,filename))}
