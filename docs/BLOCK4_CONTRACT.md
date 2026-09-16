# Блок 4 — document API v1

Pipeline: Схема PQM → Template Field Catalog → document_context → provider renderer.
Catalog keys не є SQLite columns. Bindings використовує context adapter, ніколи шаблон.
Canonical namespaces: supplier, manager, submission, qualification, framework, uo, nazk, amcu, warning, blocking, decision, task, system.

## Джерело та versioning

metadata/template_fields.v1.json — єдиний canonical catalog. version — версія API; revision — optimistic concurrency.
Адміністративні зміни — POST /api/admin/template-fields/update (key, changes, revision). Запис атомарний; у тому самому JSON збережено append-only audit старих/нових metadata з автором і часом. Stable key через цей endpoint не перейменовується. Нові keys додаються контрольованим code review/migration, з audit entry; це не довільні aliases.
У Stage 1 UI каталогу був read-only browser. Configurable derived fields нижче розширюють його контрольованим Admin editor.
Ручні зміни файла поза контрольованою міграцією не є підтримуваним workflow.
Catalog перечитується на кожний metadata request. Usage index обчислюється без таблиці/cache і без ручної синхронізації. Active, non-deprecated valid bindings та dependencies формують template usage у Схемі. Broken bindings показуються явно, не замінюються здогадками.

## Контекст і типи

Документ отримує тільки whitelist available_for свого document_type. required_for діє лише для відповідного типу. Null не перетворюється на вигаданий факт. system.today/generated_at визначаються один раз у Europe/Kyiv.
manager — поточна identity; nazk.record — конкретний linked canonical nazk_registry record, не legacy review. Для декількох записів майбутній context adapter має явно вибрати business-event record, не випадковий перший рядок.
amcu.decisions[] та warning.references[] лишаються array<object> з item_schema. Ключі children позначають поля елемента; це не окремі довільні placeholders поза repeat scope. Для `amcu.decisions[]` активований provider-neutral paragraph-group repeat: standalone `{{#repeat amcu.decisions[]}}` і `{{/repeat}}`; усередині доступні тільки item-local `{{number}}`, `{{date}}`, `{{authority}}`, `{{extract_url}}`. Provider клонує оформлені template paragraphs для кожного linked decision, без concatenated string. Empty array видаляє весь repeat range без порожніх абзаців. Nested repeat/if, cross-container ranges і scope fields поза repeat відхиляються validation gate.
Для `amcu_exclusion_protocol` decision.number/date прив'язані відповідно до `operational_tasks.protocol_number/protocol_date`; дата форматується `dd.MM.yyyy`. Інші document types не отримують неузгоджений спільний resolver. Посада УО не вигадується. Output name pattern для нового provider config поки null; чинне runtime іменування не змінюється.

## Conditional blocks — Stage 2C

Canonical semantic discriminator: `supplier.entity_type`, enum `legal_entity / individual_entrepreneur`, EXISTS+BOUND (derived). Погоджене document-only правило: normalized supplier code із 10 цифр → individual_entrepreneur, інакше legal_entity. Обидва поля supplier.code_label/entity_type — проєкції одного результату document_semantics.supplier_code_semantics; одна нормалізація й одна умова, без аналізу назви. Future context adapter обчислює цей результат один раз і передає обидва поля renderer. Це не зміна factual registry identity або правил відмінювання.

Для nazk_supplier_request renderer обирає за supplier.entity_type: перший source paragraph — individual_entrepreneur, другий — legal_entity. Source template зберігає обидва; output містить рівно один. Невідомий/null/непідтримуваний готовий enum → validation error до generation. Shared helper для рядка коду завжди повертає один із двох типів за погодженим правилом, включно з legacy else; валідація вхідного коду залишається окремою. Виключена гілка не залишає порожнього абзацу.

Погоджений syntax (кожен marker — окремий абзац):

```text
{{#if supplier.entity_type == "individual_entrepreneur"}}
Абзац для ФОП
{{/if}}
{{#if supplier.entity_type == "legal_entity"}}
Абзац для юридичної особи
{{/if}}
```

Provider-neutral `template_conditions.py`: strict parser → Condition(key,literal) → equality, без eval/executable expressions. Підтримано тільки #if, ==, canonical string/enum key, double-quoted literal і /if. Else, and/or, вкладені if, escapes/expressions та inline markers не підтримуються і дають validation error. Для enum literal і фактичне значення мають входити до enum_values. Unknown/missing/null condition value — error, без fallback. Умови перевіряються також у false branches.

DOCX adapter `docx_conditionals.render(source, output, context, fields, document_type)` приймає flat canonical context (`supplier.name` → value) та поля, перевірені Catalog. Він не читає business DB і не обчислює тип постачальника. Спочатку створює/перевіряє весь план, потім видаляє XML nodes, потім reuse `protocol_template.replace_tokens` для звичайних placeholders зі збереженням runs/форматування. Output записується атомарно лише після успішної validation; source/output не можуть збігатися.

Opening/closing paragraphs повинні бути siblings в body, header/footer або одній table cell. Блок між ними може містити кілька абзаців і цілу таблицю. False → видаляється весь діапазон разом із markers; true → видаляються лише marker paragraphs. Перехід між cells/containers, вкладені if та section breaks в умовному блоці відхиляються. Table-row conditions через markers у різних cells не підтримуються. Порожні абзаци всередині false range також видаляються; зовнішні авторські відступи не чистяться глобально. Word-required final paragraph у порожній cell зберігається як структурна вимога, без додавання порожніх table rows.

Catalog/binding та синтаксис placeholders перевіряються в усіх conditional branches,
але runtime values обчислюються лише для retained branch. Поле, присутнє тільки у
false branch (наприклад, `supplier.name_genitive` у варіанті ЮО), не може блокувати
генерацію іншого варіанта через відсутнє або нерелевантне factual value.

Validation: catalog existence, availability/active/nondeprecated, VALID binding, string/enum type, enum literal/value, balanced markers і strict syntax. Scalar placeholders також перевіряються; required_for не дозволяє порожні значення (зокрема supplier.email). Catalog scanner повертає conditional_errors, які блокують can_activate_canonical. Цей gate описує валідність шаблону, не наявність runtime data — її перевіряє render.

Google Docs provider надалі reuse ту саму Condition/equality семантику, але зараз не реалізований. Stage 2C — opt-in renderer library, не підключення НАЗК-кнопки або заміна чинних чотирьох runtime renderers. Для першої реальної генерації ще потрібні робоча копія source template з canonical placeholders/markers, context assembly та runtime integration. Source Google Doc і чинні DOCX не змінені.

## Provider і сумісність

supplier.email — shared contacts.current.email із останньої заявки через supplier_contacts, без history fallback. Порожній email → null. Для nazk_supplier_request required_for вимагає validation error до generation; nullable означає можливу відсутність source data, не дозвіл пропустити required поле. Context adapter reuse вже прочитаних contacts, без повторного query для цього поля.

Реалізований runtime format=docx, generation_provider=docx_local. Provider/destination config nullable. Майбутній google_docs provider може мати template ID, destination/folder, output pattern, copy policy і persistent output URL, без зміни document_context/keys. Google integration не реалізована.
Compatibility mapping runtime key → document_type: warning → warning_notice; decline_p49_1_2 → decline_p49_1_2; decline_p49_3 → decline_p49_3; application_protocol → application_review_protocol.
Чинні renderers та DOCX не змінюються. Детальний legacy audit — BLOCK4_TEMPLATE_AUDIT.md. Scanner читає всі word XML paragraph runs, включно з split placeholders. Legacy allowlist зафіксований аудитом, не перебудовується з upload. Валідація advisory для existing runtime; can_activate_canonical=false при unknown, unavailable, broken/unbound або legacy tokens. Будь-який майбутній canonical activation endpoint зобов’язаний перевірити цей gate. Новий generation/activation endpoint у Stage 1 не створено.

## Доступ та UI

Усі /api/admin/template-fields*, /api/admin/templates* — лише Адміністратор за existing backend guards. Non-admin не рендерить catalog controls. Runtime generation permissions — окремі, без надання права конфігурації.
Основний identifier — український label; key secondary. Пошук case-insensitive partial, одночасно label, description, group, key. Джерела schema physical fields ніколи не є основним каталогом користувача.
Немає Google/PDF/HTML generation, automatic completion, visual editor чи mass DOCX rewrite.

## Stage 2D — перший runtime (2026-09-09)

Попередні описи Stage 1/2C вище фіксують межі тих етапів. У Stage 2D активовано тільки `nazk_supplier_request` у картці НАЗК.

`metadata/runtime_templates.v1.json` реєструє template key, document_type, provider, active, filename, required_fields, conditional_variants та output pattern. `template_runtime.py` підключає цей config до стандартних admin list/download/replace/validation; старі чотири templates і їх renderers не змінені.

`task_documents.py` збирає whitelist context із перевірених Catalog bindings. Shared supplier_code_semantics обчислюється один раз для code_label/entity_type; supplier_contacts повертає email тільки останньої заявки. Усі шість полів manifest required; відсутній email не замінюється історичним. Guards: наявна нетермінальна nazk_check, current manager identity, effective active qualifications, canonical НАЗК record, активний валідний template/context. Шаблон не виконує SQL чи довільні expressions.

POST `/api/operational-tasks/{id}/documents/nazk-supplier-request` під existing tasks.manage створює версію DOCX та append-only `supplier_request_generated`. Переданий клієнтом context/template path не приймається. GET `/api/operational-tasks/{id}/documents/{document_id}/download` під tasks.read перевіряє task/document scope. Admin-only template permissions залишаються окремими.

`generated_documents` зберігає task/supplier/type/template/hash, filename/storage reference, автора/час, provider/status, день/версію/checksum. Вихідні файли відокремлені від templates; кожна генерація має власний ID і filename `НАЗК_запит_{supplier_code}_{date}_v{version}.docx`. Версія виділяється у транзакції BEGIN IMMEDIATE. Генерація не змінює task status, factual result, source_context або structured channel records і не означає направлення запиту.

Картка показує download/regenerate та історію версій; оновлюється тільки відповідний section/history, без закриття картки або full list reload. Направлення залишається окремою ручною дією УО. Google Docs provider не реалізовано.

## Configurable derived fields — 2026-09-09

Admin UI: «Шаблони документів → Каталог полів шаблонів → Додати похідне поле». Вибір базового string canonical field, transformation_type, grammatical_case, семантичного entity_type (person/legal_entity/fop/other), label, stable key та available_for. Key після створення незмінний; existing system fields не перетворюються через цей editor. Config глобальний, не персональний.

POST `/api/admin/template-fields/derived` (mode=create/update) перевіряє admin role, optimistic revision, key collision/syntax, source existence/type/availability, unsupported transformations/cases, цикли і broken dependencies. Atomic save increment revision + append audit old/new/by/at. Немає eval, SQL або imports із metadata. Інші ролі: editor hidden, прямий write → 403.

Конфігурація першого поля:
```json
{"key":"manager.full_name_genitive","label":"ПІБ керівника у родовому відмінку",
 "source_binding":{"source_type":"derived","source_field":"manager.full_name",
 "transformation_type":"declension","grammatical_case":"genitive","entity_type":"person",
 "unresolved_policy":"error","dependencies":[]},"available_for":["nazk_supplier_request"]}
```
`derived_fields.resolve` — provider-neutral engine з memoized dependency resolution на один request. Context adapter надає whitelist base_resolver; renderer отримує готові значення. Template scanner визначає потрібні keys, не тільки fixed manifest: нове поле, створене Admin і додане до шаблону, обчислюється без Python-змін. Недоступний у цьому context base binding дає явну помилку, не вигадане значення.

Поки є лише transformation_type=declension. Nominative повертає source дослівно. Genitive/accusative reuse decline_name та exact overrides; dative — existing override-only. Instrumental/locative/vocative допустимі в config, але shared engine поки їх не реалізує, тому unresolved/error. Не додано нових мовних правил. Unresolved policy зараз тільки error, без fallback на називний. Для майбутніх transformations зарезервовано тип, але uppercase/short-name/date-format не реалізовано.

У «Схемі даних PQM» кожен derived Catalog field має semantic record `document_field.<key>` з label «Похідне поле», source та transformation metadata. Це не schema migration і не фізичне поле SQLite.

Для nazk_supplier_request родовий використано лише у двох conditional paragraphs після «стосовно»; фраза «за пошуковим запитом» використовує manager.full_name. Runtime manifest вимагає сім keys; manager source та історичні generated DOCX не переписуються.

## Metadata-driven runtime bindings і conditional prefix

Runtime читає source_binding з Template Field Catalog через document_bindings.py, без whitelist document keys/columns. metadata/document_sources.v1.json визначає explicit canonical scopes та імена існуючих semantic sources. Це versioned системний контракт, не SQL або executable code з metadata. Новий Catalog key/column у чинному scope не вимагає Python/JS-зміни. Нове джерело з іншими правилами identity/join потребує погодженого scope adapter; автоматично вгадувати зв'язки заборонено.

Scope adapter використовує поточного manager, призначену УО, current supplier summary і лише linked task records. Нові поля manager/officer дочитуються в межах того самого identity один раз за request. Назва постачальника та code semantics зберігають shared document normalization; email залишається з останньої заявки без historical fallback. UNBOUND, unavailable, inactive, deprecated та broken bindings відхиляються до source resolution. Неоднозначне scalar джерело з кількома records повертає validation error, не перший випадковий record. Missing values не вигадуються. Derived descriptions без машинного binding більше не є достатніми для VALID.

Generic transformation conditional_prefix має source_field (string), condition_field (canonical enum), equals (допустимий enum literal), prefix (string, до 200 символів). Якщо умова true — prefix + source value, інакше source value без змін. Пробіли prefix зберігаються дослівно. Missing/unknown enum → error, не fallback. Обидві залежності проходять availability/cycle/binding validation та memoization через generic derived engine. Додавання transformation конфігурації доступне лише Адміністратору й записується в Catalog audit; Schema показує її як похідне поле.

supplier.display_name: supplier.name; conditional_prefix; supplier.entity_type == individual_entrepreneur; prefix = "ФОП ". ЮО повертає supplier.name без prefix. Поле створене через Admin UI; runtime DOCX автоматично не змінюється.

## Метадані сформованого документа — 2026-09-10

`document_metadata_templates` зберігає глобальні admin-configurable metadata templates окремо від DOCX. Синтаксис поля той самий: `{{canonical.field}}`; validation використовує Template Field Catalog і відхиляє unknown, UNBOUND, inactive, deprecated та unavailable fields. Іншого placeholder engine немає. Зміна конфігурації versioned та append-only аудитується в `document_metadata_template_events`.

Перший metadata key — `askod_short_summary`, label `Короткий зміст АСКОД`. Для `nazk_supplier_request`: `Запит до {{supplier.short_name}} щодо надання довідки з Реєстру НАЗК`. `supplier.short_name` — current `supplier_edr_profiles.short_name`, fallback до canonical `supplier.name`; якщо обидва джерела відсутні, generation завершується validation error. Значення з ЄДР не доповнюється префіксом `ФОП` і не використовує `supplier.display_name`.

Resolved metadata зберігається у `generated_documents.metadata_json` разом із конкретною версією документа. Воно не перераховується під час читання, тому історична версія не змінюється після оновлення supplier data або metadata template. Картка показує compact plain-text value та `Копіювати`; це не змінює task status або channel state.

Адміністратор редагує metadata template у `Адміністрування → Шаблони документів → Метадані документа`, шукає поля за label/description/group/key та вставляє stable placeholder. Routes/document types лишаються системними. `nazk_authority_request` поки не має runtime template registration, тому metadata config для нього не матеріалізовано; його буде додано разом із самим runtime document type.

Admin metadata registry є generic і configuration-driven. Для вже зареєстрованого runtime `document_type` адміністратор може створити унікальний `(document_type, metadata_key)`, задати label, description, active-state та текст із тими самими Catalog placeholders. Key і document type після створення є stable identity; редагуються label/description/template/active. Кожна фактична зміна підвищує version і створює append-only event, а ідентичне збереження повертає `changed=false`. Inactive metadata не резолвиться у нові generated document versions; уже збережені resolved metadata не перераховуються. Фізичне видалення через Admin UI не підтримується — використовується деактивація.

Document-card contract також configuration-driven: backend перетворює persisted metadata конкретної generated version у впорядкований `resolved_metadata[]` (`metadata_key`, `label`, `resolved_text`, `version`, `display_order`). UI рендерить цю collection одним shared component і копіює лише `resolved_text`; порожні values пропускаються. Frontend не знає metadata keys і не виконує повторний resolve. Тому деактивація config впливає лише на наступні generation, а historical version продовжує показувати вже збережені resolved values.
