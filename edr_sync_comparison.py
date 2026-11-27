"""EDR comparison/decision view. No writes, caches, network or startup hooks."""
import edr_sync_v2 as policy

FIELDS = ('manager_name', 'edr_status', 'full_name', 'short_name',
          'termination_decision_details', 'termination_record_date',
          'termination_record_number', 'edr_notes')


def finalize(preview):
    """Finalize one field/row plan, shared by Preview/details/XLSX/Apply."""
    detected = available = blocked = skipped = 0
    business_codes = set()
    field_counts = {field: {'detected': 0, 'available': 0, 'blocked': 0, 'skipped': 0}
                    for field in (*FIELDS, 'verification_pair')}
    ready_changes = ready_noop = 0
    helpers = {key:0 for key in ('m_note_updates','m_note_clears','google_mirror_updates',
        'google_mirror_clears','verification_event_changes','termination_changes','current_supplier_name_changes',
        'manager_changes','manager_identity_changes','manager_representation_enrichments',
        'manager_reestablishments','newly_established_managers','technical_manager_restorations','available_write_actions')}
    mirrors = set(policy.INDEPENDENT_GOOGLE_MIRROR_FIELDS)
    manager_counters = {'real_identity_change':('manager_changes','manager_identity_changes'),
        'representation_enrichment':('manager_representation_enrichments',),
        'manager_reestablished':('manager_reestablishments',),'missing_current_manager':('newly_established_managers',)}
    for plan in preview['items']:
        view, incoming = plan['current_table_values'], plan['incoming']
        candidates = set(plan['changed_fields'])
        # A source row may be blocked before a proposed change is admitted by a gate.
        decisions = []
        write_fields = set()
        plan['manager_restoration_allowed'] = False
        row_blocked = bool(plan['conflicts']) or plan['row_state'] == 'conflict'
        independent_mirrors = bool(not preview['sandbox_mode'] and plan.get('independent_mirror_only'))
        row_skipped = plan['row_state'] == 'skipped' or not plan['apply_allowed']
        manager = plan['current_manager_evidence']
        manual = str(manager.get('source') or '').startswith('Підтверджено УО')
        manual_wins = False
        if manual:
            manual_at = policy.verification_instant(manager.get('updated_at'))
            incoming_at = policy.verification_instant(incoming.get('edr_checked_at'))
            manual_wins = bool(manual_at['kind']=='datetime' and
                incoming_at['kind']=='datetime' and manual_at['value'] >= incoming_at['value'])
        for field in FIELDS:
            current = view.get(field, '')
            google = incoming.get('edr_status_source', '') if field == 'edr_status' else incoming.get(field, '')
            # Empty names/managers are not destructive source proposals.
            different = current != google and not policy._same(field, current, google)
            restoration = (field=='manager_name' and not different and field in candidates and
                plan['manager_change_kind'] in {'manager_reestablished','missing_current_manager'})
            if not different and not restoration:
                continue
            verdict = ('blocked' if row_blocked and not (independent_mirrors and field in mirrors) else 'skipped' if row_skipped or field not in candidates
                       or (field=='manager_name' and manual_wins)
                       else 'available')
            if verdict == 'available' and not restoration:
                write_fields.add(field)
            if restoration and verdict=='available':plan['manager_restoration_allowed']=True
            decisions.append({'field': field, 'current': current, 'google': google,
                              'planned': google if verdict == 'available' else current,
                              'verdict': verdict,
                              'is_difference':different,
                              'reason': 'newer_manual_value_preserved' if field=='manager_name' and manual_wins else ''})
        pair_changed = bool(plan['verification_event_change'])
        pair_different = (bool(view.get('edr_checked_at') or incoming['edr_checked_at']) and
            plan['datetime_gate']['reason'] != 'equal') or not policy._same(
                'manager_name',view.get('edr_officer',''),incoming['edr_officer'])
        if pair_changed or pair_different:
            verdict = 'blocked' if row_blocked else 'skipped' if row_skipped or not pair_changed else 'available'
            if verdict == 'available':
                write_fields.update(('edr_checked_at', 'edr_officer'))
            current_pair = {'date':view.get('edr_checked_at',''),'officer':view.get('edr_officer',''),
                'precision':plan['current_verification_precision']}
            google_pair = {'date':incoming['edr_checked_at'],'officer':incoming['edr_officer'],
                'precision':policy.decision_datetime_precision(incoming['edr_checked_at'])}
            decisions.append({'field': 'verification_pair',
                'current':current_pair,'google':google_pair,
                'planned':google_pair if verdict=='available' else current_pair,
                'verdict': verdict,'reason':plan['datetime_gate']['reason'] if not pair_changed else ''})
        plan['field_decisions'] = decisions
        plan['write_fields'] = sorted(write_fields)
        plan['changed_fields'] = sorted(write_fields - {'edr_checked_at', 'edr_officer'})
        raw = plan['current_profile']
        profile_delta = any(str(raw.get(f) or '') != str(incoming.get(f) or '') for f in write_fields)
        plan['business_change_expected'] = bool(profile_delta or
            (pair_changed and not row_blocked and not row_skipped) or not plan['existing_profile'])
        if (not row_blocked or independent_mirrors) and not row_skipped:
            if plan['business_change_expected']:
                ready_changes += 1;business_codes.add(plan['supplier_code'])
            else:
                ready_noop += 1
            helpers['verification_event_changes'] += int(pair_changed)
            helpers['termination_changes'] += int(bool(write_fields & (mirrors-{'edr_notes'})))
            helpers['current_supplier_name_changes'] += int('full_name' in write_fields and
                plan['current_supplier_name'] != plan['planned_supplier_name'])
            if 'manager_name' in write_fields or plan['manager_restoration_allowed']:
                for key in manager_counters.get(plan['manager_change_kind'],()):helpers[key] += 1
        for decision in decisions:
            if decision['verdict']=='available':helpers['available_write_actions'] += 1
            if decision.get('is_difference') is False:
                if decision['verdict']=='available':helpers['technical_manager_restorations'] += 1
                continue
            detected += 1;field_counts[decision['field']]['detected'] += 1
            field_counts[decision['field']][decision['verdict']] += 1
            if decision['verdict'] == 'available':
                available += 1
                suffix='updates' if str(decision['google'] or '').strip() else 'clears'
                if decision['field'] in mirrors:helpers['google_mirror_'+suffix] += 1
                if decision['field']=='edr_notes':helpers['m_note_'+suffix] += 1
            elif decision['verdict'] == 'blocked': blocked += 1
            else: skipped += 1
    summary = preview['summary']
    summary.update(detected_differences=detected, available_changes=available,
        blocked_changes=blocked, skipped_changes=skipped,
        ready_to_apply=ready_changes + ready_noop, ready_with_changes=ready_changes,
        ready_unchanged=ready_noop, changed_suppliers=len(business_codes),
        no_op_suppliers=ready_noop, technical_receipts=ready_changes + ready_noop,
        field_counts=field_counts)
    # Legacy displayed helper counters now describe executable changes only.
    for field in ('edr_status','full_name','short_name'):
        summary[field + '_changes'] = field_counts[field]['available']
    summary.update(helpers)
    return preview


def details(preview):
    categories = {'edr_status':'edr_status', 'verification_pair':'verification',
                  'manager_name':'names_manager','full_name':'names_manager','short_name':'names_manager'}
    rows=[]
    for plan in preview['items']:
        base={'supplier_code':plan['supplier_code'],'supplier_name':plan['current_supplier_name']
              or plan['incoming']['full_name'],'source_sheet':plan['source_sheet'],
              'source_row':plan['source_row'],'row_state':plan['row_state']}
        for d in plan['field_decisions']:
            action = ('restore_current_manager' if d.get('is_difference') is False else 'clear' if not str(d['google'] or '').strip() else
                      'accept_google_pair' if d['field']=='verification_pair' else 'update')
            rows.append({**base,'field':d['field'],'category':categories.get(d['field'],'gjkm'),
                'current_pqm_value':d['current'],'google_value':d['google'],
                'planned_pqm_value':d['planned'],'action':action if d['verdict']=='available' else d['verdict'],
                'reason':plan['conflicts'] if d['verdict']=='blocked' else d.get('reason') or
                         plan['skip_reasons'] if d['verdict']=='skipped' else 'approved_field_plan'})
        if plan['conflicts']:
            rows.append({**base,'field':'conflict','category':'conflicts','current_pqm_value':'',
                'google_value':'','planned_pqm_value':'','action':'blocked','reason':plan['conflicts']})
        elif plan['row_state']=='skipped':
            rows.append({**base,'field':'row_status','category':'skipped','current_pqm_value':'',
                'google_value':'','planned_pqm_value':'','action':'skip','reason':plan['skip_reasons']})
    return rows
