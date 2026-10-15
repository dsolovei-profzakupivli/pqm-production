# PQM: sandbox → production

## CI scope

`PQM release checks` builds the repository Dockerfile and runs the existing
release gate, AMCU polling regression and delivered regression suite on disposable
fixtures. Runtime test containers have `--network none`, no host volumes and no
deployment credentials. The build needs network access for package installation.
Artifacts contain the tested SHA, local image ID and test output; retention is 14 days.
The image ID identifies this CI build, not a published/promotable registry digest.

The workflow runs on PR updates or explicit dispatch. There is no push trigger,
Render deploy hook, production secret, production database upload or automatic deploy.
Canceling superseded checks limits duplicate runner usage. Each run is capped at
35 minutes, excluding any platform queue time. Actual charges depend on GitHub quotas.

## Release sequence

1. Start a feature branch from the current intended release baseline. Review both
   `main` and sandbox history before merging: sandbox-specific bootstrap/configuration
   must remain conditional, and newer production fixes must not be lost.
2. Open a PR and require a successful `Container release gate` result. A PR run
   tests GitHub's merge revision. It does not prove that a later merge/rebase SHA
   passed. Run checks against the final candidate revision before release acceptance.
3. Capture a fresh native SQLite backup and required persistent files for the
   target environment. Record hashes, exact schema/configuration and rollback plan.
   Run migrations twice on a private disposable copy of its actual database;
   compare business fingerprints, counts, integrity and foreign keys. This check
   is separate from public/shared CI fixtures; no real database is uploaded to CI.
4. Deploy the exact candidate SHA to `pqm-sandbox` and record the Render deploy ID.
   Verify runtime SHA after deployment. Preserve sandbox credentials and isolation.
5. Complete browser acceptance: admin/officer/viewer access, historical read-only
   selection and Chat, changed modules, templates/PDF and intended synchronization.
   Record job schedule/timezone/last/next run. Unrelated refresh/reconciliation is
   not part of release smoke. Freeze the candidate during acceptance.
6. Present the completed acceptance record for production approval. Before the
   production deployment repeat target-specific backup and migration-on-copy
   checks against the latest production data. Deploy only the approved SHA.
7. Verify production health, SHA, schema, permissions and relevant browser smoke.
   Keep the previous release and backup references. Code rollback does not roll
   back data; database restore requires a separate decision about intervening writes.

## Environment settings

- Sandbox service: `pqm-sandbox` (`srv-dalfd77f3r2c7392uub0`).
- Production service: `pqm-production-1` (`srv-da7vmitg1s2s73fim0p0`).
- Keep both deployments manual until explicit deployment automation is reviewed.
- Google requires its own sandbox client, token storage and destination.
- Sandbox data and credentials are never promoted into production.
- Sandbox 1 CPU / 2 GB is not a production performance benchmark (2 CPU / 4 GB).
- Branch protection availability and required-check settings must be verified on
  the actual GitHub plan. A workflow file alone does not enforce merge protection.

## Permanent sandbox background job interlock

Keep `PQM_DISABLE_BACKGROUND_JOBS=1` in the sandbox service configuration across
all updates. `background_jobs.disabled()` is the shared execution interlock:
it is evaluated at startup and before subsequent automatic dispatches, not stored
in SQLite. Persisted enabled overrides and `catch_up=True` cannot bypass it.
Do not change `PQM_SANDBOX=1`, environment identity, saved schedules, enabled
settings or revision numbers to obtain this protection. Production behavior is
unchanged when the variable is absent; do not change production configuration.

The interlock blocks jobs 1–3, their startup catch-up and lease acquisition, the
Google writer scheduler/claim/execution channel, deferred reference refreshes,
automatic Bids status refresh, contract-experience queue/retries and Power BI
background export. The startup operational-task rebuild is also skipped. Manual
starts through the same sync entrypoints are blocked. Explicit HTTP document
checks and other manual application edits are not an automatic scheduler bypass
and are not disabled by this interlock; deploy smoke must remain read-only.
This is not an outbound firewall, read-only database mode or cancellation of work
already running before activation. Keep the Google job configured OFF and retain
Google authorization, destination and environment guards independently.

### Standard sandbox update procedure

1. With separate approval for configuration changes, install the persistent
   sandbox-only `PQM_DISABLE_BACKGROUND_JOBS=1` setting. Retain it on every
   restart, deployment and rollback. Saving configuration may restart the service;
   treat that as a deployment requiring its own preflight and approval.
2. Immediately before each deploy, verify live service identity, current SHA,
   resolved sandbox DB path and isolation attestation, health, runtime errors,
   recorded running jobs/leases, recovery point availability and rollback SHA.
   STOP for active critical work, unknown isolation or unverified configuration.
3. Verify the exact candidate includes this interlock and has passed its
   regressions, the full container suite and Docker Release Gate. A rollback to
   older code without this interlock does not become safe merely because the
   environment variable exists; STOP and prepare a separately approved safe
   rollback procedure in that case.
4. Review startup initialization and migration effects against the actual schema
   on a private disposable DB copy. The interlock does not skip schema setup,
   reference-date normalization or other ordinary startup database initialization.
   STOP for unapproved destructive or unexpected changes. Do not run manual
   migrations, historical backfill, imports or sync as part of deployment.
5. After explicit deploy approval, deploy only the exact tested SHA. Verify the
   runtime still has `PQM_DISABLE_BACKGROUND_JOBS=1`, the expected SHA and DB
   identity, healthy startup, no registered schedulers/automatic executions,
   jobs 1–3 effectively blocked and Google job OFF. Confirm saved schedules,
   revision 2 and the requests minute `:50` remain unchanged; perform read-only
   UI acceptance. Do not press sync, Preview or Apply.

### Separately approved scheduler testing

Test scheduler behavior without changing code or adding bypass flags. Prefer the
offline regression fixtures or a separate disposable sandbox instance/database
with isolated destinations, credentials and network restrictions. Only after
separate approval, use `PQM_DISABLE_BACKGROUND_JOBS=0` in that test process and
explicitly control its schedule, clock and jobs. Saved enabled settings and
startup catch-up become effective again when the switch is off; this is not a
safe way to enable just one job in the shared sandbox service. Keep Google OFF
unless separately authorized. After testing, restore the persistent value `1`,
restart under approval and repeat the no-jobs/leases check. No scheduler test or
configuration change is authorized by the presence of this runbook.

Future changes must retain `test_background_jobs_kill_switch.py` in the normal
regression suite, covering persisted overrides, repeated startup, catch-up,
lease/Google guards, no settings writes and unchanged behavior with the flag off.

## Release acceptance record

Copy this section for each candidate and fill every item before production approval:

| Evidence | Value |
| --- | --- |
| Candidate full SHA and baseline | pending |
| PR and successful final-SHA CI run | pending |
| Sandbox Render deployment and runtime SHA | pending |
| Backup locations, hashes, verification | pending |
| First/repeat migrations, fingerprints, integrity/FK | pending |
| Browser roles/history/chat/module checks | pending |
| Templates hash/parity and PDF fixture | pending |
| Intended jobs enabled/schedule/timezone/last/next | pending |
| Known limitations and unrelated features disabled | pending |
| Rollback code SHA and database recovery decision | pending |
| Explicit production approval of this SHA | pending |
| Production deployment and post-deploy verification | pending |
