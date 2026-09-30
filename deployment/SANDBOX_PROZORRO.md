# Sandbox: manual public Prozorro reads

Only `srv-dalfd77f3r2c7392uub0` (`pqm-sandbox`), owned `/var/data/pqm_sandbox.sqlite3`.
Do not set these options on `main`/`pqm-production-1` or copy production credentials.

Set `PQM_SANDBOX_PROZORRO_READ=1` only after a fresh verified sandbox SQLite/active-assets backup,
synthetic gates and a real one-framework import on a disposable copy. Keep the entire existing
`sandbox_runtime.POLICY`, including `PQM_SAFE_MODE=1`, all jobs off, Google/NAZK workflow off.

The exception permits only authenticated, normally authorized `POST /api/sync`. It does not grant
`prozorro.update` to an officer/viewer. Existing local edits and final/historical restrictions remain.
External access is credential-free HTTPS GET to the public Prozorro framework, submission,
qualification and agreement-contract endpoints. Other hosts/methods, private DNS results, proxies,
unapproved redirects, unrelated threads and child processes remain blocked. This Python-process
guard is defense in depth, not an OS/network firewall.

Full manual scope uses the copied WEB framework IDs, not Google discovery. Google assignments are
not reimported/overwritten. Separate background contract/document checks are not enqueued. The same
framework import and supplier projections run on the sandbox DB; application-level NAZK controls
may update from imported facts, but no NAZK check/review materialization or registry refresh runs.
Existing qualification-driven lifecycle reconciliation remains part of the shared sync worker;
the generic task builder remains suppressed by safe mode. Preview/diff the chosen framework first.

Optional automatic stage: set `PQM_SANDBOX_PROZORRO_SCHEDULER=1` with READ=1 only after a fresh
backup and full incremental startup run on a disposable sandbox DB copy. Native POLICY flags
and persisted scheduler settings remain 0; only the effective Prozorro job is enabled.
The production scheduler implementation/configuration remains unchanged. Sandbox uses the same
active-framework incremental worker, hourly at :05 Europe/Kyiv, with a startup catch-up.
Recent completed automatic runs suppress duplicate catch-up. A manual single-framework run
does not stand in for an automatic run. A surviving lease is honored; restart retries every
30 seconds until it completes or expires (existing 180s TTL/30s heartbeat), without stealing it.
Check `/api/runtime-features`: Prozorro configured/registered/running, heartbeat, last result,
next run/timezone; all other jobs/integrations must remain off. No DB schema migration is needed.
Disable this stage by setting `PQM_SANDBOX_PROZORRO_SCHEDULER=0` and restarting sandbox only.

This is **not full staging workflow parity yet**: AMCU/NAZK refresh,
Google/Bids/PowerBI, document-generation subprocesses, or general task mutations are enabled.
Promote only reviewed code, never sandbox business rows, back to production.

Disable all Prozorro: set both sandbox Prozorro flags to 0 and restart sandbox only. Code rollback baseline
`cafb3f13f168c8364fb253d3f72bd9af6ad4d35b`; retain the fresh backup if data rollback is required.
Do not overwrite a sandbox DB after subsequent user edits without checking the delta first.
