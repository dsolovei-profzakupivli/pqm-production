# WEB TEST — НАЗК evidence/FK correction, 16.09.2026

## Межі та причина

Deployment та зміни live WEB DB **не виконані й не дозволяються цим документом**.
План реалізований у candidate та перевіряється на окремій копії WEB backup.
LOCAL DB, Google, НАЗК refresh/reconciliation/materialization та scheduler jobs
не є джерелом або частиною correction.

У WEB snapshot 16.09: check `112`, supplier `39795904`, relation до `32665`
існує, але parent `nazk_registry.source_id=32665` відсутній. Check лишається
`needs_review`, factual result NULL; задача `350664bf535d4f9cb2b5b9760831827a`
залишається `in_progress`. Інші relations check 112: `71515`, `561976`.

WEB read-only audit 13.09 08:53:12 UTC містить повний original registry row
32665 та той самий relation check 112. SHA-256 audit artifact:
`2f369ed9c25f7aa74abb2ad1de4e82b7b61194f9eb802a8114fa684e744fd45c`.
Це доказ історичної наявності запису, **не доказ поточного збігу особи чи factual
результату перевірки**. Причина/точний час зникнення з upstream не встановлені.

Технічний механізм: refresh замінює `nazk_registry` повністю, тоді як FK
історичного relation вказує на цей змінний current-cache; старий refresh не
вмикав FK enforcement. Втрата parent не повинна знищувати provenance.

## Реалізація

1. `nazk_registry` лишається лише поточним snapshot. Запис 32665 туди не повертається.
2. Нове append-only `nazk_registry_evidence_sources` зберігає source ID,
   snapshot payload, час фактичного спостереження та provenance. Timestamp
   snapshot не видається за час створення перевірки або factual result.
3. FK `supplier_nazk_check_matches.nazk_source_id` переводиться на стабільний
   evidence parent. У SQLite це **окрема explicit structural migration**, а
   не звичайний `ADD COLUMN`: контрольована перебудова лише child-table в
   транзакції, зі збереженням усіх rowid, PK, original values та indexes.
   Невідомі incoming FKs, triggers, columns, integrity/FK errors — STOP.
4. Для копії 16.09 створено 143 evidence snapshots: 142 із current WEB registry,
   один із підтвердженого historical WEB artifact. Це не 143 нові перевірки.
   Усі 67 original tables зберігають свої дані. Один append-only migration receipt.
5. Новий explicit relation може посилатися тільки на запис поточного реєстру;
   trigger зберігає його перший спостережений evidence snapshot. Historical-only
   snapshot не дозволяє створити новий current relation.
6. Evidence API/UI показує historical-only запис із позначкою «відсутній у
   поточному реєстрі», датою спостереження і застереженням, що це не результат
   перевірки особи. Current matching/strict coverage logic не підміняється.
7. NAZK refresh: foreign_keys + deferred atomic validation; invalid/empty payload,
   missing IDs, duplicate IDs або FK error → rollback і error. Callback workflow
   не запускається після невдалого refresh. AMCU функції не змінюються.
8. Startup створює лише additive evidence schema. Старий FK автоматично не
   мігрує, evidence із business data не відновлює, checks/tasks не створює.

## Offline acceptance

- Backup SHA: `2e6fa11c94313aab424a689c74c01689afd9af927b426ed058357e29ae91811e`.
- Manifest копії: `b679d917b32a1506c56001e19f74c8527469923d781ff6af58990df48d6202a1`.
- Перевірити fingerprint усіх 67 original tables, rowids/relations, FK=0,
  integrity=ok, 279 checks, 122 total tasks; factual changes=0.
- Repeat same manifest: 0 source inserts, 0 events, 0 relation changes.
- Перевірити rollback транзакції при injected failure, hash mismatch, змінених
  передумовах, сторонніх FK errors; immutable evidence/receipt.
- На виправленій копії: additive release migrations, repeat migration і
  schema-only safe init, без builders/jobs та без змін original data.
- Regression + synthetic HTTP/container smoke. Ніяких реальних upstream запитів
  із тестів. Повний browser acceptance та fresh Docker image build позначати
  окремо: container-runtime smoke не є Docker build.

## Наступний live етап — тільки після погодження

1. Повторити read-only inventory: service ID, live commit, DB path, disk capacity,
   FK list, relation/check/task state, effective scheduler settings (включно з DB
   overrides). Не вважати env=0 достатнім доказом disabled jobs.
2. Узгодити maintenance window; зупинити mutating traffic/jobs контрольовано.
3. Fresh SQLite online backup + storage backup / platform snapshot; verify hashes,
   restore-readability, rollback code та достатнє місце. Backup 16.09 не замінює
   новий backup перед майбутнім apply.
4. Згенерувати новий WEB-specific manifest. Будь-яка зміна передумов попереднього
   manifest → STOP, read-only review та нове погодження; не «підганяти» дані.
5. Apply FK/evidence migration в одній транзакції; after fingerprints, FK/integrity,
   repeat apply. Жодних DELETE checks/tasks, factual updates або fake completed.
6. Additive release migration та повторний запуск; publish тільки погоджений
   candidate. Safe-mode smoke до ввімкнення jobs. Операторські templates не замінювати.
7. Перевірити historical evidence UI та WEB acceptance. Google/Apply/trigger і
   ЮО · Припинення залишаються поза дозволеним етапом.
8. Jobs відновлювати окремо за погодженою конфігурацією. НАЗК reconciliation не
   є частиною FK correction.

Rollback до відновлення business writes: повернення узгодженої DB/storage-копії
та коду `f6a62b1a9d245d0f66c18c8007cb077a12678334`. Після нових business writes
стару DB поверх WEB автоматично не відновлювати: потрібен окремий forward-repair
або план узгодження змін, щоб не втратити нову роботу УО.
