# CURRENT LOCAL → existing WEB TEST, 11 September 2026

Source ZIP SHA-256: `e2bec5f54c9097a85d064d4da723b8c0c16ca9b1989b26cf5daf5c1af25999dc`.
Three-way base: delivered September 10 LOCAL; WEB base: `e5dde6623be594a4179fb47f0b214dec7a405e30`.

This is an integration, not a replacement WEB database or deployment configuration.
Preserve the existing service `pqm-production-1`, `/var/data/pqm_test_20260831.sqlite3`, DB accounts/sessions,
avatars, account preferences/presence, chat/attachments/read receipts/notifications, approved PNG favicons,
and WEB business records. Do not configure `PQM_USERS_JSON`, rotate credentials, import LOCAL data, or touch PROD.

## Runtime contract

- `PQM_ENV=web`, `PQM_AUTH_ENABLED=true`, `PQM_RELEASE_SCHEMA_ONLY=1`.
- `PQM_ENABLE_PROZORRO_SCHEDULER=1`, `PQM_ENABLE_VIOLATION_SCHEDULER=1`.
- `PQM_ENABLE_NAZK_SCHEDULER=0` by explicit user decision; manual reference features retain their existing permissions.
- Google, Bids update, PowerBI and browser launch remain disabled; Bids mode remains `disabled`.
- Keep the existing HOST, PORT, all paths and secrets. Normal start: `python server.py`.
- Optional supplier registry integration stays fail-closed without `PQM_SUPPLIER_REGISTRY_TOKEN`; no token is provisioned in this release.

Scheduler jobs have separate SQLite leases and persisted outcomes; leases are renewed while workers run and
expire after a killed process. Threads are supervised, failed starts release the registration slot, and transient
trigger failures do not kill hourly scheduling. Runtime status reads do not write/migrate the database and do not
advertise a next run for a disabled/dead thread. Schedules use Europe/Kyiv.

## Additive migration / preservation

`deploy_release.py --db <existing WEB DB>`; do NOT pass `--apply-navigation` for this update.
New tables: `document_metadata_templates`, `document_metadata_template_events`, `scheduler_job_state`,
`scheduler_job_leases`. New columns: `generated_documents.metadata_json`,
`violation_report_reviews.generated_protocol_metadata_json`. Three supplier-registry indexes are added.
No existing business fields, account records, or chat content are replaced by the migration.

Keep startup seed/backfill/rebuild guards. Active authorized officers may review any pending application,
independent of framework assignment. Final admitted/rejected application rows remain immutable for all roles.
Only the supplied updated NAZK DOCX template should replace its unmodified previous-release runtime copy;
preserve all generated documents and template history. An operator-edited template is a STOP/review condition.

Before deployment: verified current backup, migration rehearsal against its copy, exact-commit Docker build,
container smoke and WEB browser acceptance. A source-package test claim is not a Docker GO.

## Verification commands

```
python validation/web_smoke.py
python validation/release_v2_smoke.py
python validation/scheduler_smoke.py
python validation/run_local_release.py
node --check app.js
```

The delivered suite is stored in `validation/local_release_20260911`; the runner stages it with WEB source
and disposable DB/templates. Original ZIP is retained outside the checkout. Three assertions are explicitly
adapted to pre-existing WEB policy: viewer chat is allowed while business writes are denied; authentication
disabled in WEB yields fail-closed 503 before Bids RBAC; PNG magnifier favicons replace the old LOCAL WebP.
No tests are skipped. Runtime DOCX copies are seeded in the test fixture, not taken from a live database.
PDF path containment resolves the protocols root (including OS temporary-directory symlinks) before comparison.

Keep runtime backup manifests and acceptance results outside the public repository; never commit secrets or DB files.
