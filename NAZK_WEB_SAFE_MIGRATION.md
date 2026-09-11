# WEB TEST NAZK repair — 2026-09-11

Never invoke this migration from startup or a generic task rebuild. Do not run
the LOCAL-specific `migrate_nazk_legacy.py` against WEB.

## Startup boundary

`rebuild_operational_tasks()` / `operational_tasks.build()` exclude NAZK by
default. Violation catch-up and Prozorro jobs cannot indirectly reconcile,
materialize or cancel NAZK cycles. Explicit NAZK registry-job completion uses
`rebuild_nazk_tasks(..., workflow="nazk_job")`, additionally requiring
`PQM_ENABLE_NAZK_WORKFLOW=1` (default: disabled). Explicit maintenance is separate.
Keep the NAZK scheduler/workflow disabled until history correction is verified.

## Maintenance procedure

1. Docker build and run `validation/nazk_startup_guard_smoke.py`,
   `validation/nazk_web_migration_smoke.py`, and the isolated release suite.
2. Stop application writers and schedulers with the standalone maintenance
   server. Verify PID 1, TEST service ID and database path. Create an SQLite
   backup, persistent-files archive and private configuration backup. Download
   and verify SHA-256, integrity and foreign keys before changing business data.
3. Use `migrations/web_nazk_history.py --db TEST_BACKUP_COPY --plan PRIVATE_JSON`
   to generate a read-only manifest. Its printed hash is of canonical JSON,
   not of a prettified representation. Keep private manifests outside Git.
4. Rehearse against the backup copy. Apply with `--apply-sha256 PLAN_HASH
   --maintenance-backup-sha256 BACKUP_HASH`. The apply transaction fails if any
   relevant input changed. A matching receipt makes repeats a no-op.
5. Review each proposed change. Only one unambiguous same-person registry fact,
   non-empty exact case/date, historical factual result and evidence reference,
   with check date not before the fact, may yield a factual import. Multiple
   facts, missing case/date/evidence and ambiguous manager evidence remain held.
   This conservative version does not auto-resolve disciplinary records.
6. Apply the verified manifest to the stopped WEB TEST only. Existing factual
   checks and legacy rows remain unchanged. Old events remain immutable.
   Waiting cycles reuse existing checks/tasks; no requests or correspondence
   are sent/duplicated. `Не актуально` is non-factual. Unknown reasons stay
   explicitly unresolved, without closing a current task.
7. After correction only: reconcile stored NAZK evidence (no external refresh),
   then materialize and perform two generic rebuilds. Require no new redundant
   cycles, no duplicate task keys, idempotency and unchanged canonical factual
   history. Imported factual coverage requires both exact registry links and
   historical date coverage; later import time cannot extend that coverage.
8. Start WEB normally with violation scheduler enabled and NAZK disabled.
   Verify zero new NAZK checks/tasks, workload states in UI and service health.

No LOCAL DB, PROD changes, schema replacement or dependency changes are needed.
Ambiguous history is retained as `legacy_imported` plus an immutable full source
snapshot in `supplier_nazk_check_events`; it does not acquire a fabricated result.

## Rollback

Keep the verified pre-maintenance backup off the Render disk. If validation
fails before reopening, stop writers, preserve the failed DB for diagnosis and
restore that exact WEB snapshot plus the previous code/config. Never restore an
older snapshot over new user writes after reopening without a separate plan.
