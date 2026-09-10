# RELEASE MANIFEST — PQM LOCAL → WEB, 2026-09-10

Цей FINAL v2 замінює старий ZIP SHA-256 `9918c4eaa1621e04f48efe46dbc9c4409f132150d268f992a67f3f42cbfba0dd`, який більше не є фінальним.

## Походження та checkpoint

Джерело: CURRENT LOCAL `D:\AI\Codex\Projects\PQM-0.1`. Git checkout відсутній; checkpoint — UTC та SHA-256 усіх відібраних вихідних файлів. Це read-only checkpoint, не WAL checkpoint і не копія business DB. LOCAL код/БД не редагувалися. Перед ZIP усі вихідні file hashes повторно звірені; drift=0.

Read-only SQLite: mode=ro + query_only, одна read transaction; integrity_check=ok; foreign_key_check=0. З бізнес-БД експортовано тільки presentation settings і 16 SVG, без авторів та timestamp LOCAL. Схема без записів використовувалася тільки як тестова fixture поза ZIP.

## Результати

- Повторна ізольована release suite нового пакета: 239/239 PASS, errors=0, failures=0. Старі 8 падінь більше не є blockers. За результатом оновлення LOCAL: 7 stale fixtures/expectations і 1 виправлена реальна регресія. Повідомлений користувачем focused Block 4/DOCX результат — 79/79 OK; окремий focused набір у цій сесії не перезапускався.
- Реалізований LOCAL обсяг Block 4/DOCX підтверджено release suite: catalog/schema, derived fields/declension, metadata bindings, conditional renderer, наявний nazk_supplier_request runtime, template replacement/download. PROPOSED_UNBOUND decision.* та legacy renderer міграції не оголошуються готовими.
- Актуальна фінальна добірка використовувала окремі synthetic DB/копії шаблонів. Sync/Bids/schedulers не запускалися; зовнішні socket.create_connection заблоковані в runner.
- Cross-assignment permission dispatch A→B, B→A та protocol scope; Viewer/inactive denial: PASS. Це серверні тести, не browser acceptance WEB.
- deploy_release.py застосований двічі: business fixture незмінна, navigation seed ідемпотентний, SQLite/FK OK.
- Python AST та JavaScript/EDS adapter syntax: PASS.
- Browser acceptance і актуальний production WEB diff не виконані. Supplier latency та давня console initialization error не підтверджені в актуальній браузерній сесії; див. README.

## Відмінності від CURRENT LOCAL

1. server.py: assert_protocol_scope прибирає assignment boundary, залишає роль/активність та existence guard.
2. server.py: PQM_RELEASE_SCHEMA_ONLY (default true у WEB) вимикає початковий seed LOCAL УО, authority_code backfill та startup task-builder. Additive schema збережена.
3. metadata JSON: прибрано editor audit / created_by / updated_by, решта конфігурації збережена.
4. Додано deploy_release.py, config/navigation.release.json та release documentation.

Історичний WEB reference 09196f1 мав assignment guard для application mutations. Поточний deployed WEB невідомий. WEB permission acceptance залишається CRITICAL deployment gate.

## Склад та виключення

Усі runtime Python/JS/CSS/HTML модулі з кореня LOCAL, assets, поточні metadata/config, 5 вихідних DOCX templates, migrations, Dockerfile, requirements, EDS adapter package/lockfile/code, українська OCR language data. Інструкція охоплює повний LOCAL дизайн і модулі, а не лише останні зміни.

НЕ включені data/БД/WAL/SHM, secrets/.env, backups, caches, logs, generated documents, test code/artifacts/screenshots, тимчасові файли, credentials, user preferences/profiles, персональні runtime records, template versions, node_modules та локальні start/службові скрипти. Config CSV — погоджені правила відмінювання, не експорт business entities. Metadata reference URL — посилання на джерело шаблону, не токен доступу.

## Gates

1. WEB A/B/Viewer/inactive permission acceptance.
2. НАЗК DOCX WEB browser acceptance після deployment; LOCAL regression blocker закрито (239/239 OK).
3. WEB backup/міграція/health/FK/browser acceptance; performance baseline та стара console error перевіряються окремо.

LOCAL health: GET /api/health HTTP 200; ok=True

Checkpoint UTC: 2026-09-10T06:37:39.847126+00:00

Невдалі перевірки фінального запуску: немає.



## Source checkpoint SHA-256

| File | SHA-256 |
|---|---|
| .dockerignore | ff6be68920a04a622ce60a5f29402a34738a0c3e7fe18682c462a608169ec547 |
| Dockerfile | 3cf2f48b72692a65e39187493a02399d9d6ae76df9b2279160ce5ea2eae917ab |
| app.js | f0bcd58edd513c538b888a3b000e908da249a8481db025f86af891b682c71e2a |
| assets/pqm-favicon.svg | 32983ca746e49f50f096ffc764c79476099ff1dcf4bd4a3b9db2c742c6bc74e9 |
| assets/professional-purchasing-logo.webp | eea62ab562b4990e9360c6f149e2a1e9e3759c94ce1d8872696f6cd78efa41d6 |
| assets/profzakupivli-favicon.webp | 5796171b2c6c4eb7b3589f2967043dbc5a972d2b1c0f3282e4b16590bd5ea73c |
| assets/zakupivli-pro-mark.svg | 074d470d98f4549dedb869d54c2bd0736f30ed61d463ba481dea05b72e2690c6 |
| auth_access.py | 0d6811d668dccfac5d2da02c3d750193c3b2faa26a28d9647675f63f0144260c |
| auth_ui.js | 490f399a7f589030fb662cb2b16dec1d173961becf892c36705fb4e879264e72 |
| chat_ui.js | ed38f2bdc2b792d0ccf448d8388d626263a3dbbd2dc3d0dc08005e5bff8c203b |
| config/declension_overrides.csv | 60175bc447fbeac39ab8f05e550f35546c92b908620477a5698615eb032a4773 |
| declension.py | 71f3267b9188160092da746538e462787d80d7fe3d35bbf2e60996e3db148489 |
| declension_overrides.py | 4eaa74ba7cbacebc648460d075084952940130726c3157c3c0626ccecbd392cb |
| derived_fields.py | 14ca48749e0d24c912a0a336910e9bad22ba77d56a5ef560cfa5a8bdec2ce8ab |
| document_bindings.py | cf2faca92b38314c1b322277a28674da54f00e01afabb68d09fecfb8523b9a91 |
| document_semantics.py | d7b26e68be0af3d164c19e533e34e244f4d546c4a8163836231a0ba1d3037886 |
| docx_conditionals.py | 4258e0b439643ea39f81ff3c8d204f740f6c06336f86899f416cb901d9954885 |
| filters.css | 9bd7805fbe35fb1ecc69f1f9cc9e38c447d7ee544772af8cb0ad001d4cfb019a |
| formed_protocol_ui.js | 4fabdec080eae9eb8c86ec358d9bdd62b05e308e878de650ebfac8ddbe34606b |
| formed_protocols.py | 6bed06fd4bdf4d580874013bd5a75890c752246b27d485c717054e86d9a21123 |
| history_columns.js | 4e5e4bf9c38468c7a2596785ce4b50b451aba86af51e346f01e278a922ab61ae |
| history_ui.js | 3aa1988ce876d39784e9731ae811c8ac57606c5363c2071e63eef70bac29dd6a |
| index.html | bc3b557a669181a3f53792216feacc91045b199d307bbb0f31a385adb3377edf |
| metadata/data_schema.v1.json | 0f796d0d8c6ea1342b75bfc981f1fb487c8a6476a6babf5cc706823a622ffb33 |
| metadata/document_sources.v1.json | 4cc7c524391bf6666702ab42a9b087b2c9b6f004a99b0a17d82d4e71577f5d2e |
| metadata/runtime_templates.v1.json | d09546098421a7d32ca646c9982d2a4b0feeb714392f85d296648f346adab4c3 |
| metadata/template_fields.v1.json | b4ea4419fe17e95f613fd7511482a55b14ddf42fb7d6d3dc2feb7539f44dd53e |
| metadata/template_legacy_tokens.v1.json | 691207e3a21bc0006d367e0eb5807d73cc2e9f61858a43edfa9e05ed1bb9c138 |
| migrate_nazk_legacy.py | 6dcdd80b6a51da306d7842c4c1f2c6ecf2841deae01a4aee6b18f2627a8735fd |
| migrations/20260908_block3_operational_tasks.sql | 1048efd227ac27042d6e9eef3205367ed32bf7fdf2c5bcef24991f0eda946dce |
| migrations/20260909_navigation_icon_library.sql | fb37b0a2165eaa984b96ce338a7a7b51ae0a37d5265b2c22f981e21f2f00f1dc |
| migrations/20260909_navigation_settings.sql | debe23d3451f78d92665ce70e12347a52d18fe6e12c7441e6b6a0b432f2b6ea0 |
| migrations/20260909_operational_task_cards.sql | 00ec303b7043455a42a2112b55a15a45fe76a43b2a1a03e979afce5d3df9da5d |
| modules.css | ca72d0c911a7c1b18d6132f736ee3107f78c906916a47666cb06e1110da82811 |
| nav_icons.js | 64e7bdb34b538a2d1673ad009ad83284bb9b1b6def2be1bf1927581f912b1ead |
| navigation.js | 1d2840d61d518dd0796ac2ba047fe0a346cc6e9330b2a90a23969a13c9640270 |
| navigation_admin.js | a2fbf011e311b0ed8a778c9cff02a5440e9ebe605d254ac4ca9acf93c0fb74ff |
| navigation_settings.py | dd4a3b78ff2cf3b22ae6ff250fb3f551822b274524d4278c82aeea58fadf3623 |
| nazk_workflow.py | 07e3b5225afced7ff6beb8770a82537e61cb6183873669fceeec7b2423cafbf7 |
| operational_tasks.py | 7fea3bb2804ebd7eb1b5f7f536822915feeb7c8c0a77f6aba27c6456fbd9fe94 |
| protocol_docx.py | c7246d3c2736864d659e830f9d3128ba769454cbf80f1146fe320fd40b8ebd5f |
| protocol_template.py | 3581d4873f0c64aedd69ddf12c07d51d9720767668492b69ee69789c6d8110bb |
| reference_directories.py | 74b69f35134b4949b9a709c372bb646db889ea300c31d047952c373183a79a7a |
| requirements.txt | 161a70f7ed52235bb3bcf362d2ab52a6e7be38ac1d708de8d11f3db149418336 |
| schema_catalog.py | d060cc4bcf022bf1e00ba9ef0282d569f827222c29cc047e79d385e4eb8e82fc |
| schema_ui.css | 50b9c920f026286b452d2238bb6f12cea75b9e32e17fb7a7854c34e60cb080be |
| schema_ui.js | 921677d29128f9094d13c1af9d1bd4b4e86400ef76974e7a8e40bb2549f9b922 |
| server.py | 5c9ada93445203bd4a3cb7b939cf5d3578a7d9e2d8e87be3ef5e7c2b89bdea6d |
| styles.css | b479b100c3b5d0e2fcaa9fa68ce250d738132b38354d25c4977203b86ab527da |
| supplier_activity.py | 064e7d6fc70cbbddf8f9e78f60fd6e509191997197fbb7949122a279a984589b |
| supplier_contacts.py | 1650e6e6b7c33a75e13baa5bc7dad3b4905de33cba50409b6933d9bc74d2ed97 |
| table_widths.py | bdd147618e8dddd5c9f82fd02822f35b4d3b449e7463c587e12450e501eac718 |
| table_widths_ui.js | 8af718773adcc4c243040c64ed7197fa866a042334b4170e79be85a8be74aa0a |
| task_documents.py | 6f220507d3850da506ef1f02f510fd9884decb21a0bcfffca44c3a85c0115818 |
| template_catalog.py | 90b09fe90b8754bd822094298387061164a7b7ccb7e7d409e1795c1c90edf074 |
| template_catalog_ui.js | a6d9af6bd1f36fc6a3d663e147e92c960d230384a7f58163c7edd99a5106b674 |
| template_conditions.py | d607c4621fc8b9c157de6bf7acf8f7205962866b933a1036d257d92193804476 |
| template_runtime.py | 01a886348b4829b840aaed05c3cf15fce0358387f7edfdbb14934e7f5212ae22 |
| templates/application_protocol.docx | c641e9bd4492f97f730f1023bca4ac211b6cc37e8fa3008e499c12ac62948769 |
| templates/nazk_supplier_request.docx | efebfec7123f6aeb8c149ff9627a9fdecc6537321259837e9c4ad530cdba26a5 |
| templates/violation_protocols/decline_p49_1_2.docx | 202143274d78eefcaea85a24f8afd952fda542b992256e8b9f572185fcaab5e7 |
| templates/violation_protocols/decline_p49_3.docx | 6e6b44defa90e174d3231ab53b70f4139fe39819636e35fb8b092463d5a67d1d |
| templates/violation_protocols/warning.docx | a7d3ca6977d3247dc7962fae23156bf3ccded214c51f94fee8d0c45f47d1915a |
| tools/prozorro_eds_adapter/package.json | c5288a4b485b9c0ab64eb526f0a53a132c17c0e315ad96eecf7147e90cb7392a |
| tools/prozorro_eds_adapter/pnpm-lock.yaml | d70dbb146d0a93365334088a06b41210cd202dc6cc096a1ec9e5b93518717e5c |
| tools/prozorro_eds_adapter/verify-signature.mjs | 2b5d3118ce2590d3a07cb277002d8017fdccee23198348224dc8221ce32531c7 |
| tools/tessdata/ukr.traineddata | d59e53e2bded32f4445f124b4b00240fcac7e8044c003ab822ccb94f0b3db59b |
| uo_work_queue.py | fd779e25c02e28c74558b997c3c9276b89bf67630bb500cd97a8ce7c81d7e3fe |
| violation_protocol_docx.py | 3e34d6318c9816d9e29c877940ba141e8452f3fe868944debae25157c484a5e7 |
| working_modal_drag.js | b71b2c575028a9fdd2d50be561e06867c8f0f199c1a890ecf4614024d93550db |
