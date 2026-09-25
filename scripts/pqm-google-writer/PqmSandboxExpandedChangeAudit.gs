/* Temporary SANDBOX-only, read-only aggregate audit. Never invokes Full Apply. */
function pqmSandboxExpandedAuditStatus_(value, kind) {
  if (pqmGoogleBlank_(value)) return 'blank';
  var text = String(value).trim();
  if (kind === 'edr') return pqmGoogleEdrCurrentStatus_(value) || 'other';
  var allowed = ['Активний', 'Неактивний', 'Ще не в реєстрі'];
  return allowed.indexOf(text) >= 0 ? text : 'other';
}

function pqmSandboxExpandedAuditIncrement_(counts, key) {
  counts[key] = (counts[key] || 0) + 1;
}

function pqmSandboxExpandedAuditMatrix_(matrix, before, after) {
  var key = before + ' -> ' + after;
  pqmSandboxExpandedAuditIncrement_(matrix, key);
}

function pqmSandboxExpandedAuditOfficerEquivalent_(a, b) {
  return pqmGoogleOfficerComparable_(a) === pqmGoogleOfficerComparable_(b);
}

function pqmSandboxExpandedAuditEventType_(value) {
  var kind = String(value || '').trim();
  return ['admission', 'manual_edr', 'google_clarity', 'google_clarity_profile',
    'legacy_google_registry', 'google_registry'].indexOf(kind) >= 0 ?
    kind : kind ? 'other' : 'missing';
}

function pqmSandboxExpandedAuditGoogleOther_(value) {
  var text = String(value == null ? '' : value).trim()
    .replace(/^[^\p{L}\p{N}]+/u, '').trim().replace(/\s+/g, ' ');
  return text === 'Немає інформації' ? text : 'unrecognized_nonblank';
}

function pqmSandboxExpandedAuditProzorro_(value) {
  var text = String(value || '').trim().replace(/^[^\p{L}\p{N}]+/u, '').trim();
  return ['Активний', 'Неактивний', 'Ще не в реєстрі', 'Призупинений'].indexOf(text) >= 0 ?
    text : 'other';
}

function pqmSandboxExpandedAudit_(body, tabs, todayIso) {
  var plan = pqmGooglePlan_(body, tabs);
  var output = {dry_run: true, google_writes: 0, full_apply_plan_created: false,
    matched: plan.counts.matched, updated: plan.counts.updated,
    appended: plan.counts.appended, conflicts: plan.counts.conflicts,
    errors: plan.counts.errors, skipped: plan.counts.skipped,
    verification_pair_decisions: {
      google_newer_preserved: plan.counts.google_newer_preserved,
      same_date_google_officer_preserved: plan.counts.same_date_google_officer_preserved,
      same_date_equivalent: plan.counts.same_date_equivalent,
      pqm_newer_written: plan.counts.pqm_newer_written,
      google_blank_filled: plan.counts.google_blank_filled,
      pqm_blank_google_preserved: plan.counts.pqm_blank_google_preserved},
    e: {transitions: {}, planned: 0, pqm_blank_writes: 0,
      outside_known_vocabulary: 0, inactive_not_not_current: 0,
      not_registered_not_not_current: 0, active_nonregistered_requires_evidence: 0,
      other_google_source_values: {}, transitions_by_prozorro: {}},
    i: {planned: 0, google_blank_to_pqm_date: 0,
      google_nonblank_same_calendar_not_planned: 0,
      google_nonblank_different_calendar: 0, pqm_newer: 0, pqm_older: 0,
      same_day_representation_planned: 0, google_invalid_to_valid: 0,
      pqm_blank_google_nonblank_preserved: 0, blank_pqm_writes: 0,
      min_pqm_date: null, max_pqm_date: null, future_pqm_dates: 0,
      invalid_pqm_dates: 0, older_by_event_type: {}, newer_by_event_type: {},
      google_blank_by_event_type: {},
      older_google_i_equals_last_application_date: 0,
      older_google_i_equals_last_approved_application_date: 0,
      older_google_i_after_last_application_date: 0,
      older_google_i_after_last_approved_application_date: 0},
    l: {planned: 0, google_blank_to_pqm_officer: 0,
      google_nonblank_different_officer: 0,
      pqm_blank_google_nonblank_preserved: 0, blank_pqm_writes: 0,
      normalization_equivalent_planned: 0, normalization_equivalent_preserved: 0,
      newer_by_event_type: {}, same_date_by_event_type: {},
      newer_with_i_write: 0, newer_without_i_write: 0,
      google_blank_by_event_type: {}, google_blank_with_i_write: 0,
      google_blank_without_i_write: 0,
      different_officer_by_i_relation: {pqm_older: 0, pqm_newer: 0,
        same_date: 0, google_blank: 0, pqm_blank: 0, invalid_date: 0}},
    f: {planned: 0, transitions: {}, by_current_state: {}},
    h: {planned: 0, google_blank_to_pqm_date: 0,
      google_nonblank_different_calendar: 0, pqm_newer: 0,
      pqm_older: 0, same_day_representation_planned: 0,
      google_invalid_to_valid: 0, source_field: 'last_application_date'}};
  var byCode = new Map(), byRow = new Map();
  PQM_GOOGLE_TABS.forEach(function(tab) {
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      var key = tab + ':' + (index + 2);
      byRow.set(key, row);
      if (!byCode.has(code)) byCode.set(code, []);
      byCode.get(code).push({tab: tab, row: index + 2, data: row});
    });
  });
  var planned = new Map();
  plan.changes.forEach(function(change) {
    if (!change.append) planned.set(change.tab + ':' + change.row, change.cells);
  });
  body.items.forEach(function(item) {
    var matches = byCode.get(item.supplier_code.trim()) || [];
    var target = item.entity_type === 'individual_entrepreneur' ? 'ФОП' :
      item.entity_type === 'legal_entity' ? 'ЮО' : null;
    if (matches.length !== 1 || !target || matches[0].tab !== target) return;
    var match = matches[0], key = target + ':' + match.row;
    var current = byRow.get(key).values, cells = planned.get(key) || {};
    var pqmI = pqmGoogleCalendarDate_(item.verification_date);
    var googleI = pqmGoogleCalendarDate_(current[8]);
    if (pqmI.kind === 'invalid') output.i.invalid_pqm_dates++;
    if (pqmI.kind === 'date') {
      if (output.i.min_pqm_date === null || pqmI.value < output.i.min_pqm_date) output.i.min_pqm_date = pqmI.value;
      if (output.i.max_pqm_date === null || pqmI.value > output.i.max_pqm_date) output.i.max_pqm_date = pqmI.value;
      if (pqmI.value > todayIso) output.i.future_pqm_dates++;
    }
    if (pqmI.kind === 'blank' && googleI.kind !== 'blank') output.i.pqm_blank_google_nonblank_preserved++;
    if (pqmI.kind === 'date' && googleI.kind === 'date' && pqmI.value === googleI.value &&
        !Object.prototype.hasOwnProperty.call(cells, '8')) output.i.google_nonblank_same_calendar_not_planned++;
    if (pqmGoogleBlank_(item.verification_officer) && !pqmGoogleBlank_(current[11])) {
      output.l.pqm_blank_google_nonblank_preserved++;
    }
    if (!pqmGoogleBlank_(item.verification_officer) && !pqmGoogleBlank_(current[11]) &&
        current[11] !== item.verification_officer &&
        pqmSandboxExpandedAuditOfficerEquivalent_(current[11], item.verification_officer) &&
        !Object.prototype.hasOwnProperty.call(cells, '11')) {
      output.l.normalization_equivalent_preserved++;
    }
    var pqmE = pqmSandboxExpandedAuditStatus_(item.edr_status_current, 'edr');
    var prozorroState = pqmSandboxExpandedAuditProzorro_(
      item.prozorro_status_canonical || item.prozorro_status_google);
    if (pqmE === 'other') output.e.outside_known_vocabulary++;
    var pqmF = prozorroState;
    if (pqmF === 'Неактивний' && pqmE !== 'Неактуально') output.e.inactive_not_not_current++;
    if (pqmF === 'Ще не в реєстрі' && pqmE !== 'Неактуально') output.e.not_registered_not_not_current++;
    if (pqmF === 'Активний' && pqmE !== 'Зареєстровано') output.e.active_nonregistered_requires_evidence++;
    if (Object.prototype.hasOwnProperty.call(cells, '4')) {
      output.e.planned++;
      if (pqmE === 'blank') output.e.pqm_blank_writes++;
      var googleE = pqmSandboxExpandedAuditStatus_(current[4], 'edr');
      pqmSandboxExpandedAuditMatrix_(output.e.transitions,
        googleE, pqmE);
      pqmSandboxExpandedAuditIncrement_(output.e.transitions_by_prozorro,
        googleE + ' -> ' + pqmE + ' | ' + prozorroState);
      if (googleE === 'other') {
        pqmSandboxExpandedAuditIncrement_(output.e.other_google_source_values,
          pqmSandboxExpandedAuditGoogleOther_(current[4]) + ' -> ' + pqmE);
      }
    }
    if (Object.prototype.hasOwnProperty.call(cells, '8')) {
      output.i.planned++;
      if (pqmI.kind === 'blank') output.i.blank_pqm_writes++;
      if (googleI.kind === 'blank') {
        output.i.google_blank_to_pqm_date++;
        pqmSandboxExpandedAuditIncrement_(output.i.google_blank_by_event_type,
          pqmSandboxExpandedAuditEventType_(item.verification_event_type));
      }
      else if (googleI.kind === 'invalid') output.i.google_invalid_to_valid++;
      else if (pqmI.kind === 'date' && googleI.value === pqmI.value) output.i.same_day_representation_planned++;
      else if (pqmI.kind === 'date') {
        output.i.google_nonblank_different_calendar++;
        var eventType = pqmSandboxExpandedAuditEventType_(item.verification_event_type);
        if (pqmI.value > googleI.value) {
          output.i.pqm_newer++;
          pqmSandboxExpandedAuditIncrement_(output.i.newer_by_event_type, eventType);
        } else {
          output.i.pqm_older++;
          pqmSandboxExpandedAuditIncrement_(output.i.older_by_event_type, eventType);
          var lastApplication = pqmGoogleCalendarDate_(item.last_application_date);
          var lastApproved = pqmGoogleCalendarDate_(item.last_approved_application_date);
          if (lastApplication.kind === 'date') {
            if (googleI.value === lastApplication.value) output.i.older_google_i_equals_last_application_date++;
            if (googleI.value > lastApplication.value) output.i.older_google_i_after_last_application_date++;
          }
          if (lastApproved.kind === 'date') {
            if (googleI.value === lastApproved.value) output.i.older_google_i_equals_last_approved_application_date++;
            if (googleI.value > lastApproved.value) output.i.older_google_i_after_last_approved_application_date++;
          }
        }
      }
    }
    if (Object.prototype.hasOwnProperty.call(cells, '11')) {
      output.l.planned++;
      if (pqmGoogleBlank_(item.verification_officer)) output.l.blank_pqm_writes++;
      if (pqmGoogleBlank_(current[11])) {
        output.l.google_blank_to_pqm_officer++;
        pqmSandboxExpandedAuditIncrement_(output.l.google_blank_by_event_type,
          pqmSandboxExpandedAuditEventType_(item.verification_event_type));
        if (Object.prototype.hasOwnProperty.call(cells, '8')) output.l.google_blank_with_i_write++;
        else output.l.google_blank_without_i_write++;
      }
      else {
        output.l.google_nonblank_different_officer++;
        var relation = pqmI.kind === 'blank' ? 'pqm_blank' :
          googleI.kind === 'blank' ? 'google_blank' :
          pqmI.kind !== 'date' || googleI.kind !== 'date' ? 'invalid_date' :
          pqmI.value < googleI.value ? 'pqm_older' :
          pqmI.value > googleI.value ? 'pqm_newer' : 'same_date';
        output.l.different_officer_by_i_relation[relation]++;
        if (relation === 'pqm_newer') {
          pqmSandboxExpandedAuditIncrement_(output.l.newer_by_event_type,
            pqmSandboxExpandedAuditEventType_(item.verification_event_type));
          if (Object.prototype.hasOwnProperty.call(cells, '8')) output.l.newer_with_i_write++;
          else output.l.newer_without_i_write++;
        }
        if (relation === 'same_date') {
          pqmSandboxExpandedAuditIncrement_(output.l.same_date_by_event_type,
            pqmSandboxExpandedAuditEventType_(item.verification_event_type));
        }
        if (pqmSandboxExpandedAuditOfficerEquivalent_(current[11], item.verification_officer)) {
          output.l.normalization_equivalent_planned++;
        }
      }
    }
    if (Object.prototype.hasOwnProperty.call(cells, '5')) {
      output.f.planned++;
      pqmSandboxExpandedAuditMatrix_(output.f.transitions,
        pqmSandboxExpandedAuditProzorro_(current[5]), prozorroState);
      pqmSandboxExpandedAuditIncrement_(output.f.by_current_state, prozorroState);
    }
    if (Object.prototype.hasOwnProperty.call(cells, '7')) {
      output.h.planned++;
      var pqmH = pqmGoogleCalendarDate_(item.last_application_date);
      var googleH = pqmGoogleCalendarDate_(current[7]);
      if (googleH.kind === 'blank') output.h.google_blank_to_pqm_date++;
      else if (googleH.kind === 'invalid') output.h.google_invalid_to_valid++;
      else if (pqmH.kind === 'date' && pqmH.value === googleH.value) output.h.same_day_representation_planned++;
      else if (pqmH.kind === 'date') {
        output.h.google_nonblank_different_calendar++;
        if (pqmH.value > googleH.value) output.h.pqm_newer++;
        else output.h.pqm_older++;
      }
    }
  });
  output.anomalies = {unknown_planned_e_statuses: output.e.outside_known_vocabulary,
    invalid_pqm_verification_dates: output.i.invalid_pqm_dates,
    future_pqm_verification_dates: output.i.future_pqm_dates,
    same_day_i_planned: output.i.same_day_representation_planned,
    officer_normalization_only_planned: output.l.normalization_equivalent_planned,
    operational_status_mismatch: output.e.inactive_not_not_current + output.e.not_registered_not_not_current};
  return output;
}

function pqmSandboxExpandedChangeAudit() {
  var id = pqmSandboxControlledSpreadsheetId_();
  var body = pqmSandboxFetchRegistry_();
  var tabs = pqmGoogleSnapshot_(id);
  var today = Utilities.formatDate(new Date(), 'Europe/Kyiv', 'yyyy-MM-dd');
  var output = pqmSandboxExpandedAudit_(body, tabs, today);
  console.log(JSON.stringify(output));
  return output;
}
