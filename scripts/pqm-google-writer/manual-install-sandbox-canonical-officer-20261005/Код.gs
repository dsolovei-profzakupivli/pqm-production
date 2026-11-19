// ==========================================
// ДОПОМІЖНА ФУНКЦІЯ: ФОРМАТУВАННЯ СКОРОЧЕНОЇ НАЗВИ ФОП
// Перетворює "Шевченко Тарас Григорович" -> "ФОП ШЕВЧЕНКО Т.Г."
// ==========================================
function formatFopShortName(pib) {
  if (!pib) return "";
  var parts = pib.trim().split(/\s+/);
  if (parts.length === 0 || parts[0] === "") return "";
  
  var surname = parts[0].toUpperCase();
  var initials = "";
  
  if (parts.length > 1 && parts[1].length > 0) {
    initials += parts[1].charAt(0).toUpperCase() + ".";
  }
  if (parts.length > 2 && parts[2].length > 0) {
    initials += parts[2].charAt(0).toUpperCase() + ".";
  }
  
  return ("ФОП " + surname + (initials ? " " + initials : "")).trim();
}

// ==========================================
// БЛОК 1: АВТОМАТИЧНИЙ ТРИГЕР (onEdit) - ДЛЯ СТОВПЦІВ G, E, D
// ==========================================
function onEdit(e) {
  if (!e) return;
  
  var range = e.range;
  var sheet = range.getSheet();
  var sheetName = sheet.getName().trim();
  
  var startRow = range.getRow();
  var endRow = range.getLastRow();
  var startCol = range.getColumn();
  var endCol = range.getLastColumn();
  
  var actualStartRow = Math.max(2, startRow);
  
  var userEmail = Session.getActiveUser().getEmail();
  var userName = "";
  switch (userEmail) {
    case "s.namiasenko@profzakupivli.com": userName = "Світлана НАМЯСЕНКО"; break;
    case "t.fedchenko@profzakupivli.com": userName = "Тетяна ФЕДЧЕНКО"; break;
    case "o.yeromina@profzakupivli.com": userName = "Олена ЄРЬОМІНА"; break;
    case "d.savva@profzakupivli.com": userName = "Дмитро САВВА"; break;
    default: userName = userEmail ? userEmail.split('@')[0] : "Невідомий користувач";
  }

  // 🌟 ЧАСТИНА А: Стовпці D (4) або E (5) — оновлення Дати перевірки (I) та УО (L)
  if (((startCol <= 4 && endCol >= 4) || (startCol <= 5 && endCol >= 5)) && endRow > 1) {
    if (startRow === endRow && startCol === endCol) { 
      var oldValue = e.oldValue ? e.oldValue.toString().trim() : "";
      var newValue = e.value ? e.value.toString().trim() : "";
      
      if (oldValue !== newValue) {
        sheet.getRange(startRow, 9).setValue(new Date()).setNumberFormat("dd.mm.yyyy").setHorizontalAlignment("center");
        sheet.getRange(startRow, 12).setValue(userName).setHorizontalAlignment("left");
        
        // Для ФОП: якщо змінюється ПІБ у стовпці D — оновлюємо стовпчики N та O
        if (sheetName.toUpperCase() === "ФОП" && startCol === 4 && newValue !== "") {
          var fullNameFOP = "ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ " + newValue.toUpperCase();
          var shortNameFOP = formatFopShortName(newValue);
          
          sheet.getRange(startRow, 14).setValue(fullNameFOP);
          sheet.getRange(startRow, 15).setValue(shortNameFOP);
        }
      }
    }
  }
  
  // 🌟 ЧАСТИНА Б: Стовпець G (Ручне введення / редагування)
  if (startCol <= 7 && endCol >= 7 && endRow > 1) {
    var numRows = endRow - actualStartRow + 1;
    var valuesG = sheet.getRange(actualStartRow, 7, numRows, 1).getValues();
    
    var dateJValues = [];
    var numberKValues = [];
    
    for (var i = 0; i < numRows; i++) {
      var textG = valuesG[i][0] ? valuesG[i][0].toString() : "";
      var cellTextLower = textG.toLowerCase();
      var currentRow = actualStartRow + i;
      
      if (textG !== "" && cellTextLower.indexOf("смерт") !== -1) {
        sheet.getRange(currentRow, 7).setBackground('#f4cccc');
      } else {
        sheet.getRange(currentRow, 7).setBackground(null);
      }
      
      var dateMatch = textG.match(/(?:Дата запису:\s*|від\s*)([\d\.\-]+)/i);
      var numberMatch = textG.match(/(?:Номер запису:\s*|Запис\s*№\s*)(\d+)/i);
      
      if (dateMatch && dateMatch[1]) {
        var dateStr = dateMatch[1].trim();
        var jsDate = null;
        
        if (dateStr.indexOf('-') !== -1) {
          var parts = dateStr.split('-');
          if (parts.length === 3) {
            var year = parts[0].length === 2 ? parseInt("20" + parts[0], 10) : parseInt(parts[0], 10);
            var month = parseInt(parts[1], 10) - 1;
            var day = parseInt(parts[2], 10);
            jsDate = new Date(year, month, day, 12, 0, 0);
          }
        } 
        else if (dateStr.indexOf('.') !== -1) {
          var parts = dateStr.split('.');
          if (parts.length === 3) {
            var year = parts[2].length === 2 ? parseInt("20" + parts[2], 10) : parseInt(parts[2], 10);
            var month = parseInt(parts[1], 10) - 1;
            var day = parseInt(parts[0], 10);
            jsDate = new Date(year, month, day, 12, 0, 0);
          }
        }
        
        if (jsDate && !isNaN(jsDate.getTime())) {
          dateJValues.push([jsDate]);
        } else {
          dateJValues.push([dateStr]); 
        }
      } else {
        dateJValues.push([""]);
      }
      
      numberKValues.push([numberMatch && numberMatch[1] ? numberMatch[1] : ""]);
    }
    
    if (dateJValues.length > 0) {
      sheet.getRange(actualStartRow, 10, numRows, 1).setValues(dateJValues).setNumberFormat("dd.mm.yyyy").setHorizontalAlignment("center");
    }
    if (numberKValues.length > 0) {
      sheet.getRange(actualStartRow, 11, numRows, 1).setValues(numberKValues).setNumberFormat("@").setHorizontalAlignment("center");
    }
  }
}

// ==========================================
// БЛОК 2: ГОЛОВНЕ МЕНЮ
// ==========================================
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('⚙️ Робота з даними')
    .addItem('🧪 SANDBOX: Preview PQM → Google', 'pqmSandboxPreview')
    .addItem('🔄 SANDBOX: контрольована синхронізація (8–10 кодів)', 'pqmSandboxControlledApplyWithResult')
    .addItem('🚀 SANDBOX: повна синхронізація існуючих рядків', 'pqmSandboxFullApplyWithResult')
    .addSeparator()
    .addItem('🏢 Заповнити дані з файлу ClarityChecker', 'showUploadFullNameDialog')
    .addSeparator()
    .addItem('📆 Оновити Дату та УО для виділених рядків', 'updateSelectedRows')
    .addSeparator()
    .addItem('✏️ Редактор ЮО', 'openOrganizationEditorDialog')
    .addToUi();
}

// ==========================================
// БЛОК 3: РУЧНЕ ОНОВЛЕННЯ СТОВПЦЯ E
// ==========================================
function updateSelectedRows() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var range = sheet.getActiveRange();
  
  var startRow = range.getRow();
  var endRow = range.getLastRow();
  var numRows = endRow - startRow + 1;
  
  var userEmail = Session.getActiveUser().getEmail();
  var userName = "";
  switch (userEmail) {
    case "s.namiasenko@profzakupivli.com": userName = "Світлана НАМЯСЕНКО"; break;
    case "t.fedchenko@profzakupivli.com": userName = "Тетяна ФЕДЧЕНКО"; break;
    case "o.yeromina@profzakupivli.com": userName = "Олена ЄРЬОМІНА"; break;
    case "d.savva@profzakupivli.com": userName = "Дмитро САВВА"; break;
    default: userName = userEmail ? userEmail.split('@')[0] : "Невідомий користувач";
  }
  
  var currentDates = sheet.getRange(startRow, 9, numRows, 1).getValues();
  var currentUsers = sheet.getRange(startRow, 12, numRows, 1).getValues();
  
  var dateValues = [];
  var userValues = [];
  var today = new Date();
  
  for (var i = 0; i < numRows; i++) {
    var currentRow = startRow + i;
    if (sheet.isRowHiddenByFilter(currentRow)) {
      dateValues.push([currentDates[i][0]]);
      userValues.push([currentUsers[i][0]]);
    } else {
      dateValues.push([today]);
      userValues.push([userName]);
    }
  }
  
  sheet.getRange(startRow, 9, numRows, 1).setValues(dateValues).setNumberFormat("dd.mm.yyyy").setHorizontalAlignment("center");
  sheet.getRange(startRow, 12, numRows, 1).setValues(userValues).setHorizontalAlignment("left");
  SpreadsheetApp.flush();
}



// ==========================================
// БЛОК 5А: ДІАЛОГ ВИБОРУ ФАЙЛУ З ДИСКА D: (З ФАЙЛУ ClarityChecker)
// ==========================================
function showUploadFullNameDialog() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSheet();
  if (sheet.getName().trim().toUpperCase() !== 'ЮО') {
    ui.alert('Помилка', 'Ця функція призначена лише для аркуша "ЮО".', ui.ButtonSet.OK);
    return;
  }

  var html = HtmlService.createHtmlOutput(
    '<html><body>' +
    '<h3>Імпорт ClarityChecker CSV</h3>' +
    '<input type="file" id="fileInput" accept=".csv"><br><br>' +
    '<input type="button" value="Імпортувати CSV" id="uploadBtn" onclick="processFile()"> ' +
    '<input type="button" value="Закрити" onclick="google.script.host.close()">' +
    '<p id="status" style="white-space:pre-line;color:#174f2e"></p>' +
    '<script>' +
    'function processFile(){' +
    'var fileInput=document.getElementById("fileInput");' +
    'if(!fileInput.files.length){alert("Оберіть CSV-файл.");return;}' +
    'var status=document.getElementById("status");' +
    'var button=document.getElementById("uploadBtn");' +
    'status.innerText="Зчитування CSV...";button.disabled=true;' +
    'var reader=new FileReader();' +
    'reader.onload=function(event){' +
    'status.innerText="Перевірка та імпорт...";' +
    'google.script.run.withSuccessHandler(function(result){' +
    'var matched=result.matched!=null?result.matched:(result.processed||0);' +
    'var names=result.updatedNames!=null?result.updatedNames:' +
      '((result.fullNameChanged||0)+(result.shortNameChanged||0));' +
    'var dates=result.updatedDatesUo||0;' +
    'var fromCsv=result.dateFromCsv||0;' +
    'var fromFilename=result.dateFromFilename||0;' +
    'var unmatched=result.unmatchedCsvCodes!=null?' +
      'result.unmatchedCsvCodes:(result.notFound||0);' +
    'var errors=Array.isArray(result.errors)?result.errors.length:' +
      '(Number(result.errors)||0);' +
    'var lines=["Імпорт завершено",' +
      '"Знайдено в Google: "+matched,' +
      '"Оновлено назв: "+names,' +
      '"Оновлено дату/УО: "+dates,' +
      '"Дата з CSV: "+fromCsv,' +
      '"Дата з назви файла: "+fromFilename,' +
      '"Кодів CSV не знайдено: "+unmatched,' +
      '"Помилок: "+errors];' +
    'status.style.color=errors?"#b42318":"#174f2e";' +
    'status.innerText=lines.join("\\n");button.disabled=false;' +
    '}).withFailureHandler(function(error){' +
    'status.style.color="#b42318";' +
    'status.innerText="Імпорт зупинено: "+error;' +
    'button.disabled=false;' +
    '}).processFullNamesCSV(event.target.result,fileInput.files[0].name);' +
    '};' +
    'reader.onerror=function(){status.style.color="#b42318";' +
      'status.innerText="Не вдалося прочитати CSV.";button.disabled=false;};' +
    'reader.readAsText(fileInput.files[0],"UTF-8");' +
    '}' +
    '</script></body></html>'
  ).setWidth(460).setHeight(320);
  ui.showModalDialog(html, 'Імпорт ClarityChecker');
}

function processFullNamesCSV(csvText, fileName) {
  var sheet = SpreadsheetApp.getActiveSheet();
  if (sheet.getName().trim().toUpperCase() !== 'ЮО') {
    throw new Error('Імпорт ClarityChecker дозволений лише на аркуші "ЮО".');
  }

  var csv = Utilities.parseCsv(csvText, ',');
  if (!csv.length) throw new Error('CSV порожній.');

  function header(value) {
    return String(value == null ? '' : value).replace(/^\uFEFF/, '')
      .trim().replace(/\s+/g, ' ').toLowerCase();
  }
  function column(names, required) {
    var aliases = names.map(header);
    var found = [];
    csv[0].forEach(function(value, index) {
      if (aliases.indexOf(header(value)) !== -1) found.push(index);
    });
    if (found.length !== 1 && (required || found.length > 1)) {
      throw new Error('Неоднозначний або відсутній CSV-заголовок: ' + names[0]);
    }
    return found.length ? found[0] : -1;
  }

  var codeCol = column(['Код ЄДРПОУ', 'ЄДРПОУ'], true);
  var dateCol = column(['Нова дата перевірки ЄДР'], false);
  if (dateCol < 0) dateCol = column(['Фактична дата перевірки ЄДР',
    'Дата перевірки ЄДР'], true);
  // "Стара Назва" in the five-column export is NOT a verified EDR name.
  var fullCol = column(['Нова назва', 'Повна назва з ЄДР', 'Повна назва'], false);
  var shortCol = column(['Скорочена назва', 'Скорочена назва з ЄДР'], false);

  function code(value) {
    var text = String(value == null ? '' : value).trim();
    if (/^\d{1,7}$/.test(text)) return ('00000000' + text).slice(-8);
    return text; // Never erase letters or internal whitespace.
  }
  function cell(row, index) {
    return index < 0 ? '' : String(row[index] == null ? '' : row[index]).trim();
  }
  function date(value) {
    var text = String(value == null ? '' : value).trim();
    if (!text) return null;
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/.exec(text);
    var y, mo, d;
    if (m) {
      y = +m[1]; mo = +m[2]; d = +m[3];
      if (m[4] && (+m[4] > 23 || +m[5] > 59 || +m[6] > 59)) m = null;
    } else {
      m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text);
      if (m) { d = +m[1]; mo = +m[2]; y = +m[3]; }
    }
    if (!m || y < 1900 || mo < 1 || mo > 12 || d < 1 || d > 31) {
      throw new Error('Некоректна дата ClarityChecker: ' + text);
    }
    var result = new Date(y, mo - 1, d, 12, 0, 0);
    if (result.getFullYear() !== y || result.getMonth() !== mo - 1 || result.getDate() !== d) {
      throw new Error('Некоректна календарна дата ClarityChecker: ' + text);
    }
    return result;
  }
  function day(value) {
    if (value instanceof Date && !isNaN(value.getTime())) {
      return [value.getFullYear(), ('0' + (value.getMonth() + 1)).slice(-2),
        ('0' + value.getDate()).slice(-2)].join('-');
    }
    var text = String(value == null ? '' : value).trim();
    var m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text);
    return m ? [m[3], m[2], m[1]].join('-') : text.slice(0, 10);
  }
  function filenameDate(name) {
    var m = /^Результат_перевірки_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.csv$/i.exec(
      String(name == null ? '' : name).trim());
    if (!m || +m[2] > 23 || +m[3] > 59 || +m[4] > 59) return null;
    try { return date(m[1]); } catch (_) { return null; }
  }
  var cycleDate = filenameDate(fileName);

  var errors = [];
  var source = {};
  for (var i = 1; i < csv.length; i++) {
    var sourceCode = code(csv[i][codeCol]);
    if (!sourceCode) continue;
    if (Object.prototype.hasOwnProperty.call(source, sourceCode)) {
      errors.push('Повторний код CSV: ' + sourceCode);
      continue;
    }
    source[sourceCode] = {
      full: cell(csv[i], fullCol), short: cell(csv[i], shortCol),
      dateText: cell(csv[i], dateCol), matched: false
    };
  }

  var lastRow = sheet.getLastRow();
  var count = Math.max(0, lastRow - 1);
  var expected = {2: 'Код ЄДРПОУ', 9: 'Дата перевірки', 12: 'УО',
    14: 'Повна назва з ЄДР', 15: 'Скорочена назва з ЄДР'};
  Object.keys(expected).forEach(function(n) {
    if (header(sheet.getRange(1, +n).getDisplayValue()) !== header(expected[n])) {
      errors.push('Невірний заголовок Google у колонці ' + n);
    }
  });

  var rows = count ? sheet.getRange(2, 2, count, 1).getDisplayValues() : [];
  var old = {};
  [9, 12, 14, 15].forEach(function(n) {
    old[n] = count ? sheet.getRange(2, n, count, 1).getValues() : [];
  });
  var email = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
  var users = {
    's.namiasenko@profzakupivli.com': 'Світлана НАМЯСЕНКО',
    't.fedchenko@profzakupivli.com': 'Тетяна ФЕДЧЕНКО',
    'o.yeromina@profzakupivli.com': 'Олена ЄРЬОМІНА',
    'd.savva@profzakupivli.com': 'Дмитро САВВА'
  };
  var officer = users[email] || (email ? email.split('@')[0] : 'Невідомий користувач');
  var writes = {9: [], 12: [], 14: [], 15: []};
  var matched = 0, updatedNames = 0, updatedDatesUo = 0;
  var dateFromCsv = 0, dateFromFilename = 0;
  var fullNameChanged = 0, shortNameChanged = 0;
  var seenGoogle = {};

  // Complete preflight of every matched row. No Google write precedes this loop.
  rows.forEach(function(row, index) {
    var key = code(row[0]);
    if (!key || !Object.prototype.hasOwnProperty.call(source, key)) return;
    if (seenGoogle[key]) { errors.push('Повторний код Google: ' + key); return; }
    seenGoogle[key] = true;
    var item = source[key];
    item.matched = true;
    matched++;
    var sheetRow = index + 2;
    var changedName = false;
    if (item.full && item.full !== String(old[14][index][0] || '')) {
      writes[14].push({row: sheetRow, value: item.full});
      fullNameChanged++; changedName = true;
    }
    if (item.short && item.short !== String(old[15][index][0] || '')) {
      writes[15].push({row: sheetRow, value: item.short});
      shortNameChanged++; changedName = true;
    }
    if (changedName) updatedNames++;
    try {
      var parsed;
      if (item.dateText) {
        parsed = date(item.dateText);
        dateFromCsv++;
      } else if (cycleDate) {
        parsed = cycleDate;
        dateFromFilename++;
      } else {
        throw new Error('Немає дати в CSV і валідному стандартному filename');
      }
      var changedDate = day(old[9][index][0]) !== day(parsed);
      var changedOfficer = String(old[12][index][0] || '') !== officer;
      if (changedDate) {
        writes[9].push({row: sheetRow, value: parsed});
      }
      if (changedOfficer) writes[12].push({row: sheetRow, value: officer});
      if (changedDate || changedOfficer) updatedDatesUo++;
    } catch (err) {
      errors.push(key + ': ' + err.message);
    }
  });
  if (errors.length) throw new Error('Preflight ClarityChecker: ' + errors.join('; '));

  // Only planned cells are written; unmatched rows and blank source fields survive.
  [9, 12, 14, 15].forEach(function(n) {
    var planned = writes[n];
    for (var start = 0; start < planned.length;) {
      var end = start + 1;
      while (end < planned.length && planned[end].row === planned[end - 1].row + 1) end++;
      var range = sheet.getRange(planned[start].row, n, end - start, 1);
      range.setValues(planned.slice(start, end).map(function(item) { return [item.value]; }));
      if (n === 9) range.setNumberFormat('dd.MM.yyyy');
      start = end;
    }
  });

  var unmatched = Object.keys(source).filter(function(key) { return !source[key].matched; }).length;
  return {matched: matched, updatedNames: updatedNames, updatedDatesUo: updatedDatesUo,
    dateFromCsv: dateFromCsv, dateFromFilename: dateFromFilename,
    missingDates: dateFromFilename, unmatchedCsvCodes: unmatched, errors: [],
    processed: matched, notFound: unmatched,
    fullNameChanged: fullNameChanged, shortNameChanged: shortNameChanged};
}

function testPQMRegistryConnection() {
  var token = PropertiesService
    .getScriptProperties()
    .getProperty("PQM_SUPPLIER_REGISTRY_TOKEN");

  if (!token) {
    throw new Error("PQM_SUPPLIER_REGISTRY_TOKEN не знайдено.");
  }

  var response = UrlFetchApp.fetch(
    "https://pqm-production-1.onrender.com/api/integrations/suppliers/full-registry",
    {
      method: "get",
      headers: {
        Authorization: "Bearer " + token
      },
      muteHttpExceptions: true
    }
  );

  var status = response.getResponseCode();

  if (status !== 200) {
    throw new Error(
      "PQM повернув HTTP " + status + ": " + response.getContentText()
    );
  }

  var data = JSON.parse(response.getContentText());

  SpreadsheetApp.getActiveSpreadsheet().toast(
    "HTTP 200. Отримано постачальників: " + data.count,
    "✅ Зв’язок PQM → Google працює",
    8
  );

  Logger.log("HTTP: " + status);
  Logger.log("Count: " + data.count);
  Logger.log("Generated at: " + data.generated_at);
}
