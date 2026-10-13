// ДОДАТИ як окремий файл Apps Script. Наявні функції не замінювати.
// Запуск: ccShowManagerApproval. Записує тільки D після галочок і кнопки погодження.
function ccShowManagerApproval() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getActiveSheet();
  ccManagerCheckSheet_(sheet);
  var html = "<!doctype html>\n<html><head><base target=\"_top\"><meta charset=\"utf-8\">\n<style>\nbody{font:14px Arial,sans-serif;margin:20px;color:#243247}h2{font-size:20px;margin:0 0 12px}button{padding:9px 14px;cursor:pointer;border:1px solid #b9c6d4;border-radius:6px;background:#fff}button:disabled{opacity:.5;cursor:default}#apply{background:#176347;color:white;border-color:#176347}p{line-height:1.45}.scroll{max-height:390px;overflow:auto;border:1px solid #d9e1e8;margin:16px 0}table{border-collapse:collapse;width:100%}th,td{padding:10px;text-align:left;border-bottom:1px solid #e2e8ee;vertical-align:top}th{position:sticky;top:0;background:#eef3f7}td:first-child{white-space:nowrap}.note{font-size:12px;color:#8c5b0a;margin-top:6px}#status{white-space:pre-line}#summary{color:#526172}input[type=checkbox]{width:18px;height:18px}\n</style></head><body>\n<h2>Погодження змін керівників</h2>\n<p>Оберіть CSV ClarityChecker. У таблиці показано поточний ПІБ зі стовпця D та новий ПІБ із файла.<br>Позначте потрібні рядки. Запис відбудеться лише після натискання «Записати погоджені» й підтвердження.</p>\n<input type=\"file\" id=\"file\" accept=\".csv\"> <button id=\"preview\" onclick=\"loadPreview()\">Показати зміни</button>\n<p id=\"summary\"></p><div class=\"scroll\"><table><thead><tr><th>Код ЄДРПОУ</th><th>Назва</th><th>Старий керівник (зараз у D)</th><th>Новий керівник (CSV)</th><th>Погоджую</th></tr></thead><tbody id=\"rows\"></tbody></table></div>\n<button id=\"apply\" disabled onclick=\"applySelected()\">Записати погоджені (0)</button> <button onclick=\"google.script.host.close()\">Закрити</button>\n<p id=\"status\" role=\"status\"></p>\n<script>\nvar spreadsheetId=__TARGET_SPREADSHEET__,sheetId=__TARGET_SHEET__;\nvar csvText='',items=[],ready=false,busy=false;\nfunction status(text,error){var el=document.getElementById('status');el.textContent=text;el.style.color=error?'#b42318':'#176347';}\nfunction selected(){return items.filter(function(item){return item.checkbox.checked;});}\nfunction controls(){var n=selected().length;document.getElementById('apply').textContent='Записати погоджені ('+n+')';document.getElementById('apply').disabled=busy||!ready||!n;document.getElementById('preview').disabled=busy;document.getElementById('file').disabled=busy;items.forEach(function(item){item.checkbox.disabled=busy||!ready;});}\nfunction clear(){ready=false;items=[];csvText='';document.getElementById('rows').textContent='';document.getElementById('summary').textContent='';controls();}\ndocument.getElementById('file').addEventListener('change',clear);\nfunction fail(error){busy=false;ready=false;status((error&&error.message)||String(error),true);controls();}\nfunction loadPreview(){var file=document.getElementById('file').files[0];if(!file){status('Оберіть CSV-файл.',true);return;}clear();busy=true;controls();status('Зчитування та перевірка CSV…');var reader=new FileReader();reader.onerror=function(){fail('Не вдалося прочитати файл.');};reader.onload=function(event){csvText=event.target.result;google.script.run.withSuccessHandler(render).withFailureHandler(fail).ccPreviewManagerChanges(csvText,spreadsheetId,sheetId);};reader.readAsText(file,'UTF-8');}\nfunction render(result){items=[];var body=document.getElementById('rows');body.textContent='';result.rows.forEach(function(row){var tr=document.createElement('tr');[row.code,row.name,row.oldManager,row.newManager].forEach(function(value,index){var td=document.createElement('td');td.textContent=value;if(index===0){var small=document.createElement('div');small.textContent='Рядок '+row.row;small.style.fontSize='12px';td.appendChild(small);}if(index===2&&row.baselineDiffers){var note=document.createElement('div');note.className='note';note.textContent='Старий ПІБ у CSV: '+(row.oldCsvManager||'(порожньо)');td.appendChild(note);}tr.appendChild(td);});var td=document.createElement('td'),check=document.createElement('input');check.type='checkbox';check.checked=false;check.setAttribute('aria-label','Погодити '+row.code);check.onchange=controls;td.appendChild(check);tr.appendChild(td);body.appendChild(tr);items.push({row:row,checkbox:check});});document.getElementById('summary').textContent='Опрацьовано у CSV: '+result.processed+'. Змін керівника у CSV: '+result.changedInCsv+'. До погодження: '+result.rows.length+'. Уже записано: '+result.alreadyCurrent+'. Не знайдено кодів: '+result.unmatched.length+'. Пропущено D з формулами: '+result.formulaSkipped+'.';busy=false;ready=true;status(result.rows.length?'Перевірте ПІБ і позначте потрібні рядки.':'Немає змін для погодження.');controls();}\nfunction applySelected(){var rows=selected();if(busy||!ready||!rows.length)return;if(!window.confirm('Записати нових керівників у D для '+rows.length+' вибраних рядків?'))return;var selections=rows.map(function(item){return {code:item.row.code,oldManager:item.row.oldManager,newManager:item.row.newManager};});busy=true;controls();status('Запис погоджених рядків…');google.script.run.withSuccessHandler(function(result){busy=false;ready=false;status('Записано керівників: '+result.updated+'. Для подальшого погодження натисніть «Показати зміни».');items.forEach(function(item){item.checkbox.checked=false;});controls();}).withFailureHandler(fail).ccApplyApprovedManagers(csvText,spreadsheetId,sheetId,selections);}\n</script></body></html>\n";
  html = html.replace('__TARGET_SPREADSHEET__', JSON.stringify(spreadsheet.getId()))
    .replace('__TARGET_SHEET__', JSON.stringify(sheet.getSheetId()));
  SpreadsheetApp.getUi().showModalDialog(
    HtmlService.createHtmlOutput(html).setWidth(1120).setHeight(650),
    'Погодження змін керівників — ClarityChecker'
  );
}

function ccManagerText_(value) {
  return String(value == null ? '' : value).replace(/^\uFEFF/, '').trim();
}
function ccManagerComparable_(value) {
  return ccManagerText_(value).replace(/\s+/g, ' ').toUpperCase();
}
function ccManagerCode_(value) {
  var text = ccManagerText_(value);
  return /^\d{1,7}$/.test(text) ? ('00000000' + text).slice(-8) : text;
}
function ccManagerCheckSheet_(sheet) {
  if (!sheet || ccManagerComparable_(sheet.getName()) !== 'ЮО') {
    throw new Error('Потрібен аркуш «ЮО».');
  }
  [[2, 'Код ЄДРПОУ'], [4, 'ПІБ для перевірки']].forEach(function(item) {
    if (ccManagerComparable_(sheet.getRange(1, item[0]).getDisplayValue()) !==
        ccManagerComparable_(item[1])) {
      throw new Error('Невірний заголовок у колонці ' + item[0] + ': очікується «' + item[1] + '».');
    }
  });
}
function ccManagerTarget_(spreadsheetId, sheetId) {
  pqmMirrorSpreadsheetId_(spreadsheetId);
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet || spreadsheet.getId() !== spreadsheetId) {
    throw new Error('Змінилася таблиця. Відкрийте погодження заново.');
  }
  var sheet = spreadsheet.getSheetById(Number(sheetId));
  ccManagerCheckSheet_(sheet);
  return sheet;
}

function ccManagerSource_(csvText) {
  if (typeof csvText !== 'string' || !csvText.trim()) throw new Error('CSV порожній.');
  var csv = Utilities.parseCsv(csvText, ',');
  if (!csv.length) throw new Error('CSV порожній.');
  function column(name) {
    var indices = [];
    csv[0].forEach(function(h, index) {
      if (ccManagerComparable_(h) === ccManagerComparable_(name)) indices.push(index);
    });
    if (indices.length !== 1) throw new Error('Відсутній або повторний заголовок CSV: ' + name);
    return indices[0];
  }
  var codeCol = column('Код ЄДРПОУ');
  var oldCol = column('Старий ПІБ Керівника');
  var newCol = column('Новий ПІБ керівника'); // I у наданому CSV
  var resultCol = column('Результат перевірки'); // K: ознака опрацювання
  var nameCol = column('Стара Назва');
  var candidates = Object.create(null), seen = Object.create(null);
  var processed = 0, unprocessed = 0;
  csv.slice(1).forEach(function(row) {
    if (!ccManagerText_(row[resultCol])) { unprocessed++; return; }
    processed++;
    var code = ccManagerCode_(row[codeCol]);
    if (!code) throw new Error('Опрацьований рядок CSV без коду ЄДРПОУ.');
    if (seen[code]) throw new Error('Повторний опрацьований код CSV: ' + code);
    seen[code] = true;
    var oldManager = ccManagerText_(row[oldCol]);
    var newManager = ccManagerText_(row[newCol]);
    if (!newManager || ccManagerComparable_(oldManager) === ccManagerComparable_(newManager)) return;
    if (/^=/.test(newManager)) throw new Error('ПІБ не може бути формулою: ' + code);
    candidates[code] = {code: code, oldCsvManager: oldManager, newManager: newManager,
      name: ccManagerText_(row[nameCol])};
  });
  return {candidates: candidates, processed: processed, unprocessed: unprocessed};
}

// Preview is strictly read-only. The returned oldManager is the current D value.
function ccPreviewManagerChanges(csvText, spreadsheetId, sheetId) {
  var sheet = ccManagerTarget_(spreadsheetId, sheetId);
  var source = ccManagerSource_(csvText);
  var count = Math.max(0, sheet.getLastRow() - 1);
  var values = count ? sheet.getRange(2, 2, count, 13).getDisplayValues() : [];
  var formulas = count ? sheet.getRange(2, 4, count, 1).getFormulas() : [];
  var seen = Object.create(null), rows = [], alreadyCurrent = 0, formulaSkipped = 0;
  values.forEach(function(row, index) {
    var code = ccManagerCode_(row[0]);
    if (!Object.prototype.hasOwnProperty.call(source.candidates, code)) return;
    if (seen[code]) throw new Error('Повторний код у Google Sheets: ' + code);
    seen[code] = true;
    var item = source.candidates[code];
    var current = String(row[2] == null ? '' : row[2]); // D, original display value
    if (ccManagerComparable_(current) === ccManagerComparable_(item.newManager)) {
      alreadyCurrent++; return;
    }
    if (formulas[index][0]) { formulaSkipped++; return; }
    rows.push({code: code, row: index + 2, name: ccManagerText_(row[12]) || item.name,
      oldManager: current, oldCsvManager: item.oldCsvManager, newManager: item.newManager,
      baselineDiffers: ccManagerComparable_(current) !== ccManagerComparable_(item.oldCsvManager)});
  });
  var unmatched = Object.keys(source.candidates).filter(function(code) { return !seen[code]; });
  return {rows: rows, processed: source.processed, unprocessed: source.unprocessed,
    changedInCsv: Object.keys(source.candidates).length, alreadyCurrent: alreadyCurrent,
    formulaSkipped: formulaSkipped, unmatched: unmatched};
}

// Only explicit selections are eligible. Re-read both CSV and sheet before writing.
function ccApplyApprovedManagers(csvText, spreadsheetId, sheetId, selections) {
  pqmMirrorContext_();
  if (!Array.isArray(selections) || !selections.length) throw new Error('Не вибрано жодного рядка.');
  var lock = LockService.getDocumentLock();
  if (!lock || !lock.tryLock(10000)) throw new Error('Інше погодження зараз виконується. Спробуйте пізніше.');
  try {
    var preview = ccPreviewManagerChanges(csvText, spreadsheetId, sheetId);
    var candidates = Object.create(null), selected = Object.create(null), plan = [];
    preview.rows.forEach(function(row) { candidates[row.code] = row; });
    selections.forEach(function(selection) {
      if (!selection || typeof selection.code !== 'string' ||
          typeof selection.oldManager !== 'string' || typeof selection.newManager !== 'string') {
        throw new Error('Некоректний рядок погодження.');
      }
      var code = selection.code;
      if (selected[code]) throw new Error('Повторний вибір: ' + code);
      selected[code] = true;
      var row = candidates[code];
      if (!row || row.oldManager !== selection.oldManager || row.newManager !== selection.newManager) {
        throw new Error('Дані змінилися або рядок уже оновлено: ' + code + '. Оновіть перегляд. Нічого не записано.');
      }
      plan.push(row);
    });
    var sheet = ccManagerTarget_(spreadsheetId, sheetId);
    // All selected rows passed preflight. Write D only; no onEdit invocation.
    plan.forEach(function(row) { sheet.getRange(row.row, 4).setValue(row.newManager); });
    SpreadsheetApp.flush();
    return {updated: plan.length, codes: plan.map(function(row) { return row.code; })};
  } finally {
    lock.releaseLock();
  }
}
