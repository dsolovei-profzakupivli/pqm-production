# First isolated PQM sandbox

This release only bootstraps `pqm-sandbox` in **read-only safe mode**. Working
WEB `pqm-production-1` and `main` must not be redeployed as part of this setup.

## Render configuration

- Git branch initially `codex/sandbox-bootstrap-20260916`, manual deployment.
- Frankfurt, 1 CPU / 2 GB RAM ($25/month), own 10 GB disk ($2.50/month).
- Dockerfile/context unchanged: `./Dockerfile` / `.`.
- Pre-deploy command: `python validation/docker_release_gate.py`.
- Docker command: `python sandbox_runtime.py`.
- `/var/data` persistent disk, `/api/health` health path.
- Use `sandbox.env.example`; **do not link production environment groups**.
- Auto-Deploy Off until the CI/release approval process is configured.
- Do not copy OAuth credentials, DB, accounts, chat, attachments or prod storage.

The normal WEB missing-database guard remains unchanged. Only the dedicated
bootstrap, on an empty mounted sandbox disk with matching service identity,
may initialize a DB. Existing unmarked/foreign DBs and partial initializations
fail closed. An ownership marker prevents accidental reuse of a production
backup. Repeated bootstrap does not reset accounts or recreate fixtures.

The first DB contains one synthetic officer, three applications (pending,
admitted, rejected) and three DB-managed accounts: `sandbox.admin`,
`sandbox.officer`, `sandbox.viewer`. All registry/check/task/chat tables start
empty. No builder, registry refresh or reconciliation is called by bootstrap.
Versioned repository templates are copied only when creating the fresh sandbox.

Initial random passwords are never committed or printed. The one-time delivery
file `/var/data/.sandbox-initial-access.json` has mode 0600 and is not served by
HTTP. Retrieve it using authenticated Render SSH into a private local file,
deliver privately, then remove the delivery file after confirmed receipt. Never
log it. Password hashes remain in the sandbox DB. This file is not an environment
account definition and does not reset passwords on restart.

Safe mode blocks edits as well as integration controls. Login/logout still work.
Python outbound sockets/DNS and child processes are denied as defense in depth;
this is not a network firewall. DOCX→PDF is checked by pre-deploy on a synthetic
file outside persistent storage, not by invoking a business action in safe mode.
The current container has no production integration secrets. Network isolation
between Render environments and a controlled editable sandbox mode are separate
follow-up steps, not completed by this first release.

## Acceptance and STOP

1. Container gate GO (includes `validation/sandbox_smoke.py`, existing regression,
   NAZK guards/UI tests and synthetic PDF conversion).
2. Live SHA matches the sandbox branch; working main/service remain unchanged.
3. Health, private API 401 without auth; admin/officer/viewer login works.
4. SANDBOX warning visible before/after login; noindex HTTP header/meta present.
5. Three fixture applications only, no real users/data, empty registries/tasks.
6. Runtime all jobs/integrations off; attempted manual refresh/mutation is denied.
7. Bootstrap/restart preserves passwords and fixtures; integrity/FK checks OK.
8. Stop for user verification. Do not silently enable writes, jobs or auto-deploy.

Compute/disk costs exclude tax, usage and shared Performance build minutes. Do
not increase the workspace's current $100 pipeline spending limit. A new build
uses the existing workspace allowance; stop if that allowance is exhausted.
