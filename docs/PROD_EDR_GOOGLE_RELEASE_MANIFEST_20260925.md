# PROD EDR/Google code-release manifest (review only)

Base: `main` at `320c4603c3bc876c0dfd168c81611eef82947c6c`.
Source: SANDBOX base `9f9313d0bf6cd232374123916bdecc5fbd8a3123`.
This release branch is a **code-only** candidate. It does not authorize deployment,
database migration, Google writes, or Google Apps Script installation.

## Selected Git scope

| Purpose | Source PRs | Included files |
| --- | --- | --- |
| Full registry identity, name, cache | #11, #20, #21 | `supplier_registry_integration.py`, tests |
| Admission, operational/factual EDR, shared UI/API verification projection | #22–25, projection portions of #30–31 | `edr_sync_v2.py`, `server.py`, `supplier_registry_integration.py`, tests |
| EDR multiselect race fix | #33 | `app.js`, `validation/edr_monitoring_filter_state.cjs` |
| PROD routing safeguard | This PR | `server.py`, `test_prod_edr_release_routing.py` |

The historical direct-Google CLI (#26), SANDBOX runtime/theme/config, and all
Google migration audit/Apply modules and route handlers (#27–32, #34–37) are
**excluded** from this permanent release. A later, explicitly reviewed temporary
PROD migration change must port the bounded modules and add authenticated,
PROD-spreadsheet-bound routes. No `PQM_SANDBOX` flag or environment variable
enables these paths in this release: all known migration routes return 404.
The existing full-registry endpoint continues to use
`PQM_SUPPLIER_REGISTRY_TOKEN`, never the SANDBOX token.

The repository schema declarations for `supplier_edr_profiles` and
`supplier_edr_verification_events` are unchanged relative to PROD `main`;
no schema migration is included. Live PROD schema remains a pre-deploy read-only
check because no PROD DB was accessed during preparation.

Required read-model configuration: set `PQM_GOOGLE_REGISTRY_SPREADSHEET_ID`
to the authorized registry spreadsheet ID for each environment (its own
SANDBOX or PROD Google registry). Do not place the ID in code or this manifest.
If this setting is missing or blank, legacy Google factual evidence is ignored
rather than trusted. The future controlled factual-restore input must be bound
to the same authorized ID; this release does not enable that migration route.

## Apps Script inventory and attestation gate

These files are **not included** in this backend PR. Local files are not proof
of the exact code currently installed in the SANDBOX Apps Script project.
Before preparing the separate PROD Apps Script package, export or otherwise
attest the installed project code and compare hashes with these local sources.
Do not install any of them in PROD from this manifest alone.

| Class | SANDBOX source | Proposed PROD filename | Capability | PROD properties / retirement |
| --- | --- | --- | --- | --- |
| PERMANENT | `pqm-sandbox/scripts/pqm-google-writer/PqmGoogleWriter.gs` | `PqmProdGoogleWriter.gs` | Shared schema/snapshot primitives; old generic writer entrypoint must not be used as PROD Apply | Needs approved PROD URL/token contract |
| PERMANENT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs` | `PqmProdPreviewDependencies.gs` | C/E/F/H/I/L planner; Google E `Немає інформації` preservation | Replace SANDBOX constants; retain status vocabulary and formula guards |
| PERMANENT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxPreview.gs` | `PqmProdPreview.gs` | Read-only full-registry Preview | PROD full-registry URL and Bearer Script Property; no copied secret value |
| PERMANENT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxControlledApply.gs` | `PqmProdControlledApply.gs` | Bounded Google pilot writes | PROD spreadsheet ID, fresh Preview digest, explicit operator confirmation; retain read-back |
| PERMANENT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxFullApply.gs` | `PqmProdFullApply.gs` | Chunked Google writer | PROD spreadsheet ID and new Full Preview digest per execution; preserve partial-run stop contract |
| READ-ONLY AUDIT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxExpandedChangeAudit.gs` | `PqmProdExpandedChangeAudit.gs` | Read-only E/F/H/I/L impact | Remove after final acceptance if not needed operationally |
| TEMPORARY MIGRATION | `pqm-sandbox-factual-restore-preview/scripts/pqm-google-writer/PqmSandboxFactualEdrRestorePreview.gs` | `PqmProdFactualEdrRestore.gs` | Google→PQM Preview/Apply | Dedicated PROD token, digest/confirmation properties; remove after factual queue=0 |
| TEMPORARY MIGRATION | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxLegacyVerificationPreview.gs` | `PqmProdLegacyVerificationImport.gs` | Google→PQM I/L Preview/Apply | Dedicated PROD token, digest/confirmation properties; remove after Phase 1=0 |
| TEMPORARY MIGRATION | `pqm-sandbox-factual-restore-preview/scripts/pqm-google-writer/PqmSandboxTerminationNotesImport.gs` | `PqmProdTerminationNotesImport.gs` | Google→PQM G/J/K/M Preview/Apply | Dedicated PROD token, digest/confirmation properties; remove after clean queue=0 |
| READ-ONLY AUDIT | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxFactualEdrAudit.gs`, `pqm-sandbox-factual-restore-preview/scripts/pqm-google-writer/PqmSandboxLegacyVerificationOverlapAudit.gs`, `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxTerminationNotesAudit.gs` | `PqmProdFactualEdrAudit.gs`, `PqmProdLegacyOverlapAudit.gs`, `PqmProdTerminationNotesAudit.gs` | Read-only baseline/verification | Dedicated authenticated PROD read-only routes; remove/disable after acceptance |
| DO NOT DEPLOY | `pqm-sandbox/scripts/pqm-google-writer/PqmSandboxAMarkerControlledTest.gs` and all SANDBOX-only diagnostics | None | SANDBOX experiments | Never copy unchanged |

Script Properties to plan, never copy with values: PROD full-registry URL and
Bearer token (`PQM_FULL_REGISTRY_URL`, `PQM_FULL_REGISTRY_TOKEN` for the generic
writer contract), a separately provisioned PROD migration integration token,
and each migration helper's selection digest and explicit confirmation
properties. Preview tickets must be generated by fresh PROD Preview. The
SANDBOX property `PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN`, SANDBOX URL, and SANDBOX
spreadsheet ID must not appear in installed PROD scripts.

## UI/UX release inventory

The available `docs/PQM_UI_UX_BACKLOG.md` is in the local
`pqm-sandbox-factual-restore-preview` worktree, not in merged SANDBOX Git.
The two explicit entries are filter persistence and EDR→supplier-card access.
Other items below came from the release request, not a tested backlog commit.

| UI item | Implemented / tested | Merged SANDBOX | Data-sync correctness | Release decision |
| --- | --- | --- | --- | --- |
| EDR multiselect state/race | Yes / JS regression | Yes, #33 | Yes: prevents stale table against selected statuses | INCLUDE NOW |
| All factual EDR statuses in display/filter | Dynamic status options and `IN` filtering / Python+JS regressions | Existing UI plus #30–31 projections and #33 | Yes | INCLUDE NOW via projection and #33; no extra UI wish |
| Google note and G/J/K display | Existing UI and monitoring regression | In common PROD/SANDBOX base | Yes once fields import | KEEP existing UI; do not replace |
| UI/API status and date/officer parity | Shared backend projection / Python regressions | #25, #30–31 | Yes | INCLUDE NOW |
| Filter persistence after F5 across registry/table views | No / no | No | No | DEFER |
| Separate supplier-card ↗ action, code still copyable | No / no | No | No | DEFER |
| KPI active-card highlighting across views | Only existing EDR active state; broader consistency unproven | No release-specific PR | No | DEFER broader UX |
| Double vertical scroll | No verified fix | No release-specific PR | No | DEFER |
| Column widths | Existing shared control; no new verified fix | Common base | No | KEEP baseline; DEFER redesign |
| KPI tab consistency/pagination | No verified cross-view fix | No release-specific PR | No | DEFER |
| MedData historical styling/tooltip | No verified fix | No release-specific PR | No | DEFER |
| Protocol/card UI consistency | No verified fix | No release-specific PR | No | DEFER |
| Button widths and other cosmetic requests | No verified fix | No release-specific PR | No | DEFER |

No deferred UI wish is silently added to the PROD data-sync release.

## Remaining gates before merge or any migration

1. Linux container/release gate, not just local synthetic tests.
2. Read-only live PROD schema parity and exact PROD Google/PQM baseline.
3. Installed SANDBOX Apps Script source attestation and separate PROD-adapted
   Apps Script package review, especially E-preserve and blocked clean queue.
4. Separate temporary PROD migration route/auth/spreadsheet-ID change;
   Apply remains absent here.
5. DB and Sheet backups, bounded Preview→Apply→read-back runbook approval.

Known review, not an automatic identity correction: `МЮ397338`, `НВ411323`,
`кн015121`, plus any analogous PROD identities found during baseline.
Same-date I/L provenance completion remains Phase 2.
