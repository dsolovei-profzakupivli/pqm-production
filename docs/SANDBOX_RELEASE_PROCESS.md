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
