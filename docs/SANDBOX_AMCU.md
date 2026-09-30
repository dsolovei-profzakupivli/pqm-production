# Sandbox AMCU manual transport

Default off. `PQM_SANDBOX_AMCU_READ=1` is accepted only with the sandbox
policy and approved Render sandbox identity (or an isolated local fixture).
It permits the existing authenticated POST `/api/amcu-registry/refresh`.
Normal RBAC still applies. Upload, NAZK and registry schedulers are not
enabled by this flag. The independent `PQM_SANDBOX_OPERATIONAL=1` opt-in
permits the shared AMKU task reconciliation on the owned SANDBOX DB.

The download/parser child receives no deployment environment or credentials.
It uses public HTTPS GET only, with official AMCU page/static workbook and
validated data.gov.ua dataset URLs. Redirects and proxies are disabled;
resolved addresses must all be public and are pinned during each request.
Responses are size-bounded, and the parent kills the process group after
300 seconds. The child audit guard rejects database connections and child
processes; this Python guard is defense in depth, not an OS sandbox.

Existing metadata verification, workbook parsing, replacement validation,
atomic transaction, error recovery and UI polling remain in use. After a
successful registry refresh, the shared callback reconciles operational tasks
when the operational opt-in is enabled. Current AMKU membership alone creates
no task: a current effective active qualification requiring exclusion is also
required. A pending application is red/blocked in the application registry and
cannot receive decision "Так", but does not itself create a task. Completed
historical work remains closed until a new active qualification cycle.

Before enabling on Render: sandbox-only fresh backup, container gate,
verified tested commit, then explicit sandbox deployment. Verify one manual
refresh, preserved unrelated data/task counts and terminal UI status.
Never enable this flag on production or infer permission to enable NAZK.
