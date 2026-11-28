# V31.1 targeted acceptance plan

## Apply-scoped NAZK reads

The first actual EDR manager-change callback lazily creates one request-local `EDRManagerReconcileContext` inside the existing EDR callback identity boundary. It loads shared active-application, supplier-name/count, NAZK registry, and current-task inputs once for the Apply. It is discarded with the callback closure; there is no module/global cache.

After each manager change, the callback reads the current manager and that supplier's checks, evaluates against the shared registry snapshot, performs the existing check/task rules in the caller's transaction, then refreshes that supplier's task snapshot. This preserves visibility of earlier callbacks within the transaction and avoids stale manager/check/task state. Other NAZK callers continue using their existing non-context paths.

## Acceptance criteria

1. With real manager, control-refresh, NAZK reconciliation, and task-materialization callbacks, test 1, 4, 50, and 100 changed managers against a 10,000-row synthetic NAZK register.
2. Each shared full read (active-application map, active supplier counts, NAZK registry, active NAZK tasks) occurs once per Apply, independent of changed-manager count. Supplier-specific task refreshes may scale with the number of changed suppliers.
3. Check/task results for each supplier match the existing rules; later callbacks observe earlier writes. A forced exception after a callback leaves the caller transaction fully rollbackable.
4. Google → PQM omits A/F/H from comparisons, business-plan values, field decisions, XLSX inputs, counters, state digest, and writes. PQM → Google is not changed.
5. Repeat relevant V31.1, NAZK workflow/task, routing, infrastructure, and browser/HTTP checks that can run in the authorized local environment. Report blocked checks as BLOCKED, never PASS.

## Docker packaging review

Do not change the Docker build architecture or remove test bridge/fixture/archive files required by the image's pre-deploy command. Measure their exact packaged bytes, determine whether the deployed HTTP surface can retrieve them, and confirm they are not imported or invoked by normal `server.py` runtime. If runtime isolation cannot be established, report NO-GO rather than deleting files.

For local phases, set `PQM_V311_TEMP_ROOT` to a pre-created external protected directory. The bridge rejects a root inside, above, or equal to the source tree. CI may continue using the ephemeral runner's system temporary directory.

The version-routed historical harness may expose missing columns from the
current additive schema as `NULL` in temporary views over explicit in-memory
legacy fixtures. It does not modify historical assertions, source tables,
on-disk databases, or runtime code.
