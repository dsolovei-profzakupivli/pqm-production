# PROD writer contract promotion candidate

Local preparation only. Source base: ec1147a26bdbe264e65cd31d8960e8980a1872af, pending fresh runtime SHA confirmation. Reuses the accepted 12a0da213982d447003e3209577f76a66eda41f7 SANDBOX contract implementation. No backend, schema, scheduler, ClarityChecker or Google-to-PQM changes.

Install package (NOT installed): the seven PqmProd*.gs files in this directory only. Do not combine its shared pqmGoogle* definitions with legacy PROD/SANDBOX dependency files. Inventory/export the actual installed project before replacement; preserve that export and trigger/deployment configuration as rollback evidence. Installed cloud revision and Apps Script compatibility remain NOT_VERIFIED.

Existing rows: strict whole-row PQM verification_date > Google I. Equal/older/blank PQM dates skip, invalid dates or blank/invalid Google dates block. Blank incoming fields do not clear populated cells. D receives ready current_manager_name only. No invented officer; valid verification date without officer conflicts.

Owned value columns: B/C/D/F/H/I/L. E is frozen in the planner and rejected by all request builders, for both existing rows and append, regardless of special E status. A is never overwritten on existing rows. Append separately carries only A formula with relative/absolute references, format, validation and row height; never template manual values. Unsafe/missing A formula fails before batch submission. New-row E remains unfilled; existing E values/formulas remain unchanged. Other formula columns are not newly approved.

Destination guard intentionally defaults to an empty PQM_PROD_CONTROLLED_SPREADSHEET_ID and fails closed. Configure only after exact PROD spreadsheet identity, installed scripts and rollback are reviewed and installation is separately approved. API host is pinned to pqm-production-1.onrender.com; token property name is PQM_PROD_SUPPLIER_REGISTRY_TOKEN. Never export property values or tokens into evidence.

Retained safety: shared planner, fresh source/sheet digests, ScriptLock, formula conflicts, bounded chunks, before/after readback, unknown/partial outcome reporting, repeated/stale Apply guards. Full Apply is not atomic. No automatic trigger is created by these files.

Targeted command: node --test scripts/pqm-google-writer/prod-contract/*.test.cjs
Gate plan (separate approval): confirm actual PROD SHA, finalize snapshot/hashes, scoped commit and separate verification workflow with explicit checkout and Git blob checks; network-none disposable containers, new targeted tests plus all existing writer tests and full PROD regression suite. No cloud Preview/Apply, secrets, volumes or deployment during gate.

Next cloud step: reviewed bounded Preview only, then separate rollout approvals for manual Google-to-PQM and PQM-to-Google. E stays frozen until mapping receives a separate explicit approval. No ledger backfill from counts alone.

Runtime evidence: copy runtime-readonly.sh into PROD Render Shell, without importing server.py or running Google helpers that may initialize tables. Exact profile/event timestamp matching is a bounded diagnostic, not proof of all historical coverage or authority to backfill. Current deployed SHA must be confirmed before calling this the actual PROD base.

Cloud manual evidence: open the actual spreadsheet's Extensions / Apps Script; export the saved source files and appsscript.json without Script Properties values, record Project History and any deployment version, list existing triggers and latest execution results without changing them. Bound menu/trigger handlers can run saved HEAD rather than a deployment version. Preserve the export plus trigger/deployment inventory for rollback; do not install scripts or create triggers now. Existing manager confirmation and ClarityChecker scripts must remain unchanged.

Local test closeout: new PROD regressions 36/36 PASS; unchanged existing writer tests on PROD base 113/113 PASS. The separately accepted SANDBOX candidate's 151/151 result is retained evidence, not relabelled as this candidate's Linux gate. No tests were deleted from the existing suite. No Google/PQM runtime writes, Preview endpoint calls or Apply occurred. Cloud installation and full exact-SHA gate are still pending.

E freeze also excludes its template format/validation copy ranges during append. Other columns retain those template properties. Whole-row height and conditional-format range extension retain the existing implementation; neither supplies or clears an E value.
