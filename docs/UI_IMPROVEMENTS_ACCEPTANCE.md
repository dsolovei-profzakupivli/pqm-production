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

## Final consolidated contract (17 October 2026; supersedes older layout notes)

Verified sandbox baseline: `7f7eff195d1424f0a0e379e8ac81016c89c54a47`.
The 17 October metadata-only runtime check confirmed that exact Live SHA and
the active background-jobs kill-switch, without opening the runtime database.

Read-model changes:
- Protocol-officer KPI use the entire current application predicate, including
  the active officer, not a page or the review-officer field. No source/ranking
  or protocol business rules are changed.
- Existing GET `/api/audit` accepts `search`, exact `user` and `field`, and
  `date_from`/`date_to` calendar bounds in Europe/Kyiv. Filtering/COUNT precede
  LIMIT/OFFSET. Default page/size and response contract remain compatible.
  Connections are mode=ro/query_only, parameterized, with a 10-second work limit.
  No schema, index, migration or task builder. Benchmark uses 450001 synthetic
  rows; an individual query exceeding 5 seconds fails the performance test and
  requires a separate design/index approval rather than adding an index.
- Expired-appeal list and navigation counter share administrator code 40996564,
  the existing official-deadline predicate and unfinished-review requirement.
- Supplier universal search additionally matches linked framework UA-F/title.

UI changes:
- Work Queue shows two qualification panels only; detailed task UI/API remain
  present but hidden. Comfortable equal card widths adapt/wrap without inner
  horizontal scrolling; fonts, heights, values and handlers are retained.
- Application information totals are not filters; officer/decision/status groups
  remain independent. Operational-task KPI clicks start a fresh filter scope.
- Search clears cover static/dynamic text searches and multi-select/modal search,
  not dates, numbers or ordinary editing. Reset is square ×, refresh is ↻ Prozorro.
- History keeps two filter rows, full status text and banner-safe pagination.
- Existing viewport dragging is installed on native dialog headers, including
  dynamically generated column settings. Save handlers/dimensions are untouched.
  Only the read-only audit window becomes non-modal and closes on module-nav
  clicks. Editable modal forms are not auto-closed or interrupted on navigation;
  existing unsaved-change/save guards remain authoritative.
- Existing runtime-status and schedule controls share four cards. The original
  delegated preview/apply/toggle handlers, disabled rules and Google run log are
  retained. Only labels and DOM placement change; tests never invoke live actions.

Acceptance: `validation/ui_final_browser.cjs` (both themes, 1280/1440/1680/1920,
100%/125%, cards 1/2/3/4/5/7, audit/drag/search/4-card layout) plus the retained
header/framework/AMCU/browser and bulk/CAS/Excel regressions. Synthetic adapters
reject writes and outbound requests. Live acceptance remains a user step.

Manual sandbox deploy/rollback (user only): confirm the candidate exact SHA and
saved `PQM_DISABLE_BACKGROUND_JOBS=1`; in `pqm-sandbox` choose Manual Deploy →
Deploy a specific commit and enter the tested candidate SHA. Do not deploy branch
HEAD implicitly or change Auto-Deploy. After success check Live SHA/health,
startup errors, automation blocked and the UI checklist without sync/import/jobs.
Use isolated data for settings/save scenarios. For code rollback, manually deploy
the exact baseline above, keeping the kill-switch; no DB restore/migration is
needed for this schema-free package. Production promotion remains separate.

# TZ № 2 — 17 October 2026, sandbox candidate only

Baseline: `f80796bfaddff1bfba26f168b2c3d327512624de`.

- Audit: retain the 10-second SQLite deadline. Parameterized matching is evaluated once per source row; materialize IDs only, then derive exact total and the requested page in the same read-only snapshot. No indexes/schema changes. Cancellation is scoped to authenticated username plus random browser-window ID, never a global user lock. Newer sequences cancel older searches; late stale requests cannot restart. Resource exhaustion/SQLite busy returns controlled 503; superseded requests return 409, not an unhandled 500. The UI clears stale rows immediately, keeps one active search plus the latest pending query, and reports errors inline without repeated toasts.
- Protocol column: replace only Decision/Documents with Protocol decision. Batch-read existing review records without detail refresh/network. Resolve the current document from `generated_protocol_filename`; obtain the historic officer from the standalone signature paragraph in that exact DOCX. Never use the current assignment as a historical author. Missing/ambiguous signatures remain undisplayed. Read the existing `protocol_subject` metadata for ASKOD, without inventing a format. Use the existing JSON eligibility predicate independently of generation, including the existing official-decision projection. No generator changes or historical rewrites.
- Search clears stay field-local, including history's accepted two rows and inner multiselect search. Programmatic navigation restoration is reflected without F5. Framework dropdown expands leftward, wraps full labels, retains vertical scrolling and existing selections. The CPV panel is unchanged.
- Restore pink navigation badges after navigation re-render in icon and icon/text modes. The appeals count/list use the unchanged shared predicate: authority `40996564` AND pending AND canonical expired supplier deadline AND no reviewed/completed review/completed_at. Tasks retain their canonical needs-action statuses. Clicking the appeals tab/badge does not add or clear filters.
- AMCU changes are scoped to toolbar proportions, not its data or update paths. Audit has a wider framed/dimmed surface, bounded dragging and a three-line value preview with read-only full-text comparison/copy. Other modal layout/behavior remains intact; only the shared frame/shadow is adjusted.

Acceptance uses synthetic SQLite/DOCX fixtures and offline browser adapters. No live data is modified. Previously accepted applications, automation controls, frameworks and XLSX business logic must retain their regression coverage.

Manual deployment/rollback is exclusively the user's action. After separate approval deploy the exact tested SHA only to pqm-sandbox, keeping `PQM_DISABLE_BACKGROUND_JOBS=1`. Rollback target is the baseline above, with Environment preserved; no DB restore/migrations are required by this package. No production, scheduler, Google execution or kill-switch changes are authorized.
