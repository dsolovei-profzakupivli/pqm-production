var PQM_SANDBOX_FULL_REGISTRY_URL =
  'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';

var PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY =
  'PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN';

function pqmSandboxRegistryUrl_() {
  var match = PQM_SANDBOX_FULL_REGISTRY_URL.match(
    /^https:\/\/([^/?#:]+)(?::\d+)?(?:[/?#]|$)/i
  );

  if (!match || match[1].toLowerCase() !== 'pqm-sandbox.onrender.com') {
    throw new Error('PQM SANDBOX: endpoint guard rejected the URL.');
  }

  return PQM_SANDBOX_FULL_REGISTRY_URL;
}

function pqmSandboxFetchRegistry_() {
  var token = PropertiesService.getScriptProperties()
    .getProperty(PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);

  if (!token) {
    throw new Error('PQM SANDBOX: registry token is not configured.');
  }

  var url = pqmSandboxRegistryUrl_();
  var response;

  try {
    response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: {Authorization: 'Bearer ' + token},
      muteHttpExceptions: true,
      followRedirects: false
    });
  } catch (_) {
    throw new Error('PQM SANDBOX: API transport failure.');
  }

  if (response.getResponseCode() !== 200) {
    throw new Error(
      'PQM SANDBOX: API HTTP ' +
      response.getResponseCode() +
      '; no writes.'
    );
  }

  var body;

  try {
    body = JSON.parse(response.getContentText());
  } catch (_) {
    throw new Error('PQM SANDBOX: invalid JSON; no writes.');
  }

  pqmGoogleSchema_(body);
  return body;
}

function pqmSandboxPreviewChanges_(plan, tabs) {
  var letters = {1: 'B', 2: 'C', 4: 'E', 5: 'F', 7: 'H', 8: 'I', 11: 'L'};
  var changes = [];

  plan.changes.forEach(function(change) {
    Object.keys(change.cells).forEach(function(rawColumn) {
      var column = Number(rawColumn);

      changes.push({
        supplier_code: String(
          change.cells[1] ||
          (change.append
            ? ''
            : (
              tabs[change.tab].rows[change.row - 2] ||
              {codeDisplay: ''}
            ).codeDisplay || '')
        ).trim(),
        row: change.append ? 'NEW' : change.row,
        planned_row: change.row,
        column: letters[column],
        old_value: change.append
          ? null
          : (tabs[change.tab].rows[change.row - 2] || {values: []}).values[column],
        proposed_value: change.cells[column],
        action: change.append ? 'append' : 'update',
        reason: 'PQM-owned nonblank field'
      });
    });
  });

  return changes;
}

/**
 * Read-only SANDBOX Preview.
 * It does not write cells, invoke batchUpdate, or create menus.
 */
function pqmSandboxPreview() {
  var lock = LockService.getScriptLock();

  if (!lock.tryLock(0)) {
    throw new Error('PQM SANDBOX: another preview is running.');
  }

  try {
    var startedAt = Date.now();
    var fetchStartedAt = Date.now();
    var body = pqmSandboxFetchRegistry_();
    var fetchMs = Date.now() - fetchStartedAt;
    var snapshotStartedAt = Date.now();
    var tabs = pqmGoogleSnapshot_(
      SpreadsheetApp.getActiveSpreadsheet().getId()
    );
    var snapshotMs = Date.now() - snapshotStartedAt;
    var plannerStartedAt = Date.now();
    var plan = pqmGooglePlan_(body, tabs);
    var plannerMs = Date.now() - plannerStartedAt;

    var preview = {
      dry_run: true,
      google_writes: 0,
      total_pqm_suppliers: body.count,
      counts: plan.counts,
      per_tab: plan.per_tab,
      skips: plan.counts.skipped,
      conflicts_errors: plan.issues.concat(plan.gaps),
      proposed_changes: pqmSandboxPreviewChanges_(plan, tabs),
      timing_ms: {pqm_fetch: fetchMs, google_snapshot: snapshotMs,
        planner: plannerMs, total: Date.now() - startedAt}
    };

    console.log(JSON.stringify({
      total_pqm_suppliers: preview.total_pqm_suppliers,
      counts: preview.counts, per_tab: preview.per_tab, skips: preview.skips,
      conflicts_errors_count: preview.conflicts_errors.length,
      proposed_changes_count: preview.proposed_changes.length,
      google_writes: preview.google_writes, timing_ms: preview.timing_ms,
      aggregate: pqmGooglePlanAggregate_(plan),
      comparison_audit: pqmGooglePlanComparisonAudit_(plan, tabs)
    }));

    SpreadsheetApp.getActiveSpreadsheet().toast(
      'PQM: ' + body.count +
      '; updates: ' + plan.counts.updated +
      '; appends: ' + plan.counts.appended +
      '; conflicts: ' + plan.counts.conflicts,
      'PQM SANDBOX Preview — no writes',
      10
    );

    return preview;
  } finally {
    lock.releaseLock();
  }
}
