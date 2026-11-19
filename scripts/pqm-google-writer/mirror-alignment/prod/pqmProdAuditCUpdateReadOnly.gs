function pqmProdAuditCUpdateReadOnly() {
  const body = pqmProdFetchRegistry_();
  const tabs = pqmGoogleSnapshot_(pqmProdControlledSpreadsheetId_());
  const plan = pqmGooglePlan_(body, tabs);

  const rows = pqmProdPreviewChanges_(plan, tabs)
    .filter(x => x.column === 'C' && x.action === 'update')
    .map(x => ({
      supplier_code: x.supplier_code,
      row: x.row,
      old_value: x.old_value,
      proposed_value: x.proposed_value,
      action: x.action
    }));

  console.log(JSON.stringify(rows));
}
