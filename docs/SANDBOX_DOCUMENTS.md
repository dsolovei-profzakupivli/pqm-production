# Sandbox document stage

`PQM_SANDBOX_DOCUMENTS=1` is optional and defaults to disabled. It is accepted
only by the existing owned sandbox service or a disposable local fixture.
Safe mode, authentication, effective permissions, final/historical locks and
all existing integration/scheduler guards remain unchanged.

This first stage allows POST `/api/protocol/readiness` and `/api/protocol/generate`.
Existing download/read routes remain subject to their normal permissions.
It does not allow cancellation, template replacement, violation review/generation,
NAZK outcomes, reconciliation, registry refresh or task creation.

PDF export of an existing generated violation protocol uses a dedicated Linux
worker and an empty-of-secrets environment. Before launching LibreOffice the
worker installs an inherited seccomp filter: only AF_UNIX socket creation is
allowed, and io_uring setup is denied. Missing library or filter support fails
closed. There is no generic subprocess allowance. Conversion has a timeout and
kills its process group on timeout; each conversion has an isolated LO profile.
Source/output paths must be within the sandbox protocols directory.

This is network confinement, not a filesystem or hostile-document sandbox.
Do not enable arbitrary untrusted document uploads as part of this option.

Acceptance: `validation/sandbox_documents_smoke.py` is in the container gate.
The Linux test uses the actual runtime guard and PDF worker, verifies denied
Internet sockets, preserved source DOCX, cached-PDF flag guard and path scope.
HTTP fixtures verify generation, viewer denial and no operational/NAZK tasks.

Rollout: fresh sandbox backup → successful protected PR CI → sandbox-only exact
SHA deploy → enable the flag only in sandbox → read-only runtime verification.
No automatic generation of documents against copied business records is needed.
Rollback: disable the flag; keep already generated files and metadata intact.
