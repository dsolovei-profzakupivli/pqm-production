# PQM TEST WEB — інструкція для керівника

Це актуальний пакет із підтвердженого LOCAL READY стану від 01.09.2026. Пакет `PQM_TEST_WEB_DEPLOY_20260901_145224` є obsolete і не повинен використовуватися.

Ціль: існуючий repository `dsolovei-profzakupivli/pqm-production`, branch `main`, існуючий Render service `pqm-production-1`, persistent disk `/var/data`. Новий service, disk або database не створювати.

## 1. Обов'язково до зміни коду

1. Зафіксувати поточний working commit/deploy і можливість rollback.
2. Зробити snapshot persistent disk.
3. Через Render Shell створити окремий timestamped backup чинної TEST SQLite DB у `/var/data/backups/`.
4. Для DB і backup зафіксувати path, size, SHA-256, `integrity_check`, `foreign_key_check` і контрольні counts.
5. Якщо backup або перевірки неуспішні — deployment не виконувати.

## 2. Що завантажити

Завантажити **весь вміст цього package у корінь існуючого repository**, зберігаючи структуру папок. Саму зовнішню папку package не вкладати в repository. Не переносити жодних файлів поза package.

Перед commit перевірити всі записи `SHA256SUMS.txt` і весь Git diff/untracked content. SQLite, OAuth client/token, `.env`, secrets, паролі/хеші, logs, backups, cache, generated protocols, `node_modules`, локальні абсолютні шляхи та PII завантажувати заборонено.

## 3. Render environment gate

Перевірити без виведення secret values:

```text
PQM_ENV=test_web
PQM_DATA_DIR=/var/data
PQM_AUTH_ENABLED=1
PQM_USERS_JSON=<Render secret>
PQM_BIDS_MODE=disabled
PQM_ENABLE_BIDS_UPDATE=0
PQM_ENABLE_POWERBI=0
PQM_ENABLE_GOOGLE=0
PQM_ENABLE_BROWSER=0
```

Scheduler flags залишити за погодженою TEST-конфігурацією й не запускати кілька scheduler instances. Google вмикати тільки після окремого налаштування TEST OAuth secrets та HTTPS callback. LOCAL OAuth-файли не завантажувати.

## 4. Обов'язковий STOP/GO build gate

На підготовчому ноутбуці немає Docker/Podman/WSL, тому керівник повинен до commit:

1. Виконати Docker build із кореня repository.
2. Запустити isolated container з тимчасовою чистою DB і TEST env.
3. Перевірити `/api/health`, Basic Auth, static UI, JSON 404, runtime feature status, DOCX template list/download та `integrity_check`/`foreign_key_check` тимчасової DB.
4. Підтвердити, що Bids, Power BI, Google і schedulers у smoke вимкнені.

Якщо build або container smoke не проходить — STOP, commit/Auto-Deploy не виконувати.

## 5. Deploy і acceptance

Тільки після GO зробити commit у `main`; Auto-Deploy має оновити саме `pqm-production-1`. Не запускати full Prozorro sync або Bids update.

Після healthy deploy перевірити TEST banner/favicon/title, auth і ролі, Реєстр заявок, Роботу УО, актуальну чергу НАЗК, Базу постачальників, картку постачальника, Звернення, DOCX generate/regenerate/open/download, scheduler/status і persistence після restart. Повторити integrity/FK/counts. При corruption, auth lockout або критичному regression — STOP і rollback на попередній commit та DB snapshot/backup.
