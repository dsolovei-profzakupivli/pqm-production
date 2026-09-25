# PQM → Google — NEXT LOCAL implementation

Permanent daily-sync package: install `PqmSandboxPreviewDependencies.gs`,
`PqmSandboxPreview.gs`, `PqmSandboxControlledApply.gs`,
`PqmSandboxFullApply.gs`, and `PqmSandboxAppendApply.gs` together. The matched-row
Full Apply and bounded append stage both use the same `pqmGooglePlan_()` and the
full-registry `google_sync_eligible` decision predicate. H uses
`google_sync_last_decided_application_date`, never an undecided application.

`PqmGoogleWriter.gs` below is a historical standalone prototype with its own
planner globals and eligibility predicate. It is **deprecated** for this package:
do not install or run it alongside the permanent daily-sync files. It remains in
the repository for historical reference, not as an alternate production writer.

Status: standalone writer implemented and tested offline. Existing cloud scripts and the current onOpen were not available; integration into the actual menu is pending. No real PQM API, Google spreadsheet, trigger, tunnel, WEB deployment or database operation was performed.

Files:
- `PqmGoogleWriter.gs`: pure planner, validated API reader, batched spreadsheet snapshot, request builder, shared writer, preview/Apply UI and menu builder.
- `writer.test.cjs`: 26 offline fixture/mock tests, including an independent executor for emitted write requests.
- `fixture-preview.json`: illustrative six-record dry-run; not production counts.

Functions: `pqmGoogleWriter(options)` defaults to preview; `pqmGooglePreview()` shows counts and requires explicit Yes to Apply; `pqmGooglePlan_()` plans only; `pqmGoogleRequests_()` constructs one atomic batch. Manual and any future scheduled wrapper use `pqmGoogleWriter`. No scheduled wrapper/trigger is installed.

## Ownership

| Column | Source | Existing row | New eligible row |
| --- | --- | --- | --- |
| A | freshness_marker | update nonblank literal | write nonblank literal |
| B | supplier_code | identity only, never rewrite | exact trimmed string, TEXT |
| C | supplier_name | update nonblank | write nonblank |
| F | prozorro_status_google | update nonblank | write nonblank |
| H | last_application_date | valid ISO date only | valid ISO date only |
| D/E/G/I/J/K/L/M/N/O | Google-owned | preserve values/formulas | all Google-owned cells empty; no unaudited formulas copied |

H uses a real Sheets date serial with `dd.MM.yyyy`; no locale-dependent parsing. Invalid dates add an error and leave H untouched; other valid fields may still update. Marker values are copied without recalculation. Formula-like API strings are stored as literal stringValue.

Routes: individual_entrepreneur → ФОП; legal_entity → ЮО; foreign_legal_entity/unknown → skip. Existing rows update regardless of monitoring eligibility; append requires true. Exact trimmed codes are never padded or numerically converted. Legacy numeric Google B cells are matched by their displayed code to preserve visible leading zeroes. Duplicate keys within/between tabs or API are blocked; a key in the wrong tab is a conflict, never a move. Missing API suppliers stay untouched.

## Formula / validation findings

Confirmed existing behavior (user confirmation): G is «Реквізити рішення про припинення». Existing onEdit(e) extracts the record date into J «Дата запису» and record number into K «Номер запису» using regex when G is edited. J/K are stored values, not row formulas, and are NOT an unresolved formula gap. The writer never changes existing G/J/K, copies their values from a template, or generates J/K formulas; appended G/J/K remain blank. The existing onEdit parser is unchanged and remains responsible for subsequent qualifying edits to G.

Actual cloud formulas in other columns, validations and current headers were not inspected. The supplied 15-column contract is checked exactly at runtime before any mutation.

Fixtures confirm that a formula in A/B/C/F/H blocks the whole matched record, including a formula in B. An append template with an owned-column formula blocks append. Merged owned cells on existing rows also conflict. Append uses the last populated A:O row as the established template; a header-only tab has no safe template and conflicts. It copies format and validation separately, preserves template row height with updateDimensionProperties, and extends conditional format rules that cover the template row. G/J/K stay blank on append by confirmed ownership design, with no formula gap. Other Google-owned columns also stay blank. Only formulas actually observed in template metadata produce an explicit preview gap; missing J/K formulas do not. Missing row-height metadata or a merged template/destination blocks append. It copies no business/manual values, notes, or N/O formulas. Existing validations are untouched.

The separate format/validation requests follow [Google's CopyPasteRequest contract](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request). Changes are submitted in [one batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate); an invalid request rejects the batch. Production rules, validation values, formula spill ranges, sheet protections, payload size and execution time still need a real read-only preview before Apply.

## Preview, errors and concurrency

Preview performs no writes, including no property/cache writes. Apply refetches the API and both tabs under ScriptLock and compares a SHA-256 digest of the source data and sheet snapshot against the preview. API generated_at is excluded. Changed data, formula/validation/format/row-height metadata or a missing digest abort Apply. The lock is released before showing the dialog and reacquired for Apply. Lock contention rejects immediately (tryLock(0)); it does not queue a second run. Each invocation fetches once; a confirmed manual preview + Apply therefore fetches twice to detect stale data.

ScriptLock serializes this writer, not interactive Google edits or other scripts that ignore the lock. Google does not provide a conditional batch write tied to this snapshot; collaborators must avoid edits during the short final read/write interval. This is not a cross-application transaction lock.

401/403 and all non-200 statuses, redirects, invalid JSON/schema or headers abort before mutation. Transport errors are sanitized; neither tokens nor response bodies are logged. A failed/uncertain batch is not retried automatically: preview again to reconcile. Abort conditions throw an error instead of returning success counts.

Counts describe planned records in preview and the applied plan after success. `matched` overlaps updated/unchanged/conflicted matched records. `duplicate_keys` counts unique duplicate identities, including duplicates absent from the API; `conflicts` counts blocked API records. `errors` counts invalid date fields. Global skipped foreign/unknown records have no destination-tab subtotal.

Fixture: api_records=6, matched=2, appended=1, updated=2, unchanged=0, skipped=3, conflicts=0, duplicate_keys=0, errors=0; Google writes=0. ФОП: updated=1. ЮО: updated=1, appended=1, skipped=1.

Tests: `node --test writer.test.cjs` → 26 passed, 0 failed. Covers every requested fixture scenario plus stale preview, literal formula-like text, append template conflicts, emitted request preservation, sanitized transport/batch failures and snapshot date/code handling.

## Remaining integration before a real WEB run

1. Provide the current Apps Script files / onOpen and verify the actual ClarityChecker and date/officer handlers. The only local historical script found was a standalone July organization editor; it was not modified or reused as the current menu.
2. Add the module to the bound Apps Script project and enable the advanced **Google Sheets API v4** service (`Sheets`). Merge that dependency into the existing manifest; do not replace the manifest.
3. Call `pqmGoogleBuildMenu({clarityChecker: <actual handler string>, dateAndOfficer: <actual handler string>, organizationEditor: <actual handler string>})` from the current onOpen. Replace its menu-building section only. The builder produces exactly `⚙️ Робота з даними`: PQM → Google, separator, 🏢 Заповнити дані з файлу ClarityChecker, separator, 📆 Оновити Дату та УО для виділених рядків, separator, ✏️ Редактор ЮО. Its first item invokes preview. The actual menu is not yet integrated.
4. Configure `PQM_FULL_REGISTRY_URL` (reachable HTTPS full `/api/integrations/suppliers/full-registry` URL) and `PQM_FULL_REGISTRY_TOKEN` solely in Script Properties. No credentials/URL defaults are embedded in the writer. The .invalid URL and fake token in tests are isolated fixtures.
5. Inspect a real read-only preview for actual headers, formulas/array formulas, append template validation/conditional rules and scale. Resolve conflicts and obtain explicit Apply in Google only when the WEB endpoint is ready. No such run is part of this implementation.

The source API contract was read from the local PQM `docs/SUPPLIER_FULL_REGISTRY_API.md`. NEXT LOCAL is the post-frozen source tree at `D:/AI/Codex/Projects/PQM-0.1`, as defined by the local release boundary. The frozen release archive is unchanged.

## Changes in this continuation

The pre-existing local writer was completed with exact menu labels, template row-height preservation, fail-closed merged-append/unknown-height handling, removal of J/K propagation in accordance with confirmed onEdit G → J/K behavior, visible formula-audit gaps and immediate concurrency rejection. Added four focused mock tests and expanded the existing append/snapshot/menu checks. No current cloud script was available, so the menu builder is ready but cloud onOpen integration and actual formula/validation findings remain unverified.
