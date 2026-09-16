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

This is **not full staging workflow parity yet**: no automatic schedulers, AMCU/NAZK refresh,
Google/Bids/PowerBI, document-generation subprocesses, or general task mutations are enabled.
Promote only reviewed code, never sandbox business rows, back to production.

Disable: set `PQM_SANDBOX_PROZORRO_READ=0` and restart sandbox only. Code rollback baseline
`cafb3f13f168c8364fb253d3f72bd9af6ad4d35b`; retain the fresh backup if data rollback is required.
Do not overwrite a sandbox DB after subsequent user edits without checking the delta first.
