# Production UI candidate — TZ1–3

Baseline: f2aacf88713a63b2d915d16af137c4133a5f1fd8 (Live SHA confirmed by
read-only SSH on 2026-10-17). Accepted Sandbox source:
0f5f344af81167d0f54350ae46a21aaa72a502d0. This is an addressed port, not a merge
or replacement with the complete Sandbox tree.

## Included

- Accepted compact registry/KPI/filter/column/history/modal/AMCU presentation,
  responsive layouts and cross-module KPI navigation resets.
- Shared text clear controls and existing Prozorro button presentation; no sync
  invoked for visual testing, no new synchronization functionality.
- Officer statistics describe the complete active filtered set, including officer.
- Approved read-only navigation summaries, shared four-condition appeal predicate
  and existing needs-action task statuses; existing permission boundaries.
- Existing audit endpoint: server-side search/user/field/date filtering before
  pagination, exact count, bounded work, per-user/window stale-search cancellation,
  retained 10-second deadline and controlled resource responses.
- Historical protocol presentation from the current generated document and saved
  metadata, not the current assigned officer; existing ASKOD/JSON readiness rules.
- Operational list/detail additive projections and optional basis-date sorting.
  Current qualification activity is separate from captured/receipt-based history.
  Exact linked AMCU resources required; unknown evidence remains explicitly unknown.
- Supplier list multi-DK/multi-framework OR-within/AND-between filters on the same
  framework join before aggregation, existing filters and population preserved.
  Correct filtered totals even when a requested page is empty.
- Four automation cards: Applications / Prozorro, Customer appeals, NAZK registry,
  Google / EDR. Only existing Production status/actions; common layout rules.

## Explicitly excluded / preserved

- No Sandbox automation kill-switch/backends/settings/test data copied.
- No scheduler schedule editor, preview/apply or Google Writer UI/operations.
- Production scheduler/Google execution, Environment, access rules and write APIs
  unchanged. Operational creation/update/closure algorithms unchanged.
- Excel remains the existing Frameworks-tab registry export. No supplier-list
  filtered-export button, calls or filtered XLSX backend branch.
- XLSX exporter, selectors, admission rules, contacts, styles, filenames and
  framework export link helper unchanged. Protected View visibility remains a
  separate unresolved issue, not a data-loss claim or part of this release.
- No TZ5 cold-load experiments, contact-identity experiment, Halloween Edition,
  EDR/datetime/OAuth rewrites, static-502 server/config/cache fixes or other refactor.
- No DB tables/columns/indexes/migrations added or changed; init_db unchanged.
- Known baseline test_response_contract_and_cache_hit is not fixed or counted PASS
  merely because it is known. Any occurrence must be reported separately.

## DB compatibility and test boundary

Production metadata + aggregate-only source inspection used SQLite mode=ro and
query_only=ON, without app imports, migrations or row payload extraction. Required
operational sources/columns exist. Supplier scopes use only existing f.id/dk_code
and existing submission/contract framework joins. New summaries/audit/protocol
presentation consume existing tables/columns already used by Production readers.

Mutation and document-generation tests run only on disposable synthetic DBs, never
live Production/Sandbox storage. Offline Chromium intercepts all network requests
and rejects write/sync actions. New integrity regressions fingerprint protected
server functions, operational lifecycle and unchanged exporter/automation files.
The unchanged CI workflow is separately checked in source audit because the local
test runner intentionally excludes dot-directories from disposable fixtures.

Promotion requires Linux Regression Suite and Docker Release Gate on the exact
candidate commit, not branch HEAD at an arbitrary later time. Preserve GitHub
Actions tested-sha.txt, image ID, build/gate/regression logs and artifact URLs.
The code commit alone is not deployment approval. Windows cleanup failures must
not be presented as passing tests or silently waived for Linux.

## Manual deploy plan — user only, after separate approval

1. Confirm Production still runs the baseline; stop on drift. Verify a current
   consistent recovery point and recent health/jobs/leases. No full repeated audit
   unless a new risk appears. Keep Environment and scheduler settings unchanged.
2. Confirm the exact candidate SHA equals the successful gate's tested-sha.txt,
   its parent/baseline and release file manifest. No merge into main is authorized.
3. User selects pqm-production-1, Manual Deploy / Deploy a specific commit and
   supplies that exact tested SHA. Do not substitute latest/main/another branch.
   Specific-commit deployment may change Auto-Deploy behavior; do not automatically
   alter that setting. No manual migrations, imports, sync or Google writes.
4. Verify Live SHA, HTTP health, startup logs and complete cold-load of CSS/JS
   without F5 bursts. Check applications/history/audit/suppliers/frameworks/appeals/
   tasks, filter/column/KPI navigation, four automation status cards and existing
   Frameworks XLSX download. Check normal automation status without triggering jobs.
5. Scenarios requiring test writes/document generation use only an isolated DB.
   Do not produce test decisions, protocols or Google writes in Production.

## Rollback plan — user only

For a code/UI regression, user manually redeploys the confirmed pre-release SHA
(currently baseline above). No automatic rollback/restart by Codex. No Environment
or scheduler changes. This package adds no schema changes, so code rollback does
not require restoring the DB. Never restore a disk snapshot just for code rollback:
that would discard newer business records. A data incident requires a separate
recovery decision and a verified consistent backup; no destructive restore is
authorized by this document. Assess a short quiet period if active document/write
operations could conflict with restart; do not pause jobs unilaterally.
