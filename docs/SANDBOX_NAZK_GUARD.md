# Dormant sandbox NAZK export protection

This change does **not** enable a UI/API refresh route, scheduler or NAZK workflow.
`PQM_SANDBOX_NAZK_READ` defaults to 0 and must remain absent/0 on Render until
a complete validated official export succeeds and live use is separately approved.
The existing safe-mode route denylist and disabled workflow/jobs remain in effect.

Prepared transport: exact official `getAllData` HTTPS GET, no credentials/proxy/
redirects, public DNS pinning, 30s socket timeout, 60s total child deadline
(including DNS and JSON parsing), 100 MiB response cap. A deadline kills/reaps the
process group and removes temporary files. No alternate partial-search fallback.
The Python audit hook is defense in depth, not an OS firewall/filesystem sandbox.

Sandbox-only lifecycle protection reserves a live worker before Timer startup,
rejects duplicate starts, releases reservations on startup or worker failure,
and presents orphaned persisted `running` as an interrupted error without a DB
write. Existing registry validation and transaction rollback are retained.
Sandbox success never invokes the supplied business `on_complete` callback.
Non-sandbox export/lifecycle behavior remains unchanged.

`validation/sandbox_nazk_smoke.py` uses temporary synthetic SQLite only and mocks
transport/process failures. It covers timeout, malformed/empty/duplicate payload,
disabled transport, orphaned status, Timer failure, duplicate/direct start,
failed terminal status persistence and suppression of business callbacks.
No live refresh is needed or allowed for this offline guard rollout.
