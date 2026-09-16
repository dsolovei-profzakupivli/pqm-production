# PQM NEXT LOCAL — 2026-09-16 FINAL

Canonical source: `D:\AI\Codex\Projects\PQM-0.1`. New control point; does not replace `FINAL_FROZEN_20260914`. No WEB deployment or business sync performed.

## Scope since previous frozen point

Lightweight Перевірка ЄДР register, server-side filters/sorting/pagination, contextual freshness KPI, multi-status filters, column visibility/widths, viewport table, Google source notes, ClarityChecker export contract; coherent verification date/officer and known-manager projection; controlled EDR sync v2 preview/apply and stable business-event hash; AMKU completion reconciliation and document binding; termination operational workflow; shared protocol actions and declension/template navigation; safe full-registry projection and offline Apps Script UPSERT writer.

## Schema and startup

Versioned migration references are in `migrations/`, including `20260915_amcu_completion_lifecycle.sql` and `20260915_edr_google_sync_v2.sql`. Established startup `server.init_db()` invokes idempotent `edr_sync_v2.migrate()` and `operational_tasks.migrate()`. The latter creates `operational_task_qualification_decisions`; it is shipped in source, not a manually patched DB dependency. Scheduler, navigation and evidence migrations remain included. Do not blindly replay non-idempotent ALTER statements from reference SQL; use established Python migration functions.

No LOCAL SQLite DB or imported runtime data is packaged. Back up the target DB before migration. Historical MedData tooling and its source manifest are included; no historical import is automatic release acceptance.

`server.main()` normally also rebuilds operational tasks and applies scheduler settings. Initial controlled UI-only deployment must use `tools/run_ui_only_safe.py`, which disables both task rebuild and scheduler application. Do not start ordinary production mode before explicit operational approval.

## Configuration (no secret values)

Python 3.12 / `requirements.txt`, project assets, and `tools/prozorro_eds_adapter` package/lockfile are included. Rebuild Node dependencies. Set `HOST`, `PORT`, `PQM_ENV`, persistent `PQM_DATA_DIR`, authentication/config according to the runbook. For safe startup set browser, all scheduler flags, Bids update, Power BI and Google enable flags to 0; persisted settings also require review before normal startup. OAuth client/token files and `PQM_SUPPLIER_REGISTRY_TOKEN` must be provisioned separately, never stored in this archive. WEB OAuth requires the correct HTTPS callback and persistent OAuth directory.

## Documents

| Workflow | Canonical source | DOCX / PDF / gate |
| --- | --- | --- |
| AMKU | `templates/amcu_exclusion_protocol.docx` | Established DOCX/version/PDF path; per-decision hyperlink and declension gates |
| Appeals | `templates/violation_protocols/{warning,decline_p49_1_2,decline_p49_3}.docx` | Established DOCX/PDF; decline 1/2 runtime/package bytes equal |
| Termination FOP | `templates/termination_exclusion_protocol.docx` | Approved legal source preserved byte-identically; alias mapping, shared DOCX/version/PDF wired |
| Termination legal entity | Not approved | Document generation intentionally blocked; operational workflow remains available |
| NAZK | `templates/nazk_supplier_request.docx` | DOCX and shared same-version operational PDF action wired |
| Application protocol | `templates/application_protocol.docx` | Established application workflow |

Template registration/fields are in `metadata/runtime_templates.v1.json` and `metadata/template_fields.v1.json`. Resolution uses project-relative templates and the configured data directory, not user-profile absolute source paths. Missing runtime copies are seeded from packaged sources; existing operator-managed copies are not overwritten automatically. Compare target runtime templates before deployment.

LOCAL synthetic FOP termination PDF evidence: `%PDF` header valid, **111712 bytes**, source is the same generated DOCX version. Dockerfile installs LibreOffice; actual target WEB converter availability is not confirmed without deployment. Mandatory pre/post-deploy check: discover converter (or `PQM_SOFFICE_EXE`), writable temporary directory, convert a safe fixture, verify PDF header and same-version download/content-disposition. Never treat JSON conversion errors as downloads.

## Verification evidence

Run for this release: 26 offline writer tests; 50 focused termination-document/full-registry/EDR-sync/migration-toolkit tests; 30 consolidated/EDR-monitoring/termination/declension checks; Node syntax check; LOCAL health; read-only release browser smoke (seven modules desktop + 520 px, admin templates, exceptions/errors/mutations = 0); targeted declension/template navigation, synthetic protocol actions and read-only Google-note browser checks (exceptions = 0).

Recent passing evidence reused where source did not change: AMKU/appeals DOCX regressions and PDF/error handling; 53 template/blocker closure checks including FOP source preservation, v1/v2 history, unresolved/terminal/ЮО gates; actual LOCAL synthetic PDF conversion above. Previously accepted EDR viewport/column/filter UI remains covered by focused structural/query regressions and the user's manual acceptance; this release does not claim a fresh exhaustive browser replay of every EDR combination.

## Deferred integrations and safe WEB order

1. Back up target DB/templates/config; provision dependencies and persistent storage, secrets separately.
2. Review migration changes and target template parity. Start UI-only safe launcher; verify integrity/schema, health, navigation and operational document actions without sync/rebuild.
3. Verify actual WEB PDF converter with safe fixtures, including same DOCX version and error behavior.
4. Google → PQM: configure OAuth, run read-only preview, review fingerprint/counts/conflicts; controlled Apply only after explicit acceptance. Repeat unchanged preview to confirm idempotency.
5. PQM → Google: final writer is included in `scripts/pqm-google-writer`, but cloud Apps Script integration is deferred. Configure HTTPS full-registry URL and Bearer token in Script Properties, enable Sheets service, audit real cloud headers/formulas/validation. First read-only preview, controlled Apply, idempotency check; only then authorize a morning trigger. Existing G/J/K are Google/Clarity-owned and preserved; appended rows leave them blank; writer neither copies nor generates J/K. Existing cloud onEdit G → J/K remains external behavior.
6. Enable scheduled/business operations only after separate approval. No real exclusions, imports, triggers or WEB deploy were performed for this release.

## Archive safety

Exclude secrets/OAuth credentials, runtime databases/WAL/SHM/journals, logs/caches, node_modules, browser/test outputs, temporary copies, generated documents and old ZIPs. Keep these untouched in the working project. Archive integrity/listing and secret-pattern audit must pass before handoff; checksum is delivered beside the ZIP.
