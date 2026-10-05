/* Presentation only. No writer, cache, property or API mutation here. */
function pqmSandboxResultModel_(result, mode) {
  result = result || {};
  var counts = result.counts || {};
  var summary = {};
  if (mode === 'preview') {
    summary = Object.assign({total_pqm_suppliers: result.total_pqm_suppliers,
      google_writes: result.google_writes}, counts);
  } else {
    // selected_rows is not an updated count if AFTER verification failed.
    summary.updated = result.verification_passed === true ? result.selected_rows :
      (typeof result.rows_processed === 'number' ? result.rows_processed : null);
    summary.skipped = typeof result.skipped === 'number' ? result.skipped : null;
    summary.conflicts = typeof result.conflicts === 'number' ? result.conflicts : null;
    summary.errors = Array.isArray(result.failures) ? result.failures.length :
      (typeof result.failures === 'number' ? result.failures : null);
    ['status', 'cancelled', 'verification_passed', 'selected_rows', 'written_cells',
      'rows_total', 'rows_processed', 'cells_written', 'cells_attempted', 'cells_verified',
      'remaining_cells', 'chunks_completed', 'chunks_total'].forEach(function(key) {
      if (Object.prototype.hasOwnProperty.call(result, key)) summary[key] = result[key];
    });
  }
  return {mode: mode, summary: summary, per_tab: result.per_tab || {},
    issues: mode === 'preview' ? (result.conflicts_errors || []) :
      (Array.isArray(result.failures) ? result.failures : []),
    details: result.proposed_changes || [], raw_result: result};
}

function pqmSandboxUiDate_(value, field) {
  var dateFields = ['H', 'I', 'J', 'edr_checked_at', 'verification_date',
    'termination_record_date', 'last_application_date', 'google_sync_last_decided_application_date'];
  if (dateFields.indexOf(field) < 0 || value === null || value === undefined || value === '') return value;
  var iso = null;
  if (typeof value === 'number' && isFinite(value)) {
    var date = new Date((Math.floor(value) - 25569) * 86400000);
    if (!isNaN(date.getTime())) iso = date.toISOString().slice(0, 10);
  } else if (typeof value === 'string') {
    var text = value.trim(), match = /^(\d{4})-(\d{2})-(\d{2})(?:$|T| )/.exec(text);
    if (match) iso = match[1] + '-' + match[2] + '-' + match[3];
    else {
      match = /^(\d{2})\.(\d{2})\.(\d{4})(?:$| )/.exec(text);
      if (match) iso = match[3] + '-' + match[2] + '-' + match[1];
    }
  }
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return value;
  var parts = iso.split('-').map(Number), ms = Date.UTC(parts[0], parts[1] - 1, parts[2]);
  if (parts[0] < 1900 || parts[0] > 9999 || new Date(ms).toISOString().slice(0, 10) !== iso) return value;
  return iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4);
}

function pqmSandboxResultHtml_(model) {
  // Embed JSON as data, never as executable markup supplied by a supplier.
  var encoded = JSON.stringify(model).replace(/</g, '\\u003c')
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
  return '<!doctype html><html><head><meta charset="utf-8"><style>' +
    'body{font:14px Arial,sans-serif;margin:16px;color:#172b4d}' +
    'h2{font-size:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere}' +
    '.scroll{max-height:190px;overflow:auto;border:1px solid #dbe2ea;padding:8px}' +
    '.table-scroll{max-height:310px;overflow:auto}table{width:100%;border-collapse:collapse}' +
    'td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top;overflow-wrap:anywhere}' +
    'th{position:sticky;top:0;background:#eef3f8}td pre{margin:0;max-width:290px}' +
    'button{padding:7px;margin:8px 8px 8px 0}#summary{display:flex;gap:12px;flex-wrap:wrap}' +
    '.metric{background:#eef3f8;padding:8px;border-radius:6px}</style></head><body>' +
    '<p id="notice"></p><div id="summary"></div><h2>Conflicts / errors</h2>' +
    '<pre id="issues" class="scroll"></pre><section id="preview"><h2>Деталі: current → planned</h2>' +
    '<p>По 50 змін на сторінку. Це план, не результат запису.</p>' +
    '<button id="prev">← Попередня</button><span id="page"></span><button id="next">Наступна →</button>' +
    '<div class="table-scroll"><table><thead><tr><th>Код / row</th><th>Поле</th>' +
    '<th>Current</th><th>Planned</th><th>Action / reason</th></tr></thead><tbody id="rows"></tbody></table></div></section>' +
    '<details><summary>Повний результат / діагностика</summary><pre id="raw" class="scroll"></pre></details>' +
    '<button id="close">Закрити</button><script type="application/json" id="data">' + encoded + '</script>' +
    '<script>' +
    'var model=JSON.parse(document.getElementById("data").textContent),page=0,size=50;' +
    'var uiDate=' + pqmSandboxUiDate_.toString() + ';' +
    'function show(v){return v===null||v===undefined?"не надано":typeof v==="object"?JSON.stringify(v,null,2):String(v)}' +
    'document.getElementById("notice").textContent=model.mode==="preview"?' +
    '"Read-only Preview. Записи не виконуються. Apply із цього вікна недоступний.":' +
    '"Результат виконання. Невідомі лічильники не замінюються нулями. За partial/uncertain status потрібен новий Preview; повторний Apply тут недоступний.";' +
    'Object.keys(model.summary).forEach(function(k){var e=document.createElement("div");e.className="metric";' +
    'e.textContent=k+": "+show(model.summary[k]);document.getElementById("summary").appendChild(e)});' +
    'document.getElementById("issues").textContent=model.issues.length?show(model.issues):"Немає повідомлень у повернутому результаті";' +
    'document.getElementById("raw").textContent=show(model.raw_result);' +
    'document.getElementById("preview").hidden=model.mode!=="preview";' +
    'function render(){var rows=document.getElementById("rows");rows.textContent="";' +
    'model.details.slice(page*size,(page+1)*size).forEach(function(r){var tr=document.createElement("tr");' +
    '[String(r.supplier_code||"")+" / "+String(r.row||r.planned_row||""),r.column||r.field,uiDate(r.old_value,r.column||r.field),uiDate(r.proposed_value,r.column||r.field),' +
    'String(r.action||"")+" / "+show(r.reason)].forEach(function(v){var td=document.createElement("td"),p=document.createElement("pre");' +
    'p.textContent=show(v);td.appendChild(p);tr.appendChild(td)});rows.appendChild(tr)});' +
    'document.getElementById("page").textContent=(page+1)+" / "+Math.max(1,Math.ceil(model.details.length/size))+" · "+model.details.length+" змін";' +
    'document.getElementById("prev").disabled=page===0;document.getElementById("next").disabled=(page+1)*size>=model.details.length}' +
    'document.getElementById("prev").onclick=function(){if(page>0){page--;render()}};' +
    'document.getElementById("next").onclick=function(){if((page+1)*size<model.details.length){page++;render()}};' +
    'document.getElementById("close").onclick=function(){google.script.host.close()};render();' +
    '</script></body></html>';
}

function pqmSandboxShowResult_(title, result, mode) {
  try {
    SpreadsheetApp.getUi().showModalDialog(HtmlService.createHtmlOutput(
      pqmSandboxResultHtml_(pqmSandboxResultModel_(result, mode)))
      .setWidth(1050).setHeight(740), title);
  } catch (error) {
    // UI failure must not turn a completed writer into a reported writer failure.
    console.log('PQM SANDBOX result UI failed: ' + String(error));
    try { SpreadsheetApp.getActiveSpreadsheet().toast(
      'Вікно результату недоступне. Не повторюйте Apply без нового Preview. Див. diagnostic log.', title, 10); }
    catch (_) {}
  }
}

function pqmSandboxRunWithResult_(action, title) {
  var result;
  try { result = action(); }
  catch (error) {
    pqmSandboxShowResult_(title, {status: 'FAILED_OR_UNCERTAIN',
      failures: [{message: String(error), note: 'Не припускайте zero writes; перевірте diagnostic log.'}]}, 'apply');
    throw error;
  }
  pqmSandboxShowResult_(title, result, 'apply');
  return result;
}

function pqmSandboxControlledApplyWithResult() {
  return pqmSandboxRunWithResult_(pqmSandboxControlledApply, 'PQM SANDBOX — Controlled Apply');
}

function pqmSandboxFullApplyWithResult() {
  return pqmSandboxRunWithResult_(pqmSandboxFullApply, 'PQM SANDBOX — Full Apply');
}
