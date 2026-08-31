# Rollback plan

Before deployment confirm both code rollback and persistent-disk snapshot are available.

## A. Code rollback

Use when container/build/runtime code fails but the TEST DB remains valid.

1. Record current deployed commit and the two latest successful deployments.
2. Keep the old deployment available.
3. Roll back/redeploy the last confirmed working commit in Render.
4. Verify `/api/health`, auth and key UI pages.

Code rollback is the default response to build errors, startup crashes, static asset/API regressions or EDS adapter failures.

## B. Data rollback

Use only when a deployment actually changed/corrupted persistent data and code rollback alone cannot restore operation.

1. Stop writes/schedulers.
2. Preserve the current failed-state DB for diagnosis.
3. Restore the pre-deploy disk snapshot only after confirming the exact target and data-loss window.
4. Re-run SQLite integrity/FK checks and smoke-test.

Do not restore a disk snapshot automatically: it can discard legitimate TEST writes made after the snapshot. The proposed first deployment points to a copied TEST DB, leaving the old DB intact, which usually makes code rollback sufficient.

