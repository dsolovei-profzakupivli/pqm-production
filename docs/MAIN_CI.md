# Main release checks

Pull requests run `Container release gate`: build the current Dockerfile, run
the production release gate including PDF conversion, AMCU polling, OAuth callback
regressions, and the delivered regression suite. Tests run on disposable fixtures
in containers with no network, no mounted storage, and no deployment credentials.

Runs have a 35-minute limit. Logs, tested SHA and CI image ID are retained for
14 days. PR checks test GitHub's merge revision. Recheck the final release SHA
before deployment acceptance if it differs; tree parity alone is not runtime
acceptance. CI does not deploy either Render service.

Main requires PRs with a successful, up-to-date `Container release gate`. Rules
also apply to administrators. No independent approval is required while there
is only one maintainer. Force pushes and branch deletion are disabled.

Before a production release: record the exact SHA accepted in sandbox, verify
backup/rollback, run migrations twice on a private copy of current production
data, compare fingerprints/integrity, obtain deployment approval and run final
health/permissions/browser checks. Real databases and secrets are not CI inputs.
Keep Render Auto-Deploy Off. CI success does not authorize business-data
migrations, registry refresh, NAZK reconciliation or production deployment.

Do not merge the sandbox bootstrap branch wholesale into main; compare application
changes and environment policy explicitly. Google uses separate sandbox credentials.
