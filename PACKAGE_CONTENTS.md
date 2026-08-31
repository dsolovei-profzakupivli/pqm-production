# PQM TEST WEB deployment package

Це контрольований source package актуальної локальної PQM для оновлення **існуючого** TEST Render service `pqm-production-1`.

Пакет повний і самодостатній. SQLite/ProzorroBids, credentials, backup, logs, cache та сформовані документи не включені.

## Включено

- runtime Python/HTML/CSS/JavaScript;
- Dockerfile та pinned Python/Node dependencies;
- server-side adapter `@prozorro/prozorro-eds`;
- OCR language resource;
- погоджені DOCX-шаблони протоколів;
- інструкції для deployment, security, rollback і smoke-test.

## Навмисно не включено

- будь-які SQLite/DB-файли, зокрема LOCAL PQM і ProzorroBids;
- `data`, `backups`, `output`, `generated_protocols`, cache, logs, temp;
- `.env`, OAuth credentials/tokens, паролі, ключі й API tokens;
- `node_modules`, `__pycache__`, Git metadata;
- Power BI exports та сформовані документи.

Перший запуск має відбуватися з `PQM_BIDS_MODE=disabled`, `PQM_ENABLE_GOOGLE=0`, вимкненими scheduler/Bids update/Power BI/browser.
