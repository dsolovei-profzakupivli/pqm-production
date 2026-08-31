# PQM TEST WEB — аудит готовності та план заміни існуючого Render deployment

Дата аудиту: 27.08.2026  
Цільовий сервіс: `https://pqm-production-1.onrender.com`  
Статус: **AUDIT ONLY — deployment не виконувати**

> **Оновлення 30.08.2026.** Розділи 1–9 нижче збережені як історія початкового аудиту. Актуальний стан готовності та єдиний чинний порядок наступних дій наведено в розділі 10. Deployment у межах цього етапу не виконувався.

## 1. Рішення за результатом аудиту

Поточну локальну версію **ще не можна безпечно розгортати** на існуючий Render service. Причини:

1. Локальна папка не є Git-репозиторієм і не містить `render.yaml`, `Procfile`, `Dockerfile`, `runtime.txt`, `.python-version` або іншого відтворюваного deployment manifest.
2. Фактичні repository, branch, commit, build/start command, env vars і persistent disk існуючого сервісу недоступні з публічного URL. Їх потрібно переписати з Render Dashboard до будь-якої заміни.
3. Поточний `server.py` слухає тільки `127.0.0.1:8080`, відкриває браузер і безумовно запускає локальні планувальники. Для Render потрібні `0.0.0.0:$PORT`, вимкнений browser launch і контроль одного scheduler leader.
4. Основна SQLite-БД має фіксований repo-relative шлях, а Render зберігає тільки дані під mount path persistent disk. Потрібен env-configurable `PQM_DB_PATH`.
5. ProzorroBids прив’язано до Windows-шляхів `D:\ProzorroBids`; ручне оновлення Bids і Power BI запускають локальні subprocess/експорти. У першому TEST WEB їх треба fail-closed вимкнути або підключити окреме read-only джерело.
6. Google OAuth використовує localhost callback і локальні файли в `%LOCALAPPDATA%`. У TEST WEB Google-функції мають бути вимкнені до окремого HTTPS OAuth налаштування.
7. OCR/document-check залежить від Windows-шляхів Tesseract і Poppler. DOCX-генератор переносимий, але OCR у першому TEST WEB без Linux-пакетів не готовий.
8. Поточний local source не має server-side authentication/RBAC. Role у UI не є автентифікацією. Публічний Render зараз захищений Basic auth, але джерело цієї реалізації не знайдено ані в актуальному local source, ані в локальному пакеті від 21.08.2026.
9. API не має єдиного JSON error envelope: невідомі маршрути повертають HTML через `send_error`, а необроблені винятки можуть дати обрив з’єднання. Це узгоджується з класом помилки `Unexpected token '<'`, але точний старий endpoint можна встановити лише з Render logs.
10. Startup виконує ad-hoc schema changes і seed/backfill без таблиці версій міграцій та окремого rollback. Стару WEB-БД не можна оновлювати на місці без snapshot і тесту на її копії.

Отже, наступний безпечний крок — **отримати read-only конфігурацію Render Dashboard та старої WEB-БД**, після чого окремим погодженим етапом внести web-compatibility зміни в код. Цей документ не є командою deploy.

## 2. Що фактично встановлено

### 2.1. Існуючий TEST WEB

- URL відповідає.
- `GET /` без credentials повертає `401` у JSON і `WWW-Authenticate: Basic`.
- Header origin: `PQM/0.1 Python/3.12.14`.
- `GET /api/health` доступний і 27.08.2026 повернув `ok=true`.
- WEB-БД на момент перевірки: `190` frameworks, `79 224` submissions, `79 237` qualifications.
- Вбудований hourly scheduler працює: останній incremental run обробив `126/126`, помилок `0`, тривалість близько `251 с`.

Це підтверджує працездатність старого deployment, але **не розкриває його repository/commit/config/disk**.

### 2.2. Актуальна LOCAL-версія

- Основна БД: `data/pqm.sqlite3`, 1 279 647 744 байти.
- `PRAGMA integrity_check = ok` (6,73 с).
- `PRAGMA foreign_key_check`: 0 порушень.
- Повний test suite: `120 tests`, `OK` (174,536 с).
- У тестах є `ResourceWarning` про незакриті SSL sockets. Це не провал тестів, але для довгоживучого WEB-процесу потребує окремого виправлення/перевірки connection lifecycle.
- Локальна ProzorroBids: `D:\ProzorroBids\prozorro_bids.db`, 31 739 973 632 байти.
- ProzorroBids `quick_check = ok`, FK-порушень 0; counts: agreements `188`, tenders `514 257`, bids `1 333 479`, awards `595 468`. Read-only перевірка тривала 522,38 с.

### 2.3. Схема старої локальної версії 21.08.2026

Порівняно з актуальною схемою в старій копії немає нових workflow/admin таблиць, зокрема `authorized_officers`, `framework_service_directory`, `submission_nazk_controls`, `supplier_managers`, `supplier_nazk_check_*`, `violation_report_document_reviews`, `violation_report_review_events`; також бракує нових колонок у `application_fields`, `framework_officers`, `violation_report_reviews`.

Поточний `init_db()` технічно містить ad-hoc `CREATE/ALTER`, але цього недостатньо для безпечного WEB upgrade: немає migration version, dry-run report, atomic deployment plan і DB rollback.

## 3. Класи даних і рекомендована TEST-БД

Не переносити local `pqm.sqlite3` цілком: у ньому є тестові ручні рішення.

Умовний поділ:

- відновлювані кеші Prozorro: `frameworks`, `submissions`, `qualifications`, `registry_contracts`, source-частина `violation_reports`;
- ручні/предметні дані, які не можна втрачати в реальному середовищі: ручні поля `application_fields`, `audit_log`, authorized officers, service directory overrides, remarks, НАЗК workflow/control/history, violation reviews/events/document reviews;
- довідники/імпорти: EDR profiles, AMCU/NAZK registries та sync metadata — переносити тільки за окремо погодженим seed/import plan.

Для TEST рекомендовано окремий файл на persistent disk, наприклад `/var/data/pqm-test.sqlite3`. Остаточний шлях визначити лише після аудиту фактичного mount path існуючого сервісу.

Перед вибором clean DB або upgrade старої WEB-БД потрібно з Render Shell виконати read-only inventory старої WEB-БД: шлях, розмір, SHA-256, schema, counts, `integrity_check`, `foreign_key_check`, перелік ручних review/audit records. Старі test writes не переносяться автоматично.

## 4. Обов’язкові зміни коду перед deployment

1. Додати `PQM_ENV=local|test|production`; для цієї цілі використовувати тільки `test`.
2. Host/port: `PQM_HOST` default local; на Render `0.0.0.0`; port з `PORT`.
3. DB path: `PQM_DB_PATH`; усі generated protocols/cache/temp — під окремими configurable paths.
4. Browser launch — тільки local.
5. Scheduler: `PQM_ENABLE_SCHEDULER`; один процес/leader lock; заборонити дубльований scheduler при кількох workers/redeploy overlap.
6. Explicit outbound policy: `PQM_PROZORRO_WRITE_ENABLED=0`. Навіть якщо зараз виклики Prozorro read-only, TEST повинен fail-closed блокувати майбутні write methods.
7. Bids: `PQM_BIDS_MODE=disabled|readonly`; у TEST за замовчуванням `disabled`. Заборонити `/api/bids-sync` і Power BI export у TEST.
8. Google: `PQM_GOOGLE_ENABLED=0` за замовчуванням; credentials тільки Render secrets, HTTPS callback — окремим етапом.
9. OCR: `PQM_OCR_ENABLED=0` до Linux dependency setup; показувати зрозумілий JSON status, а не timeout.
10. Auth: зберегти існуючий Basic auth для обмеженого TEST доступу та окремо реалізувати server-side identity/role validation для write API. Не довіряти полям `role/user` з браузера.
11. Для всіх `/api/*` повертати JSON і коректний HTTP status навіть при 404/500; додати request ID і server logging. Frontend має перевіряти content type перед `response.json()`.
12. Винести schema upgrade в явну versioned migration із backup, dry-run/schema check і fail-closed поведінкою.
13. Закривати HTTP/SSL responses через context manager; провести WEB load test документних endpoint-ів.
14. Додати `.python-version` або точний `PYTHON_VERSION=3.12.14`; актуалізувати requirements і Linux system dependencies.

## 5. Рекомендована архітектура першого TEST WEB

- Той самий існуючий Render Web Service і той самий домен.
- Один instance і один Python process на першому етапі, щоб SQLite і scheduler не мали конкурентних writers.
- Basic auth увімкнений; URL не вважати публічною production-системою.
- Окрема TEST SQLite на persistent disk.
- Prozorro source adapter — read/sync only.
- ProzorroBids — disabled або окремий read-only snapshot/service після оцінки диска; 31,7 ГБ не копіювати автоматично.
- Google/OCR — feature flags off, доки не налаштовані окремо.
- Health endpoint не повинен розкривати секрети; health check path `/api/health`.
- Generated DOCX або віддавати на вимогу з temp, або зберігати під persistent output path з політикою очищення. Еталонні templates залишаються у read-only build artifact.

## 6. Дані, які потрібно переписати з Render Dashboard

До deploy заповнити цей блок фактичними значеннями:

| Налаштування | Фактичне значення | Статус |
|---|---|---|
| Service ID/name | невідомо | потрібен Dashboard |
| Repository | невідомо | потрібен Dashboard |
| Branch | невідомо | потрібен Dashboard |
| Running commit / deploy ID | невідомо | потрібні Events |
| Auto-deploy | невідомо | потрібен Dashboard |
| Root directory | невідомо | потрібен Dashboard |
| Build command | невідомо | потрібен Dashboard |
| Pre-deploy command | невідомо | потрібен Dashboard |
| Start command | невідомо | потрібен Dashboard |
| Health check path | невідомо | потрібен Dashboard |
| Runtime/Python setting | runtime фактично 3.12.14; source setting невідоме | частково |
| Instance type/count | невідомо | потрібен Dashboard |
| Persistent disk size/mount | невідомо | потрібні Disks |
| DB path | невідомо | потрібен Shell/Environment |
| Env var names (без secret values у звіті) | невідомо | потрібен Environment |
| Scheduler mechanism | вбудований scheduler фактично працює; зовнішні jobs невідомі | частково |
| Basic auth source/secret | фактично увімкнено; реалізація невідома | критично |
| Old DB inventory | невідомо | потрібен read-only Shell audit |

Secret values не копіювати в цей файл або журнал.

## 7. План deployment після окремого погодження

### Gate A — source/config

1. Встановити точний repo/branch/commit старого deploy.
2. Зберегти screenshots/export налаштувань Render без secret values.
3. Переконатися, що старий successful deploy доступний для rollback.
4. Тимчасово вимкнути auto-deploy або працювати з контрольованим commit.
5. Помістити актуальний source у version-controlled repo/branch; deployment commit має бути immutable і протестований.

### Gate B — disk/DB

1. Зупинити scheduler/write activity у погоджене вікно.
2. Зробити Render disk snapshot та окрему SQLite backup старої WEB-БД.
3. Зафіксувати SHA-256, counts, integrity/FK.
4. Прогнати migration на копії старої WEB-БД або створити clean TEST DB — після inventory і окремого рішення.
5. Не змішувати TEST DB з local manual test DB.

### Gate C — deploy

1. Встановити env flags `PQM_ENV=test`, write protection, Bids/Google/OCR policy.
2. Build command орієнтовно `pip install -r requirements.txt` — остаточно після repo audit.
3. Start command — лише після web bootstrap refactor; процес має bind `0.0.0.0:$PORT`.
4. Розгорнути конкретний commit на тому самому service.
5. Не видаляти старий deployment.

### Gate D — smoke test

1. Basic auth і відсутність неавторизованого доступу.
2. `/api/health`.
3. Реєстр заявок, База постачальників, Відбори, Робота УО, Довідники, Звернення.
4. Safe TEST writes: збереження ручного поля, reopening, audit log; ніяких writes у Prozorro.
5. Документний download і DOCX generation із виміром часу.
6. Scheduler: один run, без дублювання, без блокування SQLite.
7. JSON error envelope для 401/404/422/500.
8. Після smoke повторити DB integrity/FK та counts.

## 8. Rollback

Code rollback недостатній, якщо схема/дані змінилися.

1. Зупинити TEST write/scheduler.
2. У Render Events виконати rollback на зафіксований successful deployment 21.08.2026, якщо його artifact ще доступний.
3. Відновити відповідний disk snapshot/SQLite backup, якщо новий код змінив DB.
4. Перевірити env/config, бо rollback deployment не гарантує відкат поточного disk state та всіх service settings.
5. Перевірити `/api/health`, Basic auth і counts.
6. Auto-deploy не вмикати до аналізу причини rollback.

## 9. Що заборонено на цьому етапі

- Не створювати інший Render service/domain.
- Не deploy без Dashboard inventory.
- Не видаляти deployment 21.08.2026.
- Не запускати повну Prozorro sync.
- Не копіювати 31,7 ГБ ProzorroBids без окремого storage/read-only plan.
- Не commit Google OAuth tokens, Basic auth secrets або інші credentials.
- Не переносити local test decisions у WEB автоматично.
- Не запускати schema migration на єдиній WEB-БД без snapshot і перевіреної копії.

## 10. Актуальний deployment layer після підготовки 30.08.2026

### 10.1. Що вже підготовлено

- Додано відтворюваний `Dockerfile` для Python 3.12/Linux із LibreOffice, Poppler, Tesseract (`ukr`), Node.js і pinned `@prozorro/prozorro-eds` через frozen `pnpm-lock.yaml`.
- `server.py` підтримує `PQM_ENV`, `HOST`/`PORT`, `PQM_DATA_DIR`, `PQM_DB_PATH`, окремі каталоги протоколів/cache та Linux-шляхи OCR.
- У WEB browser auto-open і вбудовані schedulers вимкнені за замовчуванням. У першому TEST deployment залишити один web process і не вмикати schedulers до окремої перевірки single-leader поведінки.
- Реалізовано server-side Basic Auth через `PQM_AUTH_ENABLED` і `PQM_USERS_JSON`; секрети читаються лише з environment. `/api/health` лишається відкритим для Render health check, решта API захищені.
- API-помилки повертаються як JSON, включно з 401/404/500 та контрольованою недоступністю локальних функцій.
- Google OAuth/Docs, Bids update та Power BI мають feature flags і в TEST WEB за замовчуванням fail-closed disabled.
- ProzorroBids reader підтримує `disabled|readonly`; write/update у TEST заборонені.
- Додано `.gitignore` і `.dockerignore` для SQLite, великих Bids, backup/output/cache, OAuth credentials/tokens, `.env`, ключів і тимчасових файлів.

### 10.2. Обов'язкові Render environment variables

```text
PQM_ENV=test_web
HOST=0.0.0.0
PORT=10000
PQM_DATA_DIR=/var/data
PQM_DB_PATH=/var/data/pqm.sqlite3
PQM_AUTH_ENABLED=1
PQM_USERS_JSON=<Render secret JSON; значення не зберігати у Git>
PQM_ENABLE_BROWSER=0
PQM_ENABLE_SCHEDULER=0
PQM_ENABLE_NAZK_SCHEDULER=0
PQM_BIDS_MODE=disabled
PQM_ENABLE_BIDS_UPDATE=0
PQM_ENABLE_POWERBI=0
PQM_ENABLE_GOOGLE=0
```

Опційно після окремого тесту:

```text
PQM_BIDS_MODE=readonly
PQM_BIDS_DB=/var/data/prozorro_bids_derived.sqlite3
PQM_ENABLE_GOOGLE=1
PQM_GOOGLE_OAUTH_CLIENT_JSON=<Render secret>
PQM_GOOGLE_OAUTH_REDIRECT_URI=https://pqm-production-1.onrender.com/api/google-oauth/callback
```

### 10.3. Bids storage plan

- Повну локальну БД `D:\ProzorroBids\prozorro_bids.db` розміром `31 937 015 808` байт не переносити на диск Render 10 GB.
- Контрольні counts: `agreements=188`, `tenders=516986`, `bids=1337775`, `awards=597768`.
- Для TEST WEB окремим етапом локально сформувати compact read-only snapshot лише з потрібними колонками `agreements/tenders/bids/awards`, без `raw_json` та update-службових payload. До deployment виміряти фактичний розмір, виконати integrity/FK/counts, зафіксувати SHA-256.
- Завантажувати snapshot у staging filename під `/var/data`, перевіряти, а потім атомарно перемикати `PQM_BIDS_DB`. Web updater не вмикати.
- До готовності compact snapshot залишити `PQM_BIDS_MODE=disabled`: UI показує контрольовану недоступність, а не `Failed to fetch`.

### 10.4. Security gate перед push/deploy

1. Не переносити локальні Google OAuth client/token files; створити/використати TEST OAuth client і Render secret лише після реєстрації HTTPS callback.
2. Задати новий сильний TEST password у `PQM_USERS_JSON`; не повторно використовувати старий пароль. Перед deploy ротувати старі TEST credentials.
3. Окремо перевірити публічний repository і його історію. Архів `PQM-production.zip`, журнали та deployment-документи не можна переносити далі без offline inventory на secrets/PII; за наявності секретів потрібні видалення з history та rotation.
4. Не зберігати значення secrets у цьому документі, журналі, screenshots або server logs.

### 10.5. Перевірки виконаного preparation layer

- Python compile: успішно.
- JavaScript/Node syntax: успішно.
- Нові runtime tests: `5/5 OK`.
- Повний suite: `156 tests`, `OK` (`187.409 с`).
- Основна SQLite read-only: `integrity_check=ok`, `foreign_key_check=0`, розмір `1 281 499 136` байт.
- Ізольований TEST_WEB smoke: health `200` без auth; protected API `401` без auth і `200` з auth; Bids disabled `503 JSON`; Power BI disabled `200 JSON`; schedulers/browser не запускаються.
- Локальний Docker build не перевірено, бо Docker engine у середовищі відсутній. Це обов'язковий pre-deploy gate у CI/машині з Docker.

### 10.6. Єдиний порядок наступної deployment-задачі

1. У Render Dashboard зафіксувати поточний repo/branch/deploy ID, Docker settings, env names, disk mount/usage і можливість rollback; secrets не копіювати в звіт.
2. Зробити snapshot persistent disk та read-only inventory старої WEB-БД (path, SHA-256, schema, counts, ручні test writes, integrity/FK).
3. Offline просканувати source bundle/repository history на secrets і PII; ротувати старі credentials.
4. Побудувати Docker image з поточного source, виконати container smoke з тимчасовою TEST DB та перевірити LibreOffice/Poppler/Tesseract/Node EDS.
5. Підготувати окрему TEST SQLite на `/var/data`; не переносити local manual test decisions автоматично.
6. Розгорнути конкретний immutable commit на тому самому service із TEST flags вище, scheduler/Google/Bids/Power BI вимкненими.
7. Провести smoke: auth, health, основні вкладки, safe TEST write/round-trip/audit, JSON errors, DOCX, documents/EDS, повторні integrity/FK/counts.
8. Лише після успішного базового smoke окремо підключати Google OAuth і compact Bids snapshot.
9. При невдачі відкотити і code deployment, і відповідний disk/SQLite snapshot; простого rollback commit недостатньо.

### 10.7. Поточний висновок

**NO-GO для негайного deployment. GO для наступної контрольованої deployment-задачі після виконання security/Render inventory та Docker-build gates.** Робочий код і deployment layer підготовлені; блокери стосуються зовнішньої конфігурації, секретів, образу та стратегії TEST-БД, а не необхідності ще раз перебудовувати предметні модулі PQM.
