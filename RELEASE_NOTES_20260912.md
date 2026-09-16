# CURRENT LOCAL → WEB TEST — release notes 2026-09-12

## Основні відмінності від package 2026-09-06

- незалежні scheduler jobs із `Europe/Kyiv`, persistent per-job leases та прозорим runtime status;
- окремий persistent Admin runtime control для ручного Bids update без автоматичного запуску;
- завершений FINAL LOCAL UI polish і responsive filter/navigation layouts;
- strict НАЗК coverage за `supplier_code + manager identity + explicit registry source IDs/cycle`, без date-only fallback;
- safe LOCAL-only relation backfill: 98 single-fact relations, 0 duplicates, repeat run 0/0; ці business rows не входять до package;
- єдина factual/presentation semantics НАЗК, label `Спростовано`;
- shared operational task/detail-window framework і assignment УО;
- canonical source set модуля `Відбори`, включно з manual PQM selections;
- DOCX conditional renderer, metadata-driven bindings і configurable derived fields;
- template Catalog persistence/atomic replacement для Windows;
- no-highlight canonical DOCX replacement і version-safe regeneration;
- generic configurable document metadata та generic rendering resolved metadata у картках;
- protocol DOCX/PDF download flow без approximate Chromium fallback;
- customer-name reuse, supplier EDR/current qualification projection fixes;
- Admin templates/metadata search and collapse;
- canonical links і `used_for_blocking` presentation для warning workflow;
- active navigation після refresh синхронізується з canonical route/view.
- Google runtime control і fail-closed enforcement, persistent OAuth state/PKCE, origin validation та atomic token persistence.

## Release gates

- Full Python suite: `640/640 OK`.
- Scheduler focused suite: `18/18 OK`.
- Bids runtime-control focused suite: `9/9 OK`.
- Google runtime/security focused suite: `7/7 OK`.
- НАЗК workflow/evidence/tasks focused suite: `112/112 OK`; manager-cycle A–G: `7/7 OK`.
- Operational tasks/search focused suite: `16/16 OK`.
- Document/metadata generation focused suite: `115/115 OK`.
- Python compile: `96/96`; JavaScript/MJS syntax: `19/19`.
- Read-only browser smoke: desktop + 520 px, console errors `0`, runtime exceptions `0`, mutating requests `0`.
- LOCAL safe mode: schedulers disabled, `next_run = null`, Bids update disabled.

Known non-blocking test output: Python `ResourceWarning` for closed SSL sockets in integration fixtures. Tests complete successfully.

## WEB TEST NAZK warning

LOCAL NAZK relation backfill (98 rows) is not business data to deploy. WEB TEST requires its own read-only classification and separately approved targeted backfill before mutating NAZK reconciliation. Не переносити LOCAL manifest/check IDs/manager IDs/source relations як WEB write manifest. Вісім LOCAL `multi_fact_needs_provenance` cases навмисно не auto-backfill-нуті.

## Прийнята LOCAL Google acceptance

Один контрольований read-only-scope EDR import опрацював `14 776` source rows (`ФОП 7 361`, `ЮО 7 415`) без errors та без delta operational НАЗК tasks/supplier-level checks. Створені manager-refresh controls відповідають 69 distinct active submissions; повторна незмінна обробка дала 0 additional rows. Результат класифіковано `SAFE`. Backward `edr_checked_at` були source-driven через старіший Clarity file і не є PQM defect. Під час release gate повторний Google sync не запускався.
