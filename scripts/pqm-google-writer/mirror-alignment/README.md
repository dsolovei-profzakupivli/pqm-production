# Local mirror alignment — NOT INSTALLABLE YET

Base: `d7cb5fcc18f0f04db7b07c980315754bf6719118`.
The prod and sandbox directories are separate cloud-derived project packages.
They must never be combined into one Apps Script project.

No cloud writes, push, installation, trigger changes, or Apply were performed.
Original cloud exports are independent rollback evidence, not these edited packages.

Latest business contract: typed full verification instants, UPDATE C/D/E/F/H/I/L,
APPEND B/C/D/E/F/H/I/L and formula A. B is immutable on existing rows.
E now participates in the same whole-row gate; unknown E mappings fail closed.
Blank destination verification time accepts a valid newer source observation.
Date-only historical values are represented as Kyiv midnight with their original
precision; this does not establish the actual signing time of a protocol.
Ambiguous/nonexistent local times fail closed; sheet serialization retains seconds.

Local closeout checks (2026-10-13): merged mirror guards/planner 48/48,
Execution API wrappers 12/12, actual merged DailySync coordinator 8/8.
Final targeted Python checks: 140/140 (including status producers, read-model acceptance and incoming
workflow). Complete writer-package checks: 242/242. Append mock execution 8/8;
Clarity/editor/manager dynamic handlers 16/16. Eight precise round-trip scenarios
run independently against each merged environment, preserving seconds and strict gates.
Existing package tests do not certify the new merged cloud-derived packages.
These are targeted results, not a full-suite or Linux gate PASS.
Initial regression failures were investigated before fixture/expectation changes:
date-only values now carry datetime; equal-instant updates no longer move provenance,
alter officers or create business events; final qualification status is required;
pending names/dates are excluded. An exact-base comparison confirmed the former
first-rejected-status expectation passed on the base; its change is contractual,
not classified as baseline-related. Missing data/pqm.sqlite3 was replaced by a
disposable fixture. Windows sandbox cleanup/access errors were separated by a
permitted targeted run outside the sandbox. Protective tests were not removed.

Pending acceptance:
- Actual merged coordinator stale/repeated/partial-chunk checks passed for both
  environments. Eight round-trip scenarios per environment now use merged code,
  retaining conflict, provenance, equal-instant and repeat assertions and full time.
- Append full executor proves PASTE_FORMULA A, absolute/relative references,
  formatting/validation/height, immutable existing identities, and no nonowned values.
  Read-back now compares the full I instant, not its calendar day; one-second
  corruption fails closed. Unsafe preflight creates no partial row.
- Clarity I/L/N/O, explicit manager D approval, editor stale revisions, formulas
  and header aliases passed dynamic tests. Editor whole-row writes retain original
  formulas instead of replacing them with computed values.
- Original rollback archive digests were verified; no cloud rollback was executed.
- DailySync is an existing append/update coordinator, retained rather than blocked.
  It uses ScriptLock and the common planner/request builders. Added append preflight
  and per-chunk source digest checks passed local merged coordinator checks.
- The local Execution API adapter and fourth job are implemented: default OFF,
  daily 07:00 Europe/Kyiv, own schedule/revision/audit/run tables, no catch-up,
  one listener, shared manual/scheduled run lane, unknown outcomes block replay.
  Waiting-loop wakeup/revision, duplicate registration and active-run preservation
  passed offline tests. Live channel setup remains separately authorized work:
  shared standard GCP project, API-executable deployment, dedicated scoped user
  credentials and environment-specific HMAC secret. No channel was installed.
- Existing application status resolver is preserved; no separate signature-fetch
  requirement is imposed. Existing decision datetimes retain time; calendar-only
  values are not represented as evidence of exact electronic signing time.
  Nine read-model acceptance tests passed, including same-day offset ordering,
  pending/rejected admission suppression, actual protocol/qualification decision
  sources, verified EDR names, Active/Suspended parity and officer labels.
- The bounded status producer now runs in the existing framework/contract importer.
  Official source semantics are pinned in STATUS_EVENT_SOURCE.md; no document fetches
  or extra API calls are added. Fourteen offline producer/importer tests passed.
  Explicit causal status timestamps are required; missing/contradictory evidence
  is skipped with a diagnostic, not replaced by generic modification/sync time.
  First historical snapshots and unchanged cached statuses do not backfill events.
  Live payload availability has not been checked and remains runtime acceptance.

SANDBOX historical transfer is quarantined, not redirected to a different dataset.
Controlled sample minimum remains eight rows in SANDBOX and one in PROD.
Google→PQM changes are local in server.py and edr_sync_v2.py: strict instant gate,
typed I grid read (displayed B preserved), decided-only name selection, and separate
last_google_received_at. This additive column is not backfilled from synced_at.
No live migration or database writes have been performed. First three jobs untouched.

Installation must use a reviewed complete project manifest: a partial clasp push
can remove remote files. Installation is not authorized by this local task.
