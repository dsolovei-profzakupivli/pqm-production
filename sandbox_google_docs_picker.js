/* One administrative SANDBOX setup; normal appeal generation never opens Picker. */
(() => {
  const panel = document.getElementById('sandboxDocsPickerSetup');
  if (!panel || document.documentElement.dataset.pqmEnvironment !== 'sandbox') return;
  panel.hidden = false;
  const button = document.getElementById('sandboxDocsPickerStart');
  const status = document.getElementById('sandboxDocsPickerStatus');
  const steps = [
    ['warning', 'Попередження'],
    ['decline_p49_1_2', 'Відмова пп. 1/2'],
    ['decline_p49_3', 'Відмова пп. 3'],
    ['destination', 'Папка результатів'],
  ];
  let pickerLoad;
  let setupRunning = false;

  function render(verified, current = '', error = '', ready = false) {
    const lines = steps.map(([key, label]) => {
      const row = document.createElement('p');
      row.textContent = `${label} — ${verified.has(key) ? '✓ доступ підтверджено'
        : key === current ? 'очікує вибору' : 'не підтверджено'}`;
      return row;
    });
    const summary = document.createElement('strong');
    summary.textContent = `Google Docs для звернень — ${ready ? 'ГОТОВО' : 'НЕ ГОТОВО'}`;
    lines.push(summary);
    if (error) {
      const detail = document.createElement('p');
      detail.textContent = error;
      lines.push(detail);
    }
    status.replaceChildren(...lines);
  }

  function loadPicker() {
    if (pickerLoad) return pickerLoad;
    pickerLoad = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://apis.google.com/js/api.js';
      script.onload = () => {
        if (!window.gapi?.load) return reject(new Error('Google Picker API недоступний'));
        window.gapi.load('picker', {callback: resolve, onerror: reject});
      };
      script.onerror = () => reject(new Error('Не вдалося завантажити Google Picker API'));
      document.head.appendChild(script);
    }).catch(error => {pickerLoad = null; throw error;});
    return pickerLoad;
  }

  function pickConfigured(key, config) {
    const expected = config.resources?.[key];
    if (!expected || !/^[A-Za-z0-9_-]{20,100}$/.test(expected))
      throw new Error('Некоректний configured resource');
    const pickerApi = window.google?.picker;
    if (!pickerApi?.PickerBuilder || !pickerApi?.DocsView)
      throw new Error('Google Picker API недоступний');
    const view = new pickerApi.DocsView(key === 'destination'
      ? pickerApi.ViewId.FOLDERS : pickerApi.ViewId.DOCUMENTS).setFileIds(expected);
    if (key === 'destination') view.setSelectFolderEnabled(true);
    return new Promise((resolve, reject) => {
      let finished = false;
      const picker = new pickerApi.PickerBuilder()
        .setAppId(config.app_id)
        .setDeveloperKey(config.api_key)
        .setOAuthToken(config.access_token)
        .setOrigin(location.origin)
        .addView(view)
        .setCallback(async data => {
          if (finished || ![pickerApi.Action.CANCEL, pickerApi.Action.PICKED].includes(data?.action)) return;
          finished = true;
          picker.setVisible(false);
          if (data.action === pickerApi.Action.CANCEL)
            return reject(new Error('Вибір скасовано; setup зупинено.'));
          if (data.docs?.length !== 1 || data.docs[0]?.id !== expected)
            return reject(new Error('Обрано не погоджений ID; setup зупинено.'));
          try {
            const result = await request('/api/sandbox/admin/google-docs-picker/resource?key='
              + encodeURIComponent(key));
            if (result.id !== expected || result.is_app_authorized !== true)
              throw new Error('Backend не підтвердив доступ до exact ID');
            resolve();
          } catch (error) {reject(error);}
        }).build();
      picker.setVisible(true);
    });
  }

  button.addEventListener('click', async () => {
    setupRunning = true;
    button.disabled = true;
    const verified = new Set();
    let current = '';
    let config;
    render(verified, steps[0][0]);
    try {
      config = await request('/api/sandbox/admin/google-docs-picker/config');
      await loadPicker();
      for (const [key] of steps) {
        current = key;
        render(verified, current);
        await pickConfigured(key, config);
        verified.add(key);
        render(verified);
      }
      const finalCheck = await request('/api/sandbox/appeals-google-docs/access-check');
      if (finalCheck.ready_for_single_generation_test !== true
          || steps.some(([key]) => finalCheck[key] !== true))
        throw new Error('Підсумкова backend-перевірка доступу не пройдена');
      render(verified, '', '', true);
    } catch (error) {
      render(verified, current, error.message);
    } finally {
      if (config) config.access_token = '';
      button.disabled = false;
      setupRunning = false;
    }
  });

  // Google stores the per-file grant. Reconstruct the status after a reload
  // with metadata GETs; never open Picker or generate a document implicitly.
  authReady.then(async () => {
    if (currentMe?.role !== 'admin' || setupRunning) return;
    const verified = new Set();
    for (const [key] of steps) {
      try {
        const result = await request('/api/sandbox/admin/google-docs-picker/resource?key='
          + encodeURIComponent(key));
        if (result.is_app_authorized === true) verified.add(key);
      } catch { /* A missing grant is displayed as not confirmed. */ }
    }
    if (setupRunning) return;
    let ready = false;
    if (verified.size === steps.length) {
      try {
        ready = (await request('/api/sandbox/appeals-google-docs/access-check'))
          .ready_for_single_generation_test === true;
      } catch { /* Fail closed if the whole access check fails. */ }
    }
    render(verified, '', '', ready);
  }).catch(() => {});
})();
