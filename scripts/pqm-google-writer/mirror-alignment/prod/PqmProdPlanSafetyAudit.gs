/* Aggregate-only PROD diagnostic. No mutation or Apply call is reachable here. */
function pqmProdPlanSafetyAuditStatus_(value, kind) {
  if (pqmGoogleBlank_(value)) return 'blank';
  var text = String(value).trim().replace(/\s+/g, ' ');
  if (kind === 'F') {
    var statuses = ['Активний', 'Неактивний', 'Ще не в реєстрі', 'Призупинений'];
    var plain = text.replace(/^[^\p{L}\p{N}]+/u, '').trim();
    return statuses.indexOf(plain) >= 0 ? plain : 'other/unknown';
  }
  var edr = ['Зареєстровано', 'Неактуально', 'Припинено',
    'В стані припинення', 'Порушено справу про банкрутство', 'Банкрут'];
  var canonical = text.replace(/^[^\p{L}\p{N}]+/u, '').trim();
  if (canonical.toLocaleLowerCase('uk-UA') === 'немає інформації') return 'Немає інформації';
  return edr.indexOf(canonical) >= 0 ? canonical : 'other/unknown';
}

function pqmProdPlanSafetyAuditIncrement_(bucket, key) {
  bucket[key] = (bucket[key] || 0) + 1;
}

function pqmProdPlanSafetyAudit_(body, tabs, plan) {
  var google = new Map(), items = new Map(), planned = new Map();
  var sheetCounts = new Map(), apiCounts = new Map();
  PQM_GOOGLE_TABS.forEach(function(tab) {
    tabs[tab].rows.forEach(function(row) {
      var code = String(row.codeDisplay === undefined ? row.values[1] || '' : row.codeDisplay).trim();
      if (code) {
        google.set(code, row);
        sheetCounts.set(code, (sheetCounts.get(code) || 0) + 1);
      }
    });
  });
  body.items.forEach(function(item) {
    var code = item.supplier_code.trim();
    items.set(code, item);
    apiCounts.set(code, (apiCounts.get(code) || 0) + 1);
  });
  var result = {
    dry_run: true, google_writes: 0, db_writes: 0,
    total_pqm_suppliers: body.count, planner_counts: plan.counts,
    f: {planned: 0, transitions: {}, google_blank_to_value: 0, value_to_value: 0,
      planned_blank_count: 0, unknown_source_status_count: 0, unknown_planned_status_count: 0},
    h: {planned: 0, google_blank_to_decided_date: 0, pqm_decided_date_newer: 0,
      google_date_newer_than_pqm_decided_date: 0, same_calendar_date_representation_only: 0,
      invalid_google_date: 0, invalid_pqm_decided_date: 0, other: 0,
      suppliers_with_newer_pending_than_latest_decided: null,
      newer_undecided_date_than_latest_decided: 0,
      h_planned_for_those_suppliers: 0, h_uses_pending_date_count: 0,
      pending_status_available_in_payload: false},
    e: {planned: 0, transitions: {}, google_no_information_preserved: 0,
      google_no_information_planned: 0, special_factual_preserved: 0,
      unknown_google_status_count: 0, unknown_planned_status_count: 0,
      planned_blank_count: 0},
    skipped: {pending_only: null, no_decided_application: 0,
      unsupported_entity_type: 0, missing_required_identity: 0,
      not_google_sync_eligible_other: 0, other: 0,
      pending_status_available_in_payload: false, classified_total: 0,
      matches_planner_skipped: false},
    eligible_missing_google: {supported_type: 0, unsupported_type: 0,
      total: 0, unsupported_entity_types: {}},
    append: {planner_append_candidates: plan.counts.appended,
      append_count_matches_eligible_missing: false,
      discrepancy_reasons: {}},
    verification_pairs: {google_newer_preserved: plan.counts.google_newer_preserved,
      same_date_google_officer_preserved: plan.counts.same_date_google_officer_preserved,
      same_date_equivalent: plan.counts.same_date_equivalent,
      pqm_newer_written: plan.counts.pqm_newer_written,
      google_blank_filled: plan.counts.google_blank_filled,
      pqm_blank_google_preserved: plan.counts.pqm_blank_google_preserved,
      planned_i: 0, planned_l: 0, i_l_pair_mismatch_count: 0}
  };
  plan.changes.forEach(function(change) {
    var row = change.append ? null : tabs[change.tab].rows[change.row - 2];
    var code = change.append ? String(change.cells[1] || '').trim() :
      String(row && row.codeDisplay || '').trim();
    var item = items.get(code), cells = change.cells;
    if (!change.append) planned.set(code, cells);
    var hasI = Object.prototype.hasOwnProperty.call(cells, '8');
    var hasL = Object.prototype.hasOwnProperty.call(cells, '11');
    if (hasI) result.verification_pairs.planned_i++;
    if (hasL) result.verification_pairs.planned_l++;
    if (hasI !== hasL) result.verification_pairs.i_l_pair_mismatch_count++;
    if (!row) return;
    if (Object.prototype.hasOwnProperty.call(cells, '5')) {
      var fBefore = pqmProdPlanSafetyAuditStatus_(row.values[5], 'F');
      var fAfter = pqmProdPlanSafetyAuditStatus_(cells[5], 'F');
      result.f.planned++;
      pqmProdPlanSafetyAuditIncrement_(result.f.transitions, fBefore + ' -> ' + fAfter);
      if (fBefore === 'blank') result.f.google_blank_to_value++;
      else result.f.value_to_value++;
      if (fAfter === 'blank') result.f.planned_blank_count++;
      if (fBefore === 'other/unknown') result.f.unknown_source_status_count++;
      if (fAfter === 'other/unknown') result.f.unknown_planned_status_count++;
    }
    if (Object.prototype.hasOwnProperty.call(cells, '7')) {
      var googleH = pqmGoogleCalendarDate_(row.values[7]);
      var decidedH = pqmGoogleCalendarDate_(item && item.google_sync_last_decided_application_date);
      result.h.planned++;
      if (googleH.kind === 'invalid') result.h.invalid_google_date++;
      else if (decidedH.kind === 'invalid') result.h.invalid_pqm_decided_date++;
      else if (googleH.kind === 'blank' && decidedH.kind === 'date') result.h.google_blank_to_decided_date++;
      else if (googleH.kind === 'date' && decidedH.kind === 'date' && decidedH.value > googleH.value)
        result.h.pqm_decided_date_newer++;
      else if (googleH.kind === 'date' && decidedH.kind === 'date' && googleH.value > decidedH.value)
        result.h.google_date_newer_than_pqm_decided_date++;
      else if (googleH.kind === 'date' && decidedH.kind === 'date' && googleH.value === decidedH.value)
        result.h.same_calendar_date_representation_only++;
      else result.h.other++;
    }
    if (Object.prototype.hasOwnProperty.call(cells, '4')) {
      var eBefore = pqmProdPlanSafetyAuditStatus_(row.values[4], 'E');
      var eAfter = pqmProdPlanSafetyAuditStatus_(cells[4], 'E');
      result.e.planned++;
      pqmProdPlanSafetyAuditIncrement_(result.e.transitions, eBefore + ' -> ' + eAfter);
      if (eBefore === 'Немає інформації') result.e.google_no_information_planned++;
      if (eBefore === 'other/unknown') result.e.unknown_google_status_count++;
      if (eAfter === 'other/unknown') result.e.unknown_planned_status_count++;
      if (eAfter === 'blank') result.e.planned_blank_count++;
    }
  });
  var factual = ['Припинено', 'В стані припинення',
    'Порушено справу про банкрутство', 'Банкрут'];
  body.items.forEach(function(item) {
    var code = item.supplier_code.trim(), row = google.get(code);
    var supported = item.entity_type === 'individual_entrepreneur' || item.entity_type === 'legal_entity';
    if (!item.google_sync_eligible) {
      // The API exposes decision existence, not the latest application's literal status.
      result.skipped.no_decided_application++;
    } else if ((sheetCounts.get(code) || 0) > 1 || (apiCounts.get(code) || 0) > 1) {
      // Duplicates are planner conflicts, not skipped suppliers.
    } else if (!supported) {
      result.skipped.unsupported_entity_type++;
    }
    if (item.google_sync_eligible && !row) {
      result.eligible_missing_google.total++;
      if (supported) result.eligible_missing_google.supported_type++;
      else {
        result.eligible_missing_google.unsupported_type++;
        pqmProdPlanSafetyAuditIncrement_(result.eligible_missing_google.unsupported_entity_types,
          item.entity_type);
      }
    }
    if (row && item.google_sync_eligible && supported) {
      var currentE = pqmProdPlanSafetyAuditStatus_(row.values[4], 'E');
      var change = planned.get(code) || {};
      if (currentE === 'Немає інформації' && !Object.prototype.hasOwnProperty.call(change, '4'))
        result.e.google_no_information_preserved++;
      if (factual.indexOf(currentE) >= 0 && !Object.prototype.hasOwnProperty.call(change, '4'))
        result.e.special_factual_preserved++;
    }
    var latest = pqmGoogleCalendarDate_(item.last_application_date);
    var decided = pqmGoogleCalendarDate_(item.google_sync_last_decided_application_date);
    if (latest.kind === 'date' && decided.kind === 'date' && latest.value > decided.value) {
      result.h.newer_undecided_date_than_latest_decided++;
      var selected = planned.get(code) || {};
      if (Object.prototype.hasOwnProperty.call(selected, '7')) {
        result.h.h_planned_for_those_suppliers++;
        if (pqmGoogleCalendarDate_(selected[7]).value === latest.value)
          result.h.h_uses_pending_date_count++;
      }
    }
  });
  result.skipped.classified_total = result.skipped.no_decided_application +
    result.skipped.unsupported_entity_type + result.skipped.missing_required_identity +
    result.skipped.not_google_sync_eligible_other + result.skipped.other;
  result.skipped.matches_planner_skipped = result.skipped.classified_total === plan.counts.skipped;
  result.append.append_count_matches_eligible_missing =
    result.append.planner_append_candidates === result.eligible_missing_google.supported_type;
  if (!result.append.append_count_matches_eligible_missing) {
    result.append.discrepancy_reasons.planner_conflicts = plan.counts.conflicts;
    result.append.discrepancy_reasons.planner_errors = plan.counts.errors;
  }
  return result;
}

function pqmProdPlanSafetyAudit() {
  var id = pqmProdControlledSpreadsheetId_();
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM PROD: another audit is running; no writes.');
  try {
    var body = pqmProdFetchRegistry_();
    var tabs = pqmGoogleSnapshot_(id);
    var plan = pqmGooglePlan_(body, tabs);
    var output = pqmProdPlanSafetyAudit_(body, tabs, plan);
    console.log(JSON.stringify(output));
    return output;
  } finally { lock.releaseLock(); }
}
