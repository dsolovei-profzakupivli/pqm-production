/* Canonical PQM → Google business-event planner for UPDATE + APPEND. */
function pqmGoogleSafeAppendFormula_(formula, row) {
  if (typeof formula !== 'string' || !/^=/.test(formula)) return false;
  var text = formula.replace(/"(?:[^\"]|"")*"/g, '""');
  if (/[{}!:\[\];]/.test(text)) return false;
  var references = text.match(/\$?[B-O]\$?\d+/gi) || [];
  if (!references.length || references.some(function(ref) { return Number(ref.match(/\d+$/)[0]) !== row; })) return false;
  text = text.replace(/\$?[B-O]\$?\d+/gi, '0');
  if ((text.match(/[A-Z_][A-Z_0-9]*\s*\(/gi) || []).some(function(fn) {
    return !/^(IF|IFERROR|AND|OR|NOT|LEN|ISBLANK)\s*\($/i.test(fn);
  })) return false;
  text = text.replace(/\b(IF|IFERROR|AND|OR|NOT|LEN|ISBLANK|TRUE|FALSE)\b/gi, '');
  return !/[^\s0-9=+\-*/^%<>&(),."]/ .test(text);
}

function pqmGoogleTranslatedAppendFormula_(formula, templateRow, targetRow) {
  if (!pqmGoogleSafeAppendFormula_(formula, templateRow)) throw new Error('PQM: unsafe append formula A.');
  return formula.replace(/"(?:[^\"]|"")*"|\$?[B-O](\$?)(\d+)/gi, function(ref, fixed, row) {
    if (ref.charAt(0) === '"' || fixed === '$') return ref;
    return ref.slice(0, ref.length - row.length) + String(Number(row) + targetRow - templateRow);
  });
}

function pqmGoogleMatrixVerification_(value, precision) {
  if (pqmGoogleBlank_(value)) return {kind: 'blank'};
  var dateOnly = precision === 'day' ||
    (precision !== 'datetime' && typeof value === 'number' && Math.abs(value - Math.floor(value)) < 1e-9) ||
    (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.trim()));
  if (dateOnly) {
    // A date-only check is the same Kyiv-local midnight used by the Python
    // Google → PQM gate. Keep date-only cells as dates when writing; only the
    // comparison uses this midnight instant.
    if (Object.prototype.toString.call(value) === '[object Date]') {
      var dateInstant = pqmVerificationDatetime_(value);
      return dateInstant.kind === 'datetime' ? dateInstant : {kind: 'invalid'};
    }
    var date = pqmGoogleCalendarDate_(value);
    if (date.kind !== 'date') return {kind: 'invalid'};
    var midnight = pqmVerificationDatetime_(date.value);
    return midnight.kind === 'datetime' ? midnight : {kind: 'invalid'};
  }
  var instant = pqmVerificationDatetime_(value);
  return instant.kind === 'datetime' ? instant : {kind: instant.kind};
}

function pqmGoogleMatrixSourceVerification_(item) {
  var state = pqmGoogleMatrixVerification_(item.verification_date,
    item.verification_datetime_precision);
  if (state.kind !== 'blank' && state.kind !== 'invalid') return state;
  if (state.kind === 'blank' && item.google_sync_last_decided_application_decision === 'admit' &&
      !pqmGoogleBlank_(item.google_sync_last_decided_protocol_at)) {
    return pqmGoogleMatrixVerification_(item.google_sync_last_decided_protocol_at, '');
  }
  return state;
}

function pqmGoogleMatrixNumber_(state) {
  return state.kind === 'datetime' ? pqmVerificationSerial_(state.value) : pqmGoogleDate_(state.date);
}

function pqmGoogleBusinessSchema_(items) {
  items.forEach(function(item) {
    if (typeof item.google_writer_eligible !== 'boolean' ||
        typeof item.google_sync_has_active_qualification !== 'boolean' ||
        typeof item.google_sync_has_admission_history !== 'boolean' ||
        typeof item.classification_version !== 'string' ||
        typeof item.classification_status !== 'string' ||
        typeof item.classification_reason !== 'string' ||
        typeof item.classification_reason_label !== 'string' ||
        typeof item.append_allowed !== 'boolean' ||
        !(item.target_sheet === null || item.target_sheet === 'ФОП' || item.target_sheet === 'ЮО') ||
        ['google_sync_last_decided_application_decision', 'google_sync_last_decided_protocol_at',
          'google_sync_last_decided_protocol_officer', 'google_sync_last_decided_submission_id',
          'google_sync_latest_rejection_officer'].some(function(key) {
          return !Object.prototype.hasOwnProperty.call(item, key) ||
            (item[key] !== null && typeof item[key] !== 'string');
        })) throw new Error('PQM: business/classification schema mismatch.');
  });
}

function pqmGoogleBusinessPlan_(body, tabs, options) {
  options = options || {};
  pqmGoogleSchema_(body);
  pqmGoogleBusinessSchema_(body.items);
  var result = pqmGoogleCounts_(), perTab = {}, issues = [], gaps = [], changes = [], index = new Map(), apiKeys = new Map();
  result.api_records = body.items.length;
  function issue(reason, key, tab, detail) { issues.push({reason: reason, supplier_code: key, tab: tab || null, detail: detail || null}); }
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name]; perTab[name] = pqmGoogleCounts_();
    if (!tab || JSON.stringify(tab.headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) throw new Error('PQM: header mismatch: ' + name);
    tab.rows.forEach(function(row, i) {
      var key = String(row.codeDisplay === undefined ? (row.values[1] == null ? '' : row.values[1]) : row.codeDisplay);
      if (!key) return;
      if (!index.has(key)) index.set(key, []);
      index.get(key).push({tab: name, row: i + 2, data: row});
    });
  });
  body.items.forEach(function(item) { var key = item.supplier_code; apiKeys.set(key, (apiKeys.get(key) || 0) + 1); });
  // Keep literal identifiers distinct. Whitespace-stripped forms are used
  // only to detect ambiguous aliases; they never become lookup or write keys.
  var textAliases = new Map(), identityConflicts = new Set();
  new Set(Array.from(index.keys()).concat(Array.from(apiKeys.keys()))).forEach(function(key) {
    var diagnosticKey = key.replace(/\s/g, '');
    if (!textAliases.has(diagnosticKey)) textAliases.set(diagnosticKey, []);
    textAliases.get(diagnosticKey).push(key);
  });
  textAliases.forEach(function(keys) { if (keys.length > 1) keys.forEach(function(key) { identityConflicts.add(key); }); });
  var duplicates = new Set();
  index.forEach(function(rows, key) { if (rows.length > 1) duplicates.add(key); });
  apiKeys.forEach(function(count, key) { if (count > 1) duplicates.add(key); });
  result.duplicate_keys = duplicates.size;
  var nextRows = {};
  PQM_GOOGLE_TABS.forEach(function(name) { nextRows[name] = tabs[name].rows.length + 2; });
  body.items.forEach(function(item) {
    var key = item.supplier_code;
    var tabName = item.target_sheet === 'ФОП' || item.target_sheet === 'ЮО' ? item.target_sheet : null;
    function count(name) { result[name]++; if (tabName) perTab[tabName][name]++; }
    if (tabName) perTab[tabName].api_records++;
    if (identityConflicts.has(key)) { count('conflicts'); issue('identifier_text_conflict', key, tabName); return; }
    if (item.classification_status === 'nonresident' || item.entity_type === 'foreign_legal_entity') {
      count('skipped'); issue('nonresident_append_blocked', key, null, item.classification_reason_label || 'Нерезидент: автоматичне додавання поки вимкнено'); return;
    }
    if (item.entity_type === 'unknown' || item.classification_status === 'conflict' ||
        item.classification_status === 'needs_review') {
      count('conflicts'); issue(item.classification_reason || 'entity_type_unresolved', key, null,
        item.classification_reason_label || 'Потрібна перевірка типу постачальника'); return;
    }
    var expectedTab = item.entity_type === 'individual_entrepreneur' ? 'ФОП' :
      item.entity_type === 'legal_entity' ? 'ЮО' : null;
    if (item.classification_version !== 'subject-nature-20261030-v2' ||
        item.classification_status !== 'resolved' || item.append_allowed !== true ||
        !expectedTab || item.target_sheet !== expectedTab) {
      count('conflicts'); issue('classification_contract_unverified', key, tabName,
        item.classification_reason_label || 'Потрібна перевірка типу постачальника'); return;
    }
    if (!item.google_writer_eligible) { count('skipped'); issue('no_decided_application_event', key, tabName); return; }
    if (duplicates.has(key)) { count('conflicts'); issue('duplicate_key', key, tabName); return; }
    if (!tabName) { count('conflicts'); issue('classification_target_missing', key, null,
      item.classification_reason_label || 'Не визначено вкладку для підтвердженого типу'); return; }
    var found = (index.get(key) || [])[0];
    if (found && found.tab !== tabName) { count('conflicts'); issue('routing_mismatch', key, tabName); return; }
    if (found) count('matched');
    if (found && options.appendOnly === true) { count('unchanged'); return; }
    if (found && tabs[tabName].merges.some(function(range) {
      return (range.startRowIndex || 0) <= found.row - 1 && range.endRowIndex >= found.row &&
        PQM_GOOGLE_OWNED.some(function(column) { return column >= (range.startColumnIndex || 0) && column < range.endColumnIndex; });
    })) { count('conflicts'); issue('merged_owned_cell', key, tabName); return; }
    if (found && PQM_GOOGLE_OWNED.some(function(column) { return !!found.data.formulas[column]; })) {
      count('conflicts'); issue('formula_in_owned_cell', key, tabName); return;
    }
    var tab = tabs[tabName], template = !found && tab.rows.length ? tab.rows[tab.rows.length - 1] : null;
    if (!found && !template) { count('conflicts'); issue('missing_append_template', key, tabName); return; }
    if (!found && !pqmGoogleSafeAppendFormula_(template.formulas[0], tab.rows.length + 1)) {
      count('conflicts'); issue('unsafe_or_missing_append_formula_A', key, tabName); return;
    }
    if (!found && (!Number.isInteger(tab.templateRowHeight) || tab.templateRowHeight <= 0)) {
      count('conflicts'); issue('missing_template_row_height', key, tabName); return;
    }
    if (!found && tab.merges.some(function(range) {
      return range.endRowIndex > tab.rows.length && (range.startColumnIndex || 0) < 15 && range.endColumnIndex > 0;
    })) { count('conflicts'); issue('merged_append_template_or_destination', key, tabName); return; }
    if (!found && PQM_GOOGLE_APPEND_OWNED.some(function(column) { return !!template.formulas[column]; })) {
      count('conflicts'); issue('formula_in_append_owned_cell', key, tabName); return;
    }

    var admitted = item.google_sync_has_admission_history;
    var active = item.google_sync_has_active_qualification;
    var decision = item.google_sync_last_decided_application_decision;
    if (decision !== 'admit' && decision !== 'reject') { count('conflicts'); issue('decision_event_missing', key, tabName); return; }
    var prozorro = active ? 'Активний' : admitted ? 'Неактивний' : 'Ще не в реєстрі';
    var prozorroCategory = active ? 'active' : admitted ? 'inactive' : 'not_yet';
    var edr = (!admitted || !active) ? 'Неактуально' :
      (pqmGoogleBlank_(item.edr_status_current) ? 'Зареєстровано' : pqmGoogleEdrCurrentStatus_(item.edr_status_current));
    if (edr === null) { count('conflicts'); issue('unknown_edr_status', key, tabName); return; }
    var cells = {};
    function blockVerificationPair() {
      // D/E/I/L form one provenance group. Conflicts must not leave a partial
      // verification write, while independent C/F/H events remain in Preview.
      [3, 4, 8, 11].forEach(function(column) { delete cells[column]; });
    }
    if (!found) {
      var name = !pqmGoogleBlank_(item.supplier_name) ? item.supplier_name : item.latest_submission_name;
      if (pqmGoogleBlank_(name)) { count('conflicts'); issue('append_name_missing', key, tabName); return; }
      cells[1] = key; cells[2] = name;
      if (!pqmGoogleBlank_(item.current_manager_name)) cells[3] = item.current_manager_name;
      cells[4] = (!admitted && decision === 'reject') ? 'Неактуально' : edr;
      cells[5] = prozorro;
      var appendDate = pqmGoogleCalendarDate_(item.google_sync_last_decided_application_date);
      if (appendDate.kind !== 'date') { count('conflicts'); issue('last_decided_application_date_missing_or_invalid', key, tabName); return; }
      cells[7] = pqmGoogleDate_(appendDate.value);
      if (!admitted && decision === 'reject') {
        if (pqmGoogleBlank_(item.google_sync_latest_rejection_officer)) {
          count('conflicts'); issue('rejection_protocol_officer_missing', key, tabName); return;
        }
        cells[11] = item.google_sync_latest_rejection_officer;
      } else {
        var appendVerification = pqmGoogleMatrixSourceVerification_(item);
        var appendOfficer = item.verification_officer ||
          (decision === 'admit' ? item.google_sync_last_decided_protocol_officer : '');
        if ((appendVerification.kind !== 'datetime' && appendVerification.kind !== 'day') || pqmGoogleBlank_(appendOfficer)) {
          count('conflicts'); issue('admission_verification_pair_missing_or_invalid', key, tabName); return;
        }
        cells[8] = pqmGoogleMatrixNumber_(appendVerification); cells[11] = appendOfficer;
      }
    } else {
      // Supplier name, status and decided application date are separate business
      // events. They never clear Google values and do not rewrite I/L history.
      if (!pqmGoogleBlank_(item.supplier_name) && String(found.data.values[2] || '') !== String(item.supplier_name)) cells[2] = item.supplier_name;
      var existingProzorro = pqmGoogleProzorroCategory_(found.data.values[5]);
      if (existingProzorro === null) { count('conflicts'); issue('unknown_google_prozorro_status', key, tabName); return; }
      if (existingProzorro !== prozorroCategory) cells[5] = prozorro;
      var currentH = pqmGoogleCalendarDate_(found.data.values[7]);
      var sourceH = pqmGoogleCalendarDate_(item.google_sync_last_decided_application_date);
      if (sourceH.kind === 'invalid' || currentH.kind === 'invalid') {
        count('conflicts'); issue('last_decided_application_date_conflict', key, tabName); return;
      }
      if (sourceH.kind === 'date' && (currentH.kind === 'blank' || sourceH.value > currentH.value))
        cells[7] = pqmGoogleDate_(sourceH.value);

      // Before the first admission, a rejection may update its own protocol
      // officer. Rejections after admission never replace I/L.
      if (!admitted && decision === 'reject') {
        if (pqmGoogleBlank_(item.google_sync_latest_rejection_officer)) {
          count('conflicts'); issue('rejection_protocol_officer_missing', key, tabName); return;
        }
        if (pqmGoogleOfficerComparable_(item.google_sync_latest_rejection_officer) !==
            pqmGoogleOfficerComparable_(found.data.values[11])) cells[11] = item.google_sync_latest_rejection_officer;
        if (pqmGoogleEdrCurrentStatus_(found.data.values[4]) !== 'Неактуально') cells[4] = 'Неактуально';
      } else {
        if (!admitted || !active) {
          if (pqmGoogleEdrCurrentStatus_(found.data.values[4]) !== 'Неактуально') cells[4] = 'Неактуально';
        } else if (decision === 'admit' &&
            (pqmGoogleProzorroCategory_(found.data.values[5]) !== 'active' ||
             pqmGoogleEdrCurrentStatus_(found.data.values[4]) === 'Неактуально') &&
            pqmGoogleEdrCurrentStatus_(found.data.values[4]) !== edr &&
            !pqmGoogleEdrPreserveInformation_(found.data.values[4])) {
          cells[4] = edr;
        }
        var verification = pqmGoogleMatrixSourceVerification_(item);
        var googleFormat = String(found.data.verificationDateFormat || '');
        var googlePrecision = /H|h/.test(googleFormat) ? 'datetime' : googleFormat ? 'day' : '';
        var googleVerification = pqmGoogleMatrixVerification_(found.data.values[8], googlePrecision);
        var eventType = String(item.verification_event_type || '');
        var isAdmission = eventType === 'admission';
        var hasVerificationEvent = !pqmGoogleBlank_(item.verification_date);
        if (decision === 'reject' && eventType === 'admission') {
          // A later rejection never rewrites the last admission/check provenance.
        } else if (hasVerificationEvent && verification.kind === 'invalid') {
          blockVerificationPair(); count('conflicts'); issue('pqm_verification_timestamp_invalid', key, tabName);
        } else if (hasVerificationEvent && (verification.kind === 'day' || verification.kind === 'datetime')) {
          if (verification.kind === 'day' && googleVerification.kind === 'blank' && isAdmission) {
            var protocolOfficer = item.verification_officer || item.google_sync_last_decided_protocol_officer;
            if (pqmGoogleBlank_(protocolOfficer)) { blockVerificationPair(); count('conflicts'); issue('admission_protocol_officer_missing', key, tabName); }
            else if (pqmGoogleEdrPreserveInformation_(found.data.values[4])) {
              blockVerificationPair(); count('conflicts'); issue('manual_edr_information_marker_blocks_verification_pair', key, tabName);
            } else {
              if (!pqmGoogleBlank_(item.current_manager_name)) cells[3] = item.current_manager_name;
              cells[4] = edr;
              cells[8] = pqmGoogleDate_(verification.date); cells[11] = protocolOfficer;
              count('google_blank_filled');
            }
          } else if (verification.kind === 'day') {
            var googleCalendar = pqmGoogleCalendarDate_(found.data.values[8]);
            // A later Google calendar day is certainly newer than any instant
            // within the PQM date-only day. Preserve Google provenance without
            // treating the date-only PQM value as permission to write.
            if ((googleVerification.kind === 'day' || googleVerification.kind === 'datetime') &&
                googleCalendar.kind === 'date' && googleCalendar.value > verification.date) {
              blockVerificationPair();
              count('google_newer_preserved');
            } else if (googleVerification.kind !== 'day' || googleVerification.date !== verification.date ||
                pqmGoogleOfficerComparable_(item.current_manager_name) !== pqmGoogleOfficerComparable_(found.data.values[3]) ||
                pqmGoogleEdrCurrentStatus_(item.edr_status_current) !== pqmGoogleEdrCurrentStatus_(found.data.values[4]) ||
                pqmGoogleOfficerComparable_(item.verification_officer) !== pqmGoogleOfficerComparable_(found.data.values[11])) {
              blockVerificationPair(); count('conflicts'); issue('date_only_cannot_prove_verification_order', key, tabName);
            } else count('same_date_equivalent');
          } else if (googleVerification.kind === 'invalid') {
            blockVerificationPair(); count('conflicts'); issue('google_verification_timestamp_invalid', key, tabName);
          } else if (googleVerification.kind === 'blank') {
            var sourceEdr = pqmGoogleEdrCurrentStatus_(item.edr_status_current);
            if (pqmGoogleBlank_(item.current_manager_name) || pqmGoogleBlank_(item.verification_officer) || !sourceEdr) {
              blockVerificationPair(); count('conflicts'); issue('verification_group_incomplete', key, tabName);
            } else if (pqmGoogleEdrPreserveInformation_(found.data.values[4])) {
              blockVerificationPair(); count('conflicts'); issue('manual_edr_information_marker_blocks_verification_pair', key, tabName);
            } else {
              cells[3] = item.current_manager_name;
              cells[4] = sourceEdr;
              cells[8] = pqmVerificationSerial_(verification.value); cells[11] = item.verification_officer;
              count('google_blank_filled');
            }
          } else if (googleVerification.kind === 'day') {
            blockVerificationPair(); count('conflicts'); issue('google_date_only_cannot_prove_timestamp_order', key, tabName);
          } else if (verification.value > googleVerification.value) {
            var newerEdr = pqmGoogleEdrCurrentStatus_(item.edr_status_current);
            if (pqmGoogleBlank_(item.current_manager_name) || pqmGoogleBlank_(item.verification_officer) || !newerEdr) {
              blockVerificationPair(); count('conflicts'); issue('verification_group_incomplete', key, tabName);
            } else if (pqmGoogleEdrPreserveInformation_(found.data.values[4])) {
              blockVerificationPair(); count('conflicts'); issue('manual_edr_information_marker_blocks_verification_pair', key, tabName);
            } else {
              cells[3] = item.current_manager_name;
              cells[4] = newerEdr;
              cells[8] = pqmVerificationSerial_(verification.value); cells[11] = item.verification_officer;
              count('pqm_newer_written');
            }
          } else if (verification.value === googleVerification.value) {
            var equalEdr = pqmGoogleEdrCurrentStatus_(item.edr_status_current);
            if (!equalEdr || pqmGoogleBlank_(item.current_manager_name) || pqmGoogleBlank_(item.verification_officer)) {
              blockVerificationPair(); count('conflicts'); issue('same_timestamp_verification_group_incomplete', key, tabName);
            } else if (pqmGoogleEdrPreserveInformation_(found.data.values[4])) {
              blockVerificationPair(); count('conflicts'); issue('manual_edr_information_marker_blocks_verification_pair', key, tabName);
            } else {
              var managerConflict = !pqmGoogleBlank_(item.current_manager_name) &&
                pqmGoogleOfficerComparable_(item.current_manager_name) !== pqmGoogleOfficerComparable_(found.data.values[3]);
              var statusConflict = !equalEdr || equalEdr !== pqmGoogleEdrCurrentStatus_(found.data.values[4]);
              var officerConflict = !pqmGoogleBlank_(item.verification_officer) &&
                pqmGoogleOfficerComparable_(item.verification_officer) !== pqmGoogleOfficerComparable_(found.data.values[11]);
              if (managerConflict || statusConflict || officerConflict) {
                blockVerificationPair();
                if (!managerConflict && !statusConflict && officerConflict) count('same_date_google_officer_preserved');
                else { count('conflicts'); issue('same_timestamp_verification_conflict', key, tabName); }
              } else count('same_date_equivalent');
            }
          } else count('google_newer_preserved');
        } else if (decision === 'admit' && !pqmGoogleBlank_(found.data.values[8]) && isAdmission) {
          // An admission protocol event cannot replace a more recent verification.
        }
        if (!hasVerificationEvent && !pqmGoogleBlank_(found.data.values[8])) count('pqm_blank_google_preserved');
      }
    }
    if (!found && (!Object.prototype.hasOwnProperty.call(cells, '1') || !Object.prototype.hasOwnProperty.call(cells, '2'))) {
      count('conflicts'); issue('append_row_incomplete', key, tabName); return;
    }
    if (pqmGoogleProtected_(tabs[tabName], found ? found.row : nextRows[tabName], Object.keys(cells).map(Number))) {
      count('conflicts'); issue('protected_owned_cell', key, tabName); return;
    }
    if (!Object.keys(cells).length) { count('unchanged'); return; }
    changes.push({tab: tabName, row: found ? found.row : nextRows[tabName]++, append: !found, cells: cells,
      source_event: !found && decision === 'reject' && !admitted ? 'first_rejection' :
        decision === 'admit' ? 'admission' : active ? 'active_qualification' : 'qualification_inactive',
      source_timestamps: {pqm_verification: item.verification_date || item.google_sync_last_decided_protocol_at || null,
        google_verification: found ? found.data.values[8] || null : null,
        precision: item.verification_datetime_precision || null}});
    count(found ? 'updated' : 'appended');
  });
  return {counts: result, per_tab: perTab, issues: issues, gaps: gaps, changes: changes};
}

// The shared Apps Script entrypoint is declared in PqmGoogleWriter.gs. Pure
// VM suites that load only the two planner files replace the legacy fallback.
if (typeof pqmGooglePlan_ === 'undefined' || pqmGooglePlan_ === pqmGoogleLegacyPlan_ ||
    pqmGooglePlan_ === pqmGoogleWriterLegacyPlan_) pqmGooglePlan_ = pqmGoogleBusinessPlan_;
