# Сформовані протоколи УО — LOCAL

## Робочий сценарій

№, дата та УО протоколу залишаються чинними полями заявки. Вони не доводять факту формування документа.
Після успішної генерації DOCX створюються formed_protocols і точний склад formed_protocol_members. Номер у Реєстрі відкриває спільну модалку протоколу.
Підготовка реквізитів виконується через чинні поля/масове заповнення. Якщо виділено заявки, перевірка і генерація використовують саме їх IDs; без виділення — чинну відфільтровану вибірку протоколу.

Скасування вимагає підтвердження і причини, звільняє весь склад, зберігає №/дату/УО/рішення/зауваження. Змінити реквізити сформованих заявок перед новою генерацією можна лише після скасування. Повторна генерація — новий UUID і нова версія, попередній запис залишається cancelled.
Формування і скасування дозволені лише коли відповідні заявки мають поточний qualification status pending («Очікує рішення»); для змішаного складу скасування повністю блокується.

## Legacy

70 наявних generated-маркерів не мігрувалися у нові записи і не групувалися за номером/датою/УО.
У рядку видно «Legacy: сформований раніше». Достовірного складу немає, тому модалка складу не відкривається.
Для pending-заявки доступне індивідуальне скасування позначки з підтвердженням/причиною/audit. Жодна інша заявка з тим самим номером не змінюється.
Для інших статусів скасування legacy-позначки недоступне і в UI, і через API.

## Зберігання і захист

- formed_protocols: UUID, snapshot реквізитів, version, active/cancelled/superseded, created/cancelled actor/time/reason, counts, шлях і SHA-256 DOCX.
- formed_protocol_members: submission_id, порядок, immutable snapshot_json і active-lock. Історичні snapshots не змінюються при скасуванні.
- Partial unique index не допускає двох активних входжень однієї заявки; окремий індекс — двох активних записів однієї серії (№ + дата + УО).
- BEGIN IMMEDIATE охоплює остаточну перевірку status/scope/stale fields, генерацію і запис membership. При помилці генерації нових records/маркерів немає.
- viewer не виконує mutation; officer — лише свій склад; admin — адміністративний доступ. Автор і роль беруться із server auth, не з body запиту.
- Зміни subject fields/схеми наявних таблиць не робилися. Додано дві таблиці та два індекси.

DOCX фізично зберігається у PQM_PROTOCOLS_DIR (типово data/protocols)/_formed/<protocol_id>/Протокол № <номер> від dd.mm.yyyy.docx.
Кожна версія має власну директорію. Старі файли не видаляються. Робоче завантаження доступне лише active-запису; обхід через старий generic file endpoint для _formed заборонено.
Якщо файл успішно записано, але commit БД не відбувся, він може лишитися невидимим orphan у своїй UUID-директорії; активного запису/lock при цьому немає. Автоматичного destructive cleanup немає.

## API

- POST /api/protocol/readiness — чинна перевірка + pending/legacy/active guards.
- POST /api/protocol/generate — успішний DOCX → новий protocol_id.
- GET /api/protocol/formed/<id> — реквізити, snapshot складу, counts і історія нових формувань.
- GET /api/protocol/formed/<id>/download — тільки актуальний DOCX.
- POST /api/protocol/formed/<id>/cancel — confirmed=true, reason.
- POST /api/protocol/legacy/<submission_id>/cancel — confirmed=true, reason.

## Backup і acceptance

Backup: backups/formed_protocol_20260905_103015.
SQLite SHA-256: 2780bf110c2d13b092a9c8b98d47d5620abae272d2ee32f94532697ecba2ac0e.
Backup journal SHA-256: 2d1250ed45d9d05cd7d54e4fab65a6742b172d9d3288f462b0947d1cf1009d64.
Before/after counts усіх старих таблиць незмінні; повний digest application_fields однаковий; integrity ok, FK 0, legacy count 70.
Деталі: artifacts/formed_protocol_migration.json.

Browser acceptance (той самий LOCAL код, окрема fixture DB на 8099):
№100 Федченко 5 → cancel; №101 Єрьоміна 3 → cancel; чинне bulk редагування трьох заявок → №100 Федченко 8 → reload.
Новий №100 version=2, snapshot=8, table rows=8/8/0. Попередні snapshots=5 і 3, обидва cancelled; усі три DOCX збережені, SHA відповідають БД.
Повторний POST заблоковано 409. Legacy без підтвердження/не-pending — 409, viewer — 403; успішне скасування торкнулося лише pending legacy-заявки.
Evidence: artifacts/formed_protocol_acceptance_v2/browser.json, merged_modal.png, legacy_browser.json, docx_verification.json.

Основний LOCAL 8080: read-only smoke агента на реальній заявці 2b276aee433d4f83b12183c0955abd56 (№888, Допущено): legacy видно, cancellation відсутній; live.json, live_legacy.png. Агент не скасовував і не переформовував робочі заявки; mutation acceptance проводився на окремій fixture DB.
LOCAL перезапущено PID 11556 через acceptance launcher без init_db та schedulers, health ok. Вимкнення schedulers діє для цього процесу, не змінює файли конфігурації. Sync/Bids update не запускався; WEB TEST/GitHub/Render не змінювалися.

## Regression

Focused: 19 tests OK. Остаточний full suite: 314 tests OK (279.748 s).
Python syntax server.py/formed_protocols.py/auth_access.py і JS syntax app.js/formed_protocol_ui.js — OK.
Full suite мав ResourceWarning щодо SSL sockets, без failures/errors. Генератор і його шаблон у цьому пакеті не змінювалися.

## Паралельна робота в основному LOCAL

Безпосередня перевірка міграції підтвердила незмінність старих counts і application_fields. Проте від backup до кінця всього завдання в основному LOCAL окремо виконувалися робочі PATCH/POST (10:42–10:58), що підтверджується audit та logs/server.log. Вони не належать до fixture acceptance агента і не відкочувалися.
Фінальні відмінності від backup: audit_log 2546 → 2632, supplier_managers 13392 → 13394, application_protocol_remark_selections 1 → 2; application_fields містить робочі редагування 11 заявок.
Також у головній БД зафіксовано новий №100, 5 заявок (4/1), protocol_id ec0b1abdae8f44a6897ca8969d8e2b57: створено 10:56, скасовано 10:58. Обидва API повернули 200; snapshot і файл залишилися, active-lock знято. Legacy-маркерів усе ще 70.
Фінальна integrity_check: ok; foreign_key_check: 0. Evidence: artifacts/formed_protocol_final_integrity.json та artifacts/formed_protocol_concurrent_activity.json.
