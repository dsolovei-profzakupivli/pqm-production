const ORGANIZATION_EDITOR_CONFIG = Object.freeze({
  spreadsheetId: '1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA',
  sheetName: 'ЮО',
  headerRow: 1,
  codeHeader: 'Код ЄДРПОУ',
  nameHeader: 'Найменування',
  maxResults: 50
});

function organizationEditorOnOpen() {
  // Окреме меню більше не створюємо.
  // Редактор ЮО відкривається з головного меню:
  // ⚙️ Робота з даними → ✏️ Редактор ЮО
}

function setupOrganizationEditor() {
  pqmMirrorContext_();
  const spreadsheet = pqmMirrorOpenById_(ORGANIZATION_EDITOR_CONFIG.spreadsheetId);
  const handler = 'organizationEditorOnOpen';
  ScriptApp.getProjectTriggers()
    .filter(function(trigger) {
      return trigger.getHandlerFunction() === handler;
    })
    .forEach(function(trigger) {
      ScriptApp.deleteTrigger(trigger);
    });

  ScriptApp.newTrigger(handler)
    .forSpreadsheet(spreadsheet)
    .onOpen()
    .create();

  organizationEditorOnOpen();
}

function openOrganizationEditorDialog() {
  pqmMirrorContext_();
  const html = HtmlService.createHtmlOutputFromFile('Dialog')
    .setWidth(1100)
    .setHeight(720);
  SpreadsheetApp.getUi().showModalDialog(html, 'Пошук і редагування ЮО');
}

function organizationEditorSearch(query) {
  query = organizationEditorNormalize_(query);
  if (query.length < 2) {
    throw new Error('Введіть щонайменше 2 символи назви або коду ЄДРПОУ.');
  }

  const sheet = organizationEditorGetSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow <= ORGANIZATION_EDITOR_CONFIG.headerRow) return [];

  const headers = organizationEditorGetHeaders_(sheet);
  const codeIndex = organizationEditorFindHeaderIndex_(headers, ORGANIZATION_EDITOR_CONFIG.codeHeader);
  const nameIndex = organizationEditorFindHeaderIndex_(headers, ORGANIZATION_EDITOR_CONFIG.nameHeader);
  const width = Math.max(codeIndex, nameIndex) + 1;
  const values = sheet
    .getRange(ORGANIZATION_EDITOR_CONFIG.headerRow + 1, 1, lastRow - ORGANIZATION_EDITOR_CONFIG.headerRow, width)
    .getDisplayValues();

  const queryDigits = organizationEditorDigits_(query);
  const looksLikeCode = queryDigits.length >= 4 && queryDigits === organizationEditorDigits_(query);
  const matches = [];

  for (let i = 0; i < values.length; i++) {
    const code = String(values[i][codeIndex] || '').trim();
    const name = String(values[i][nameIndex] || '').trim();
    const codeMatch = queryDigits && organizationEditorDigits_(code).includes(queryDigits);
    const nameMatch = organizationEditorNormalize_(name).includes(query);
    if ((looksLikeCode && codeMatch) || (!looksLikeCode && (nameMatch || codeMatch))) {
      matches.push({
        row: ORGANIZATION_EDITOR_CONFIG.headerRow + 1 + i,
        code: code,
        name: name
      });
      if (matches.length >= ORGANIZATION_EDITOR_CONFIG.maxResults) break;
    }
  }
  return matches;
}

function organizationEditorGetRow(rowNumber) {
  const sheet = organizationEditorGetSheet_();
  const lastRow = sheet.getLastRow();
  const lastColumn = sheet.getLastColumn();
  rowNumber = Number(rowNumber);
  if (!Number.isInteger(rowNumber) ||
      rowNumber <= ORGANIZATION_EDITOR_CONFIG.headerRow ||
      rowNumber > lastRow) {
    throw new Error('Рядок не знайдено.');
  }

  const headers = organizationEditorGetHeaders_(sheet);
  const range = sheet.getRange(rowNumber, 1, 1, lastColumn);
  const displayValues = range.getDisplayValues()[0];
  const rawValues = range.getValues()[0];
  const formulas = range.getFormulas()[0];
  const validations = range.getDataValidations()[0];
  const numberFormats = range.getNumberFormats()[0];
  const fields = headers.map(function(header, index) {
    const validation = validations[index];
    let options = [];
    if (validation &&
        validation.getCriteriaType() === SpreadsheetApp.DataValidationCriteria.VALUE_IN_LIST) {
      options = validation.getCriteriaValues()[0] || [];
    }

    const raw = rawValues[index];
    const isDate = raw instanceof Date ||
      /^Дата\b/i.test(header) ||
      /[dmy]/i.test(numberFormats[index] || '') &&
      !/0\.00|#,##0/i.test(numberFormats[index] || '');

    return {
      index: index,
      header: header || ('Колонка ' + organizationEditorColumnLetter_(index + 1)),
      value: isDate && raw instanceof Date
        ? organizationEditorDateToInput_(raw, displayValues[index])
        : displayValues[index],
      type: isDate ? 'date' : (options.length ? 'select' : organizationEditorInferTextType_(header)),
      options: options,
      readOnly: Boolean(formulas[index]) ||
        ['Дата перевірки ЄДР', 'Дата перевірки'].indexOf(header) >= 0 ||
        header === 'УО',
      hasFormula: Boolean(formulas[index])
    };
  });

  return {
    row: rowNumber,
    revisionToken: organizationEditorMakeRevisionToken_(displayValues),
    fields: fields
  };
}

function organizationEditorSaveRow(payload) {
  pqmMirrorContext_();
  if (!payload || !Array.isArray(payload.values)) {
    throw new Error('Некоректні дані форми.');
  }

  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const sheet = organizationEditorGetSheet_();
    const row = Number(payload.row);
    const lastColumn = sheet.getLastColumn();
    if (!Number.isInteger(row) ||
        row <= ORGANIZATION_EDITOR_CONFIG.headerRow ||
        row > sheet.getLastRow()) {
      throw new Error('Рядок більше не існує.');
    }
    if (payload.values.length !== lastColumn) {
      throw new Error('Структура таблиці змінилася. Закрийте форму і відкрийте її знову.');
    }

    const range = sheet.getRange(row, 1, 1, lastColumn);
    const currentDisplay = range.getDisplayValues()[0];
    if (payload.revisionToken !== organizationEditorMakeRevisionToken_(currentDisplay)) {
      throw new Error(
        'Цей рядок уже змінив інший користувач. Закрийте форму, відкрийте запис повторно та перевірте нові дані.'
      );
    }

    const formulas = range.getFormulas()[0];
    const numberFormats = range.getNumberFormats()[0];
    const values = range.getValues()[0];
    const headers = organizationEditorGetHeaders_(sheet);
    const verificationDateIndex = organizationEditorFindHeaderIndex_(
      headers,
      'Дата перевірки ЄДР'
    );
    const responsiblePersonIndex = organizationEditorFindHeaderIndex_(
      headers,
      'УО'
    );

    payload.values.forEach(function(value, index) {
      if (formulas[index]) {
        // setValues receives the whole row: retain the formula, not getValues' result.
        values[index] = formulas[index];
        return;
      }
      const text = value == null ? '' : String(value).trim();
      const isDate = /^Дата\b/i.test(headers[index]) ||
        /[dmy]/i.test(numberFormats[index] || '') &&
        !/0\.00|#,##0/i.test(numberFormats[index] || '');
      values[index] = isDate && text ? organizationEditorParseIsoDate_(text) : text;
    });

    const today = new Date();
    today.setHours(12, 0, 0, 0);
    values[verificationDateIndex] = today;
    values[responsiblePersonIndex] = organizationEditorGetUserName_();

    pqmMirrorRange_(range).setValues([values]);

    // Записуємо службові поля окремо й явно. Зміни, зроблені скриптом,
    // не запускають наявний простий тригер onEdit(e).
    sheet.getRange(row, verificationDateIndex + 1)
      .setValue(today)
      .setNumberFormat('dd.MM.yyyy')
      .setHorizontalAlignment('center');
    sheet.getRange(row, responsiblePersonIndex + 1)
      .setValue(values[responsiblePersonIndex])
      .setHorizontalAlignment('left');

    SpreadsheetApp.flush();

    const updatedDisplay = range.getDisplayValues()[0];
    return {
      ok: true,
      message: 'Дані рядка ' + row +
        ' збережено. Дату перевірки ЄДР та УО оновлено.',
      revisionToken: organizationEditorMakeRevisionToken_(updatedDisplay)
    };
  } finally {
    lock.releaseLock();
  }
}

function organizationEditorGetSheet_() {
  const spreadsheet = pqmMirrorOpenById_(ORGANIZATION_EDITOR_CONFIG.spreadsheetId);
  const sheet = spreadsheet.getSheetByName(ORGANIZATION_EDITOR_CONFIG.sheetName);
  if (!sheet) throw new Error('Вкладку «' + ORGANIZATION_EDITOR_CONFIG.sheetName + '» не знайдено.');
  return sheet;
}

function organizationEditorGetHeaders_(sheet) {
  return sheet.getRange(ORGANIZATION_EDITOR_CONFIG.headerRow, 1, 1, sheet.getLastColumn())
    .getDisplayValues()[0]
    .map(function(value) {
      return String(value || '').replace(/^\uFEFF/, '').trim();
    });
}

function organizationEditorFindHeaderIndex_(headers, expected) {
  const normalizedExpected = organizationEditorNormalize_(expected);
  const aliases = expected === 'Дата перевірки ЄДР' ?
    [normalizedExpected, organizationEditorNormalize_('Дата перевірки')] : [normalizedExpected];
  const matches = [];
  headers.forEach(function(header, index) {
    if (aliases.indexOf(organizationEditorNormalize_(header)) >= 0) matches.push(index);
  });
  if (matches.length !== 1) {
    throw new Error('Не знайдено колонку «' + expected + '».');
  }
  return matches[0];
}

function organizationEditorNormalize_(value) {
  return String(value == null ? '' : value)
    .toLocaleLowerCase('uk-UA')
    .replace(/[«»„“”"'`]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function organizationEditorDigits_(value) {
  return String(value == null ? '' : value).replace(/\D/g, '');
}

function organizationEditorParseIsoDate_(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error('Некоректна дата: ' + value);
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12, 0, 0);
}

function organizationEditorDateToInput_(dateValue, displayValue) {
  const displayed = String(displayValue || '').trim();
  let match = /^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$/.exec(displayed);
  if (match) {
    return match[3] + '-' +
      String(match[2]).padStart(2, '0') + '-' +
      String(match[1]).padStart(2, '0');
  }

  match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(displayed);
  if (match) {
    return match[1] + '-' +
      String(match[2]).padStart(2, '0') + '-' +
      String(match[3]).padStart(2, '0');
  }

  return dateValue.getFullYear() + '-' +
    String(dateValue.getMonth() + 1).padStart(2, '0') + '-' +
    String(dateValue.getDate()).padStart(2, '0');
}

function organizationEditorGetUserName_() {
  const userEmail = String(Session.getActiveUser().getEmail() || '')
    .trim()
    .toLowerCase();

  const users = {
    's.namiasenko@profzakupivli.com': 'Світлана НАМЯСЕНКО',
    't.fedchenko@profzakupivli.com': 'Тетяна ФЕДЧЕНКО',
    'o.yeromina@profzakupivli.com': 'Олена ЄРЬОМІНА',
    'd.savva@profzakupivli.com': 'Дмитро САВВА'
  };

  return users[userEmail] ||
    (userEmail ? userEmail.split('@')[0] : 'Невідомий користувач');
}

function organizationEditorInferTextType_(header) {
  return /Приміт|Реквізит|Повна назва|Найменування/i.test(header)
    ? 'textarea'
    : 'text';
}

function organizationEditorMakeRevisionToken_(values) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(values)
  );
  return Utilities.base64EncodeWebSafe(bytes);
}

function organizationEditorColumnLetter_(column) {
  let result = '';
  while (column > 0) {
    const remainder = (column - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    column = Math.floor((column - 1) / 26);
  }
  return result;
}
