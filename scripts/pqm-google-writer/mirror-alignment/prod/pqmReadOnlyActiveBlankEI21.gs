function pqmReadOnlyActiveBlankEI21() {
  if (typeof PQM_MANAGER_D_BACKFILL === 'undefined') {
    throw new Error('Не знайдено manifest 135 кодів D-backfill');
  }
  const recent = new Set(
    PQM_MANAGER_D_BACKFILL.map(x => String(x[0]).trim())
      .concat(['24923488', '34833410', '45651847'])
  );
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('ЮО');
  const values = sheet.getRange(2, 2, sheet.getLastRow() - 1, 8).getDisplayValues(); // B:I
  const codes = values
    .filter(r => recent.has(r[0].trim())
      && (r[4].trim() === 'Активний' || r[4].trim().endsWith(' Активний'))
      && !r[3].trim() && !r[7].trim()) // E та I
    .map(r => r[0].trim())
    .sort();
  Logger.log(JSON.stringify({count: codes.length, codes: codes}));
}
