# PQM LOCAL → WEB — для Діми, 10.09.2026, FINAL v2

Цей реліз замінює попередній ZIP із SHA-256 `9918c4eaa1621e04f48efe46dbc9c4409f132150d268f992a67f3f42cbfba0dd`. Старий ZIP більше не є фінальним.

Еталон: CURRENT LOCAL `D:\AI\Codex\Projects\PQM-0.1`, зафіксований файловим SHA-256 checkpoint. Це повний комплект актуального застосунку, не інкрементальний патч останніх файлів. **Увесь погоджений дизайн LOCAL має бути перенесений у WEB.** Не збирати реліз лише з останніх JS/CSS чи старого WEB-пакета.

## Статус та release gates

Пакет підготовлено для розгортання на staging і приймання. Це НЕ підтвердження готовності production: актуальний deployed WEB checkout та його конфігурація недоступні. Порівняно лише історичний WEB-знімок `.tmp_web_reference_09196f1`.

Критичний permission blocker виправлено в коді пакета, але закривається тільки після перевірки на WEB. Попередні 8 падінь Block 4/DOCX розібрано: за результатом оновлення LOCAL — 7 stale fixtures/expectations та 1 виправлена реальна регресія. Повторна ізольована release suite нового пакета: **239/239 OK**. Попередній test blocker знято. Повідомлений власником LOCAL focused результат: **79/79 OK**; окремо цей набір у поточній сесії не перезапускався, релевантні тести включені в release suite.

## Обов'язковий функціональний і візуальний обсяг

- Усі вкладки/модулі LOCAL, data-driven navigation, custom SVG library та її settings: `navigation.js`, `nav_icons.js`, `navigation_admin.js`, `navigation_settings.py`, seed з 16 custom SVG. Зберегти порядок, видимість, display modes, icon keys та кольори.
- Актуальний filter-bar standard; supplier detail section-card standard; modal/floating detail windows; draggable working modals, особливо «Налаштування колонок» та «Зауваження до протоколу» (`working_modal_drag.js`). Перевірити overflow, scroll, footer, drag, reload і збереження налаштувань.
- «Робота УО», «Операційні задачі», НАЗК workflow, `warning_block`, canonical НАЗК relations, responsible-UO assignment. RNOKPP reuse має використовувати поточного керівника, без підміни попередньою особою.
- Manual protocol decision attachment, `used_for_blocking`/highlighting; відображення прив'язаних доказів і рішень. Не переносити LOCAL рішення чи документи: тільки код і структуру.
- База постачальників: ФОП/ЮО + статус ЄДР + reset + active state фільтрів. Unified effective qualification counts через `supplier_activity.py`: однакові результати у списку, профілі, робочій черзі та задачах; статус/строк відбору враховується.

## Блок 4 — що фактично включено

Template Field Catalog та інтеграція зі «Схемою даних PQM»: `template_catalog*`, `schema_catalog.py`, `schema_ui*`, metadata. Є configurable derived fields/declension, `derived_fields.py`, `declension*.py`, CSV overrides, metadata-driven runtime bindings (`document_bindings.py`, `document_sources.v1.json`), conditional renderer (`docx_conditionals.py`, `template_conditions.py`). Відповідні перевірки у повторній release suite пройшли.

`nazk_supplier_request` DOCX runtime, реальний DOCX-шаблон, template replacement/download та metadata registry включено і підтверджено ізольованими regression tests нового CURRENT LOCAL. Перевірки ФОП/ЮО, поточного керівника, відмінювання, умовних гілок, generation/download/version history та заміни шаблону проходять. Це завершений і перевірений LOCAL обсяг Блоку 4; WEB browser acceptance після розгортання залишається обов’язковим. Не прирівнювати його до реалізації майбутніх unbound полів чи міграції всіх legacy шаблонів.

Поля `decision.number`, `decision.date`, `decision.url` залишаються `PROPOSED_UNBOUND`: не подавати їх як готові runtime bindings. Legacy чотири шаблони не оголошуються переведеними на canonical renderer.

## CRITICAL: права УО

Усі АКТИВНІ УО з відповідними role permissions мають read/write/review access до ВСІХ заявок і рішень по заявках, незалежно від responsible/assigned UO відбору. Призначення УО — організаційний атрибут, не permission guard. «Мої» фільтри можуть звужувати представлення, але їх можна скинути; вони не обмежують API.

Історичний WEB `officer_mutation_scope_allowed` порівнював protocol_officer/framework_officer з поточною УО. CURRENT LOCAL вже прибрав цей guard для заявок. Проте LOCAL `assert_protocol_scope` досі блокував чужі заявки під час формування/скасування протоколів. У пакеті прибрано тільки порівняння assignment: збережено role=officer, active=1 та перевірку існування заявки. Центральні granular permissions, Viewer denial та контроль неактивних УО збережено. Правила призначення для звернень замовників не змінено.

Приймання WEB обов'язкове для двох різних облікових записів:

1. Active UO A відкриває заявку відбору responsible UO=B, розглядає документи, змінює поля, зберігає рішення, формує протокол; перевірити повторне відкриття і дозволене скасування.
2. Active UO B аналогічно для відбору A.
3. «Мої»/assignment filter впливає лише на список; після reset доступні всі заявки. Перевірити прямі GET/PATCH/POST API, не лише кнопки.
4. Viewer не отримує write, навіть за помилкового override; inactive UO/account не отримує write. УО без відповідного granular permission також не отримує його автоматично.
5. Перевірити зовнішні WEB proxy/middleware та власні query filters: у них не повинно залишитися assignment-based guards для заявок/рішень. До виконання всіх пунктів permission blocker НЕ закритий.

## Розгортання без заміни WEB business data

1. У maintenance window зупинити WEB writers, sync, Bids і schedulers. Зробити консистентний backup WEB SQLite через SQLite backup API/штатний backup сервісу, а також WEB code/assets/config, persistent templates, uploaded/generated documents. Не копіювати лише основний sqlite-файл під час активного WAL. Перевірити можливість відновлення.
2. Розпакувати в новий code directory/image. Не розпаковувати поверх persistent data directory. Встановити Python dependencies з requirements.txt; Dockerfile також встановлює OCR/PDF/LibreOffice та production dependencies EDS adapter за lockfile. Зберегти чинні WEB secrets у захищеному середовищі.
3. Налаштувати `PQM_ENV=web`, `PQM_DATA_DIR` на існуючий persistent WEB каталог, `PQM_DB_PATH` на існуючу WEB БД, `PQM_RELEASE_SCHEMA_ONLY=1`. На етапі deploy/acceptance: `PQM_ENABLE_SCHEDULER=0`, `PQM_ENABLE_NAZK_SCHEDULER=0`, `PQM_BIDS_MODE=disabled`, `PQM_ENABLE_BIDS_UPDATE=0`, `PQM_ENABLE_BROWSER=0`, `PQM_ENABLE_POWERBI=0`, `PQM_ENABLE_GOOGLE=0`. Зберегти чинну WEB auth-конфігурацію; не імпортувати LOCAL користувачів.
4. З code directory виконати (підставити справжній шлях):

   ```sh
   python deploy_release.py --db /var/data/pqm.sqlite3 --apply-navigation
   ```

   Скрипт запускає guarded additive schema migrations і reference-table initialization, потім лише presentation seed. Нові таблиці/колонки створюються ідемпотентно. Не запускати SQL-файли навмання замість актуальних Python migrate-функцій: SQL у migrations є частиною історії, а повна актуальна структура забезпечується init_db та migrate-функціями модулів. Не запускати `migrate_nazk_legacy.py`, sync/reconciliation чи data rebuild у межах цього релізу без окремого WEB data plan.

   Release guard вимикає імпорт початкових LOCAL УО, authority_code backfill та автоматичний startup task-builder у WEB. Системні defaults зауважень/системних профілів додаються лише коли відповідний каталог порожній. Жодні LOCAL business rows не імпортуються. Task-builder для наявних WEB фактів — окрема контрольована операція після backup/acceptance; інакше історичні WEB дані можуть ще не мати нових задач.
5. Перенести `metadata/*.json` та `config/declension_overrides.csv` у code directory як актуальну конфігурацію LOCAL. Перед цим зберегти копію WEB metadata. Це не копіювання рядків business DB; не переносити audit/editor history з LOCAL. Metadata файли мають бути доступні для запису, якщо використовується адміністрування каталогу/derived fields.
6. **Окремо встановити всі п'ять поточних DOCX-шаблонів** з `templates/` у `$PQM_DATA_DIR/templates/` зі збереженням підкаталогу `violation_protocols/`. Backup старих WEB шаблонів обов'язковий. Самого оновлення `/app/templates` недостатньо: runtime читає persistent templates, а старі файли автоматично не замінюються. Не чіпати WEB generated_documents/protocols та інші завантажені документи. DOCX у ZIP — вихідні шаблони, не згенеровані документи.
7. Seed навігації змінює лише `navigation_icons` для включених ключів і singleton `navigation_settings`; чужі icon keys не видаляє. Він переносить authoritative LOCAL presentation settings, не users/preferences/roles/assignment. Backup цих двох WEB таблиць дозволяє відкотити лише оформлення. `--apply-navigation` потрібен для повного перенесення LOCAL дизайну.
8. Restart WEB. GET `/api/health` має бути успішним; перевірити конфігурацію feature flags, відсутність фонових sync/Bids, `PRAGMA integrity_check` = `ok`, `PRAGMA foreign_key_check` = порожньо. Порівняти до/після кількості й значення WEB заявок, рішень, постачальників, користувачів та призначень.
9. Browser acceptance: повне reload без старого cache; усі вкладки/іконки/модалки/фільтри вище; permission matrix A/B/Viewer/inactive; НАЗК workflow, warning_block, manual attachment, поточний керівник/RNOKPP, effective counts; Блок 4 та DOCX для ФОП/ЮО. Не закривати release gates лише за health=OK.

**Ніколи не копіювати LOCAL DB поверх WEB.** Не очищати WEB business tables. Для rollback повернути code/config/templates; additive columns зазвичай можна залишити. Відновлення повної WEB DB з backup потребує зупинки writers і врахування нових WEB записів після deployment.

## Відомі питання та межі перевірки

- LOCAL supplier-base baseline ~9–12 с заданий як відома проблема продуктивності. У цьому audit запит списку не запускався, бо він може перебудовувати runtime summary. Поточний browser latency не підтверджено. Виміряти cold/warm load та server response time на WEB, виконати окремий performance audit/monitoring; не видавати baseline за нову регресію.
- Раніше була console initialization error. Поточну браузерну консоль у цій сесії не перевірено; статус «потребує відтворення», не «виправлено» і не «нова регресія». Перед прийманням зафіксувати точний message/stack та порівняти з попереднім випадком.
- Повторна ізольована release suite: **239/239 OK**, failures=0, errors=0. Попередні 8 падінь більше не є known issue цього пакета. Permission tests та дворазове застосування deploy seed пройшли. Тестові дані/результати/скриншоти в ZIP не включені.
