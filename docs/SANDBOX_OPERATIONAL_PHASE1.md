# SANDBOX operational baseline, phase 1

`PQM_SAFE_MODE=1` remains mandatory. `PQM_SANDBOX_OPERATIONAL=1` is a separate,
explicit opt-in for internal workflows. Before a permitted workflow writes,
`attest_internal_target()` checks the configured database path, existing
SANDBOX ownership marker and approved Render service. Existing login/RBAC,
business predicates and audit history remain in force.

| Existing action | Phase-1 decision | Destination / constraint |
|---|---|---|
| Prozorro `/api/sync`, `/api/frameworks/refresh` | ALLOW_EXTERNAL_READ + ALLOW_SANDBOX_INTERNAL | Exact public API read allowlist; attested SANDBOX DB; task rebuild after qualification sync |
| Prozorro violation/appeal sync | ALLOW_EXTERNAL_READ + ALLOW_SANDBOX_INTERNAL | Exact `violation_reports` API read; local report and warning-task records |
| AMKU refresh | ALLOW_EXTERNAL_READ + ALLOW_SANDBOX_INTERNAL | Isolated official public read; successful registry commit followed by shared task builder; failure surfaced as AMKU error |
| AMKU Excel upload | INTENTIONALLY_UNSUPPORTED in phase 1 | Existing SANDBOX AMKU parser deliberately rejects uploads; shared PROD path still gets the post-refresh task builder |
| NAZK refresh | ALLOW_EXTERNAL_READ + ALLOW_SANDBOX_INTERNAL only with `PQM_SANDBOX_NAZK_READ=1` | Exact official GET and attested SANDBOX DB; existing explicit NAZK task workflow |
| Operational-task rebuild, card edits/history, responses and qualification links | ALLOW_SANDBOX_INTERNAL | Exact route allowlist; existing auth/RBAC; no document send/generation routes opened |
| EDR Google OAuth and Google→PQM Preview/Apply | Separate SANDBOX EDR opt-in | Exact SANDBOX spreadsheet, scoped OAuth store and source fingerprint/state digest |
| Google announcement directory and remarks Sheet refresh | INTENTIONALLY_UNSUPPORTED in phase 1 | Requires separate source-ID attestation; existing SANDBOX skip remains explicit |
| Google Docs/Drive templates, generated-doc folders and external sends | INTENTIONALLY_UNSUPPORTED in phase 1 | Dedicated SANDBOX copies/targets required in phase 2; PROD targets blocked |
| Unknown external URL, PROD DB/Sheet, runtime-feature enablement | BLOCK_EXTERNAL_WRITE | No generic egress or SAFE_MODE exception |

The AMKU refresh→task call is shared product logic, not a SANDBOX-only
implementation. On task-builder failure, the source replacement may already
be committed, but AMKU refresh status becomes `error`; the task-builder
transaction rolls back and a retry uses the existing idempotency keys.
AMKU registry membership alone does not create an operational task: only a
current effective active qualification requiring exclusion does. A new pending
application is visibly AMKU-blocked in the application registry and cannot be
admitted through the UI or API, but does not itself create an operational task.
Completed historical work stays closed until a new active qualification cycle.
No scheduler or global Google integration is enabled by this phase.
