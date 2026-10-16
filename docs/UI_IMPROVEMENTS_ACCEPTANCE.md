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

## Consolidated sandbox UI follow-up (2026-10-16)

Parent / manual rollback: `fc31efbbf817da84e1418fce13d9d4d7e0b29b62`.
The fresh metadata-only sandbox check confirmed that Live SHA and the enabled
background-jobs kill-switch. No runtime database was opened for that check.

- Applications: selected KPI stay in one horizontal strip; dynamic officers
  remain the single `officers` preference group. No individual officer keys.
  Actions occupy two compact rows, independent of KPI scrolling.
- Work Queue: content-sized KPI, officer, category and publication cards retain
  their original heights, text sizes, callbacks and counts.
- Frameworks: copy full UA-F number, aligned to the cell right edge. Existing
  export and personal table widths are untouched.
- Supplier Registry: no visible XLSX action here (Frameworks export remains).
  Universal CPV search checks related qualifications/memberships before paging.
  Existing read endpoint accepts repeated or comma-separated string CPV codes;
  selected codes/framework IDs use OR internally and AND between groups. CPV,
  framework and status are scoped together before supplier aggregation.
  Dropdown searches do not discard checked values. No schema or write API.
- External Work Queue KPI navigation replaces old application filters and clears
  selection snapshots/revision before applying the card's compound conditions.
  A late select-all response is rejected even if selection was previously empty.
  Local application KPI and manual filter combination are unchanged.
- History: first row contains search/code/supplier/CPV/framework/contract/manager/
  officer; second row has wide remarks, dates, compact status and `Очистити`.
  Text-field clears and existing filter handlers remain. Narrow screens wrap.
  Both themes must have the same compact row geometry (no stretched dark rows).

Offline checks: `validation/application_header_browser.cjs`,
`validation/consolidated_ui_browser.cjs`, `validation/ui_improvements_browser.cjs`,
`validation/external_kpi_filters.cjs`, plus Python regression suites.
Browser fixtures block outbound requests; profile/selection tests use synthetic
state only. Do not exercise live refresh, importer or sync for UI acceptance.
The final exact SHA still requires Linux regression and Docker gate evidence.
No deploy, restart, rollback, production or Google operation is performed here.
