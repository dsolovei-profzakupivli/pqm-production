(() => {
  const moduleKey = '__pqmOperationalTaskOfficerFilterV1';
  if (window[moduleKey]) return;

  const select = document.querySelector('#operationalTaskOfficer');
  const originalRequest = window.request;
  if (!select || typeof originalRequest !== 'function') return;
  window[moduleKey] = true;

  let latestListRequest = 0;
  function renderOfficers(officers) {
    if (!Array.isArray(officers)) return;
    const selected = select.value;
    const options = new Map();
    options.set('', 'Усі УО');
    for (const officer of officers) {
      const value = String(officer?.value ?? '').trim();
      if (!value) continue;
      const name = String(officer.full_name ?? '').trim() || `УО · ID ${value}`;
      options.set(value, `${name}${officer.historical_snapshot ? ' · Історична УО' : ''}`);
    }
    options.set('__unassigned__', 'Не призначено');
    if (selected && !options.has(selected)) options.set(selected, 'Вибрану УО не знайдено');

    select.replaceChildren(...[...options].map(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      return option;
    }));
    select.value = selected;
  }

  window.request = async function (url, ...args) {
    const isOperationalList = typeof url === 'string' && /\/operational-tasks(?:\?|$)/.test(url);
    const requestNumber = isOperationalList ? ++latestListRequest : 0;
    const result = await originalRequest.call(this, url, ...args);
    if (isOperationalList && requestNumber === latestListRequest) renderOfficers(result?.officers);
    return result;
  };

})();
