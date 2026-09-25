# Temporary PROD Google ↔ PQM baseline (read-only)

This package does **not** enable migration or Apply routes. It does not read
Google on Render. The Apps Script candidate reads the current PROD spreadsheet
and POSTs batches of at most 500 rows to the authenticated comparator.

1. Review and attest the Apps Script candidate against the installed project.
   Enable the Advanced Google Sheets service (`Sheets`, v4). Configure Script
   Properties `PQM_PROD_GOOGLE_BASELINE_URL` (the exact PROD HTTPS audit URL),
   `PQM_PROD_GOOGLE_BASELINE_TOKEN` (the existing PROD full-registry integration
   Bearer credential), and `PQM_PROD_GOOGLE_REGISTRY_SPREADSHEET_ID` (the current
   PROD registry). Do not put values in source control. Verify the allowed host.
2. Configure backend `PQM_GOOGLE_REGISTRY_SPREADSHEET_ID` to the same authorized
   PROD spreadsheet (already required by the factual projection). Only for the
   bounded audit window, set `PQM_PROD_GOOGLE_BASELINE_ENABLED=1`. Default is off.
3. Run `pqmProdGoogleBaselineAudit()` in the PROD-bound spreadsheet project.
   It returns/logs aggregates only. An error means the aggregate is incomplete;
   do not treat it as a baseline. No Apply function is in this candidate.
4. Save the aggregate and disable the endpoint by removing or setting
   `PQM_PROD_GOOGLE_BASELINE_ENABLED=0`. Keep it off after the baseline unless
   a separate approval explicitly extends the audit window.

Security: the route accepts POST only with the existing integration Bearer token,
an exact authorized spreadsheet ID and source digest. Body <=1 MiB and records
per request <=500. It opens SQLite with `mode=ro` and `PRAGMA query_only=ON`.
It returns no supplier codes, names, officer names or G/K/M text; DB and Google
writes are zero. Existing migration routes remain 404.

The summary merges per-batch counters. The Apps Script first scans both tabs
to mark duplicate literal identities across batches. Existing same-date
provenance completion is reported but excluded from Phase 1; Phase 1 includes
only newer or initial I/L pairs. G/J/K/M counts are comparisons, not an Apply
plan. Google E `Немає інформації` is a status bucket, not factual evidence.
