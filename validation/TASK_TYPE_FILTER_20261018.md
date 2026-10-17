# Operational task type chips: Sandbox-only fix

Parent: 92f38d56012be311162f951261c6966c599c2eba.

Regression introduced in 81f998e: the type-chip handler called
resetOperationalKpiFilters(), which cleared search/officer/date and set status
to active. It also lost second-click deselection. Restore the original additive
toggle from 45ac2dcf76b23651f6e580768c681f76e336b97a. Only one application line
changes; backend, schema, write API, scheduler, Google and kill-switch unchanged.

Coverage: actual JS handler + query builder, 32 type/status combinations,
unchanged search/officer/date/sort/status; deselection and switching type;
authorized HTTP list on schema-only synthetic SQLite with 16→2→16 completed
tasks, all three requested types across six status groups; identical DB dump
before/after reads. Existing UI probes corrected to assert additive behavior.

Read-only live evidence at 2026-10-17 21:13 UTC: Sandbox deployed parent92f38d5,
completed16 / AMCU2; Production deployed121ab87e, completed49 / AMCU16.
Both deployed handlers contain the reset regression. Counts obtained directly
with SQLite mode=ro/query_only and aggregate queries, not live UI interaction.
No application import or runtime write. Production remains unchanged.

Local targeted suite: 3/3 PASS. Existing three Node UI probes PASS.
Offline Chromium actual-handler DOM clicks: 12 combinations (three chips,
light/dark, 100%/125%) PASS; synthetic rendering, not live acceptance.
Full exact-SHA Linux/Docker results are supplied separately with Actions artifacts.

Manual acceptance pending: completed KPI → each type → same KPI/status and
intersection; second click clears only type; search/officer/date preserved.
Rollback: user manually redeploys previous Live SHA92f38d5 after checking no
conflicting operations. No DB restore/migration required by this UI-only diff.
No deployment, merge, restart or runtime changes performed by this package.
