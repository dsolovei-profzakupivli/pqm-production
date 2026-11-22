# Sandbox experience task exception

Keep PQM_DISABLE_BACKGROUND_JOBS=1. The existing experience worker is the only new exception to that environment lock. Scheduler jobs, automatic synchronization, Writer and other processes keep their existing interlocks.
A persisted .pqm-background-jobs-disabled emergency marker or state_error still blocks this task. No marker is removed and no Render variable is changed by the implementation.

After manual ingestion, the existing framework scope admits pending work. At process startup one additional scope scans existing pending rows in keyset batches of 32, on the same two-worker executor. This scan reads SQLite only; it does not download submissions or call sync. Active ID/scope caps remain 128. A second overlapping startup scope is rejected.

Previously saved positive, negative, unavailable or legacy experience is skipped, regardless of age/fingerprint. Invalid historical JSON fails closed. The same check repeats under BEGIN IMMEDIATE before writing to avoid overwriting a result completed concurrently. Historical/read-only/finalized applications are skipped. Existing KEP/MVS categories, document_checked_at and manual fields remain intact.
A temporary unavailable search is not persisted as completed evidence; the existing capped retry policy is used. Scope/job metadata and caches retain Stage 1 bounds. Restart may scan missing work again, but never overwrites saved experience.
No new cron, timer polling, endpoint, UI control, database schema, Google access or Production exception is introduced. Missing-work scanning is enabled by this code only after a separately approved deployment; local tests use disposable synthetic fixtures.

The PENDING ID reservation now covers the entire queued/active/waiting-retry chain. A timer uses an identity token, so duplicate/cancelled callbacks cannot claim a newer chain. A callback that fires before active release becomes READY and is dispatched once on release. Missing scans skip the owned ID without touching its budget.

When all 128 ID slots are owned, a scope parks its cursor in bounded metadata (maximum 128 scopes), releases its worker and resumes on a release/retry/admission event. It does not spin executor continuations, skip IDs, block a worker for a timer, or add polling.

The budget is at most two additional attempts per chain, unchanged from the existing configured constant. Terminal exhausted markers are retained within the existing 128-entry budget metadata cap; only terminal unowned markers may be evicted to admit a later independent chain. An in-flight/waiting budget is never evicted/reset. Restart rebuilds missing work from SQLite and starts fresh in-memory budgets; this is not a lifetime retry limit across all restarts/manual runs. Saved results are always skipped.

Timer startup failure keeps the already reserved retry READY and uses the existing executor (the normal 60-second delay cannot be supplied by a failed timer thread). Executor submission failure retains ownership/budget/cursor for a subsequent admission/release or restart, without an automatic busy retry loop. No claim of progress through a permanently broken executor is made.

At emergency stop, waiting timers are cancelled and deferred scopes are retired. The physical marker is never removed.
