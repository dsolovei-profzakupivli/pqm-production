# UI improvements: sandbox-first acceptance

Baseline: `45ac2dcf76b23651f6e580768c681f76e336b97a`.
No deployment, restart, rollback, runtime test writes, sync, importer or Google
writes are performed by the preparation tools.

## Package

1. Applications: compact officer row above the four requested general KPI cards;
   existing counts, enabled/active states and filters are preserved. Other KPI
   definitions and saved settings are retained, not deleted. Short action labels
   retain the existing IDs, handlers, permissions and confirmations.
2. Framework registry: scoped 13px body / 11.5px headers, full UA-F number copy
   beside the unchanged Prozorro link. Technical identifiers are not copied.
3. Unified field-local clear buttons: supplier universal name/code search,
   framework search, nine history text filters, AMCU search. The supplier registry
   currently has one shared name/code field, not a second independent code input.
   Clears emit the existing input event; other filter values are retained.
4. AMCU toolbar: compact wrapping flex layout, one row when width permits.
5. Supplier-card participation/win KPI are hidden by default. Returning them
   requires explicit `PQM_SUPPLIER_BIDS_READY=1` AND a non-disabled Bids mode;
   this package does not set the flag or initiate Bids synchronization.
6. Operational navigation count: statuses from
   `operational_tasks.STATUS_GROUPS['needs_action']`, not unread messages.
7. Appeals navigation count / expired quick filter: same predicate, official
   supplier response deadline only, pending official status, review not completed.
   Missing/invalid deadlines are not counted. Canonical
   `violation_deadline_control` decides expiry; date-only deadlines include the
   entire date, timestamp offsets are respected, calculations use Europe/Kyiv.
8. Layout: existing sandbox initialization/race protection is retained. Saved
   table widths are reapplied after container resize and font readiness. Existing
   static responses already send no-store; cached resources are not established
   as the cause of the reported production F5 issue. Production live reproduction
   has not been performed; sandbox acceptance must verify first-open behavior.

## API / security

Approved additions: GET `/api/operational-tasks/summary` (`tasks.read`) and
GET `/api/violation-reports/summary` (`appeals.read`). Existing route permission
patterns cover both. Each returns count and calculation time, with no-store.
Connections use SQLite mode=ro and query_only; no task builders or detail refresh.
Appeals list adds `response_expired=1` using the identical predicate.
No tables, migrations, startup changes, scheduler settings or business rules.

Counts refresh after authentication, on focus/navigation/visibility and at most
one non-overlapping 60-second interval while the page is visible. Viewing does
not decrement counts. Failed/unauthorized reads hide the badge rather than
asserting a zero count. Existing module-wide visibility remains unchanged.

## Acceptance / rollback

Use synthetic fixtures for mutations and isolated settings persistence tests.
Verify both themes at 1920/1440/768/390px, field-local clears, copy, deadlines,
RBAC, navigation and async table updates. Never click real refresh/sync buttons.
Manual sandbox deploy requires separate user approval and the permanent
`PQM_DISABLE_BACKGROUND_JOBS=1` environment flag. Only the user performs deploy.
Code rollback is to the exact baseline above; it retains the kill-switch and
accepted bulk behavior. No database restore is required for this UI-only schema
delta (there is none). Do not restore disk snapshots merely to roll code back.

Production promotion is a separate candidate on its actual deployed baseline,
only after sandbox acceptance; do not transfer sandbox configuration or data.
