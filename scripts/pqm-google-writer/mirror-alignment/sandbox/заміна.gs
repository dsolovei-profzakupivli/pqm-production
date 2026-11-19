// ==========================================================
// ПЕРЕВІРКА ПЕРЕД ПЕРЕНЕСЕННЯМ ДАНИХ
//
// ДЖЕРЕЛО:
// "Результати_Перевірки_ЄДР – копія_16.09"
//
// ПРИЙМАЧ:
// "Результати_Перевірки_ЄДР"
//
// Відбираємо тільки:
// I = 16.09.2026
// I = 17.09.2026
//
// Зіставлення:
// B — РНОКПП
//
// Майбутнє перенесення:
// I — Дата перевірки
// L — УО
//
// ЦЯ ФУНКЦІЯ НІЧОГО НЕ ЗМІНЮЄ!
// ==========================================================

function checkTransfer1609_1709() {
  throw new Error('SANDBOX historical transfer is quarantined; no reads or writes.');

  // --------------------------------------------------------
  // ID ТАБЛИЦЬ
  // --------------------------------------------------------

  const SOURCE_ID =
    "140Vd4RJiye2bHSMVpn74jJNeF5ACRtoJjWsESZh8VHw";

  const TARGET_ID =
    "1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww";

  const SHEET_NAME = "ФОП";

  const REQUIRED_DATES = [
    "16.09.2026",
    "17.09.2026"
  ];


  // --------------------------------------------------------
  // ВІДКРИВАЄМО ТАБЛИЦІ
  // --------------------------------------------------------

  const sourceSS = pqmMirrorOpenById_(SOURCE_ID);
  const sourceSheet = sourceSS.getSheetByName(SHEET_NAME);

  const targetSS = pqmMirrorOpenById_(TARGET_ID);
  const targetSheet = targetSS.getSheetByName(SHEET_NAME);

  if (!sourceSheet) {
    throw new Error(
      'У таблиці-джерелі не знайдено аркуш "ФОП".'
    );
  }

  if (!targetSheet) {
    throw new Error(
      'В основній таблиці не знайдено аркуш "ФОП".'
    );
  }


  // --------------------------------------------------------
  // ДОПОМІЖНА ФУНКЦІЯ ДЛЯ ДАТИ
  // --------------------------------------------------------

  function normalizeDate(value) {

    if (value === "" || value === null) {
      return "";
    }

    // Якщо Google Sheets повернув справжній Date
    if (
      Object.prototype.toString.call(value) === "[object Date]" &&
      !isNaN(value)
    ) {
      return Utilities.formatDate(
        value,
        Session.getScriptTimeZone(),
        "dd.MM.yyyy"
      );
    }

    // Якщо дата зберігається як текст
    return value.toString().trim();
  }


  // --------------------------------------------------------
  // ЧИТАЄМО ДЖЕРЕЛО
  //
  // B:L
  //
  // B = row[0]  — РНОКПП
  // I = row[7]  — Дата перевірки
  // L = row[10] — УО
  // --------------------------------------------------------

  const sourceLastRow = sourceSheet.getLastRow();

  if (sourceLastRow < 2) {
    throw new Error(
      "У таблиці-джерелі немає даних."
    );
  }

  const sourceData = sourceSheet
    .getRange(
      2,
      2,
      sourceLastRow - 1,
      11
    )
    .getValues();


  // --------------------------------------------------------
  // ВІДБИРАЄМО ТІЛЬКИ 16.09 ТА 17.09
  // --------------------------------------------------------

  const selectedRows = [];

  const countByDate = {
    "16.09.2026": 0,
    "17.09.2026": 0
  };

  sourceData.forEach((row, index) => {

    const sheetRow = index + 2;

    const code = row[0]
      ? row[0].toString().trim()
      : "";

    const checkDate =
      normalizeDate(row[7]);

    const uo = row[10]
      ? row[10].toString().trim()
      : "";

    if (
      REQUIRED_DATES.indexOf(checkDate) !== -1
    ) {

      selectedRows.push({
        row: sheetRow,
        code: code,
        checkDate: checkDate,
        uo: uo
      });

      countByDate[checkDate]++;
    }

  });


  // --------------------------------------------------------
  // ПЕРЕВІРКА ДУБЛІКАТІВ РНОКПП У ДЖЕРЕЛІ
  // --------------------------------------------------------

  const sourceCodeCount = {};
  const emptySourceCodes = [];

  selectedRows.forEach(item => {

    if (item.code === "") {

      emptySourceCodes.push(item.row);

    } else {

      if (!sourceCodeCount[item.code]) {
        sourceCodeCount[item.code] = 0;
      }

      sourceCodeCount[item.code]++;
    }

  });


  const duplicateSourceCodes =
    Object.keys(sourceCodeCount)
      .filter(code =>
        sourceCodeCount[code] > 1
      );


  // --------------------------------------------------------
  // ЧИТАЄМО ОСНОВНУ ТАБЛИЦЮ
  // --------------------------------------------------------

  const targetLastRow =
    targetSheet.getLastRow();

  if (targetLastRow < 2) {
    throw new Error(
      "В основній таблиці немає даних."
    );
  }


  // Читаємо B, I та L
  const targetCodes = targetSheet
    .getRange(
      2,
      2,
      targetLastRow - 1,
      1
    )
    .getValues();

  const targetDates = targetSheet
    .getRange(
      2,
      9,
      targetLastRow - 1,
      1
    )
    .getValues();

  const targetUOs = targetSheet
    .getRange(
      2,
      12,
      targetLastRow - 1,
      1
    )
    .getValues();


  // --------------------------------------------------------
  // СТВОРЮЄМО МАПУ ОСНОВНОЇ ТАБЛИЦІ
  //
  // РНОКПП -> рядок/рядки
  // --------------------------------------------------------

  const targetMap = {};

  for (
    let i = 0;
    i < targetCodes.length;
    i++
  ) {

    const code = targetCodes[i][0]
      ? targetCodes[i][0]
          .toString()
          .trim()
      : "";

    if (code === "") {
      continue;
    }

    if (!targetMap[code]) {
      targetMap[code] = [];
    }

    targetMap[code].push({
      row: i + 2,
      date: normalizeDate(
        targetDates[i][0]
      ),
      uo: targetUOs[i][0]
        ? targetUOs[i][0]
            .toString()
            .trim()
        : ""
    });

  }


  // --------------------------------------------------------
  // ЗІСТАВЛЯЄМО
  // --------------------------------------------------------

  let foundCount = 0;

  let rowsThatWouldChange = 0;

  let datesThatWouldChange = 0;

  let uosThatWouldChange = 0;

  const missingCodes = [];

  const duplicateTargetCodes = [];


  selectedRows.forEach(item => {

    if (item.code === "") {
      return;
    }

    const matches =
      targetMap[item.code];

    if (
      !matches ||
      matches.length === 0
    ) {

      missingCodes.push({
        code: item.code,
        sourceRow: item.row
      });

      return;
    }


    foundCount++;


    // Якщо один РНОКПП зустрічається
    // кілька разів в основній таблиці
    if (matches.length > 1) {

      duplicateTargetCodes.push({
        code: item.code,
        rows: matches
          .map(x => x.row)
          .join(", ")
      });

    }


    // Перевіряємо кожний знайдений рядок
    matches.forEach(match => {

      let rowWouldChange = false;


      // Дата
      if (
        match.date !==
        item.checkDate
      ) {

        datesThatWouldChange++;
        rowWouldChange = true;

      }


      // УО
      if (
        match.uo !==
        item.uo
      ) {

        uosThatWouldChange++;
        rowWouldChange = true;

      }


      if (rowWouldChange) {
        rowsThatWouldChange++;
      }

    });

  });


  // --------------------------------------------------------
  // ФОРМУЄМО ЗВІТ
  // --------------------------------------------------------

  let message =

    "ПЕРЕВІРКА ЗАВЕРШЕНА\n" +
    "НІЧОГО НЕ ЗМІНЕНО.\n\n" +

    "У джерелі знайдено:\n" +

    "16.09.2026 — " +
    countByDate["16.09.2026"] +
    " рядків\n" +

    "17.09.2026 — " +
    countByDate["17.09.2026"] +
    " рядків\n\n" +

    "РАЗОМ: " +
    selectedRows.length +
    " рядків\n\n" +

    "Знайдено в основній таблиці: " +
    foundCount +
    "\n" +

    "Не знайдено РНОКПП: " +
    missingCodes.length +
    "\n\n" +

    "Було б змінено рядків: " +
    rowsThatWouldChange +
    "\n" +

    "Змін дат: " +
    datesThatWouldChange +
    "\n" +

    "Змін УО: " +
    uosThatWouldChange +
    "\n\n" +

    "Дублі РНОКПП у джерелі: " +
    duplicateSourceCodes.length +
    "\n" +

    "Дублі РНОКПП в основній: " +
    duplicateTargetCodes.length +
    "\n" +

    "Порожніх РНОКПП у джерелі: " +
    emptySourceCodes.length;


  // --------------------------------------------------------
  // ДОДАЄМО НЕЗНАЙДЕНІ КОДИ
  // --------------------------------------------------------

  if (missingCodes.length > 0) {

    message +=
      "\n\nНЕ ЗНАЙДЕНО:\n";

    missingCodes.forEach(item => {

      message +=
        item.code +
        " (рядок джерела " +
        item.sourceRow +
        ")\n";

    });

  }


  // --------------------------------------------------------
  // ДОДАЄМО ДУБЛІ В ОСНОВНІЙ
  // --------------------------------------------------------

  if (
    duplicateTargetCodes.length > 0
  ) {

    message +=
      "\n\nДУБЛІ В ОСНОВНІЙ:\n";

    duplicateTargetCodes
      .forEach(item => {

        message +=
          item.code +
          " — рядки " +
          item.rows +
          "\n";

      });

  }


  // --------------------------------------------------------
  // ПОКАЗУЄМО РЕЗУЛЬТАТ
  // --------------------------------------------------------

  SpreadsheetApp
    .getUi()
    .alert(message);


  // Також пишемо повний звіт у журнал
  Logger.log(message);
}

// ==========================================================
// ПЕРЕНЕСЕННЯ ДАТИ ПЕРЕВІРКИ ТА УО
//
// ДЖЕРЕЛО:
// "Результати_Перевірки_ЄДР – копія_16.09"
//
// ПРИЙМАЧ:
// "Результати_Перевірки_ЄДР"
//
// Беремо тільки рядки:
// I = 16.09.2026
// I = 17.09.2026
//
// Зіставлення:
// B — РНОКПП
//
// ОНОВЛЮЄМО ТІЛЬКИ:
// I — Дата перевірки
// L — УО
// ==========================================================

function transferDateAndUO1609_1709() {
  pqmMirrorContext_();
  throw new Error('SANDBOX historical transfer is quarantined; no reads or writes.');

  const SOURCE_ID =
    "140Vd4RJiye2bHSMVpn74jJNeF5ACRtoJjWsESZh8VHw";

  const TARGET_ID =
    "1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww";

  const SHEET_NAME = "ФОП";

  const REQUIRED_DATES = [
    "16.09.2026",
    "17.09.2026"
  ];


  // ========================================================
  // ВІДКРИВАЄМО ТАБЛИЦІ
  // ========================================================

  const sourceSS =
    pqmMirrorOpenById_(SOURCE_ID);

  const sourceSheet =
    sourceSS.getSheetByName(SHEET_NAME);

  const targetSS =
    pqmMirrorOpenById_(TARGET_ID);

  const targetSheet =
    targetSS.getSheetByName(SHEET_NAME);


  if (!sourceSheet) {
    throw new Error(
      'У таблиці-джерелі не знайдено аркуш "ФОП".'
    );
  }

  if (!targetSheet) {
    throw new Error(
      'В основній таблиці не знайдено аркуш "ФОП".'
    );
  }


  // ========================================================
  // НОРМАЛІЗАЦІЯ ДАТИ
  // ========================================================

  function normalizeDate(value) {

    if (value === "" || value === null) {
      return "";
    }

    if (
      Object.prototype.toString.call(value) === "[object Date]" &&
      !isNaN(value)
    ) {

      return Utilities.formatDate(
        value,
        Session.getScriptTimeZone(),
        "dd.MM.yyyy"
      );

    }

    return value.toString().trim();
  }


  // ========================================================
  // ЧИТАЄМО ДЖЕРЕЛО B:L
  //
  // B = row[0]  — РНОКПП
  // I = row[7]  — Дата перевірки
  // L = row[10] — УО
  // ========================================================

  const sourceLastRow =
    sourceSheet.getLastRow();

  const sourceData =
    sourceSheet
      .getRange(
        2,
        2,
        sourceLastRow - 1,
        11
      )
      .getValues();


  // ========================================================
  // СТВОРЮЄМО СЛОВНИК ТІЛЬКИ ДЛЯ 16.09 І 17.09
  // ========================================================

  const sourceMap = {};

  let sourceCount = 0;

  sourceData.forEach(row => {

    const code = row[0]
      ? row[0].toString().trim()
      : "";

    const checkDate =
      normalizeDate(row[7]);

    const uo = row[10]
      ? row[10].toString().trim()
      : "";


    if (
      code !== "" &&
      REQUIRED_DATES.indexOf(checkDate) !== -1
    ) {

      sourceMap[code] = {
        checkDate: checkDate,
        uo: uo
      };

      sourceCount++;
    }

  });


  // ========================================================
  // ЗАПОБІЖНИК №1
  //
  // Ми вже перевірили, що має бути рівно 400.
  // Якщо раптом джерело змінилося — НІЧОГО НЕ ЗАПИСУЄМО.
  // ========================================================

  if (sourceCount !== 400) {

    SpreadsheetApp.getUi().alert(
      "ЗАПИС СКАСОВАНО.\n\n" +
      "Очікувалося 400 рядків,\n" +
      "але зараз знайдено: " +
      sourceCount +
      ".\n\n" +
      "Жодних змін не внесено."
    );

    return;
  }


  // ========================================================
  // ЧИТАЄМО ОСНОВНУ ТАБЛИЦЮ
  // ========================================================

  const targetLastRow =
    targetSheet.getLastRow();


  // B — РНОКПП
  const targetCodes =
    targetSheet
      .getRange(
        2,
        2,
        targetLastRow - 1,
        1
      )
      .getValues();


  // I — Дата перевірки
  const dateRange =
    targetSheet
      .getRange(
        2,
        9,
        targetLastRow - 1,
        1
      );

  const dates =
    dateRange.getValues();


  // L — УО
  const uoRange =
    targetSheet
      .getRange(
        2,
        12,
        targetLastRow - 1,
        1
      );

  const uos =
    uoRange.getValues();


  // ========================================================
  // СПОЧАТКУ ПЕРЕВІРЯЄМО ВСІ 400
  //
  // ВАЖЛИВО:
  // до цього моменту НІЧОГО НЕ ЗАПИСУЄМО
  // ========================================================

  const targetMap = {};

  for (let i = 0; i < targetCodes.length; i++) {

    const code = targetCodes[i][0]
      ? targetCodes[i][0].toString().trim()
      : "";

    if (code === "") {
      continue;
    }

    if (!targetMap[code]) {
      targetMap[code] = [];
    }

    targetMap[code].push(i);
  }


  const missingCodes = [];
  const duplicateCodes = [];


  Object.keys(sourceMap).forEach(code => {

    const matches = targetMap[code];

    if (!matches || matches.length === 0) {

      missingCodes.push(code);

    } else if (matches.length > 1) {

      duplicateCodes.push(code);

    }

  });


  // ========================================================
  // ЗАПОБІЖНИК №2
  //
  // Якщо хоча б один код:
  // - не знайдено
  // - або знайдено більше одного разу
  //
  // НІЧОГО НЕ ЗАПИСУЄМО
  // ========================================================

  if (
    missingCodes.length > 0 ||
    duplicateCodes.length > 0
  ) {

    let message =
      "ЗАПИС СКАСОВАНО.\n\n" +
      "Не знайдено РНОКПП: " +
      missingCodes.length +
      "\n" +
      "Дублів РНОКПП: " +
      duplicateCodes.length +
      "\n\n" +
      "Жодних змін не внесено.";


    if (missingCodes.length > 0) {

      message +=
        "\n\nНе знайдено:\n" +
        missingCodes.join("\n");

    }


    if (duplicateCodes.length > 0) {

      message +=
        "\n\nДублі:\n" +
        duplicateCodes.join("\n");

    }


    SpreadsheetApp
      .getUi()
      .alert(message);

    return;
  }


  // ========================================================
  // ВСІ 400 ПРОЙШЛИ ПЕРЕВІРКУ
  // ТЕПЕР ГОТУЄМО ЗМІНИ
  // ========================================================

  let matchedCount = 0;
  let changedRows = 0;
  let changedDates = 0;
  let changedUOs = 0;


  Object.keys(sourceMap).forEach(code => {

    // Ми вже перевірили,
    // що для кожного коду рівно один рядок
    const index = targetMap[code][0];

    const item = sourceMap[code];


    const oldDate =
      normalizeDate(dates[index][0]);

    const oldUO =
      uos[index][0]
        ? uos[index][0].toString().trim()
        : "";


    let rowChanged = false;


    // ------------------------------------------------------
    // I — ДАТА ПЕРЕВІРКИ
    // ------------------------------------------------------

    if (oldDate !== item.checkDate) {

      // Записуємо дату як справжню дату,
      // а не просто текст.

      const parts =
        item.checkDate.split(".");

      const newDate =
        new Date(
          Number(parts[2]),
          Number(parts[1]) - 1,
          Number(parts[0])
        );

      dates[index][0] = newDate;

      changedDates++;
      rowChanged = true;
    }


    // ------------------------------------------------------
    // L — УО
    // ------------------------------------------------------

    if (oldUO !== item.uo) {

      uos[index][0] = item.uo;

      changedUOs++;
      rowChanged = true;
    }


    if (rowChanged) {
      changedRows++;
    }


    matchedCount++;
  });


  // ========================================================
  // ФІНАЛЬНИЙ ЗАПОБІЖНИК
  // ========================================================

  if (matchedCount !== 400) {

    SpreadsheetApp.getUi().alert(
      "ЗАПИС СКАСОВАНО.\n\n" +
      "Перед записом отримано " +
      matchedCount +
      " відповідностей замість 400.\n\n" +
      "Жодних змін не внесено."
    );

    return;
  }


  // ========================================================
  // ЗАПИС
  //
  // ЗМІНЮЄМО ТІЛЬКИ I ТА L
  // ========================================================

  pqmMirrorRange_(dateRange).setValues(dates);

  pqmMirrorRange_(uoRange).setValues(uos);


  // Формат дати в I
  pqmMirrorRange_(dateRange).setNumberFormat("dd.MM.yyyy");


  SpreadsheetApp.flush();


  // ========================================================
  // РЕЗУЛЬТАТ
  // ========================================================

  SpreadsheetApp
    .getUi()
    .alert(
      "ГОТОВО.\n\n" +

      "Опрацьовано РНОКПП: " +
      matchedCount +
      "\n" +

      "Оновлено рядків: " +
      changedRows +
      "\n" +

      "Оновлено дат: " +
      changedDates +
      "\n" +

      "Оновлено УО: " +
      changedUOs +
      "\n\n" +

      "Інші стовпці не змінювалися."
    );
}
