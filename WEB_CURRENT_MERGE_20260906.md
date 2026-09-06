# CURRENT LOCAL → WEB TEST, 2026-09-06

Source package SHA-256: `8a3e6bc58a78ac8676dc6e2332bce4785b2dd1faf2586bd1c9d1c01922f7ceed`.
Previous deployed commit: `be1245a3c5eff25c87e1b82d753da46ea78788cf`.
Only `pqm-production-1` / `srv-da7vmitg1s2s73fim0p0` is in scope.

CURRENT LOCAL is the business/UI baseline. Preserved WEB seams: login gate and
cookie authentication, managed users/password hashes, custom roles, avatars,
cabinet/presence, richer chat/notifications/read receipts and application sharing.
No LOCAL database, OAuth tokens or credentials are included. Existing runtime
template overrides are not overwritten. New application protocol template is
available as the fourth template.

WEB startup uses `integration/safe_startup.py`, never LOCAL `init_db()` to repair
an existing database. Additive migration must be explicitly reviewed and run in
maintenance before starting the HTTP service and schedulers. Bids, Power BI,
local browser and local role impersonation fail closed in WEB. Existing TEST
Google and Prozorro scheduler configuration remain unchanged.

Additional integration safeguards: application sources/DB files are not served
as static content; completed application rows remain immutable even for admin;
session authorization checks current account status/role and password changes
invalidate the affected cookie sessions. POSIX port reuse permits restart without
allowing two live listeners; Windows retains exclusive binding.

## STOP/GO commands

```
docker build -t pqm-current-gate:20260906 .
docker run --rm pqm-current-gate:20260906 sh -c 'python -m unittest discover -s validation -v && python validation/web_smoke.py && node --check app.js && node --check chat_ui.js'
```

The smoke suite uses only temporary synthetic data and disables all external sync.
It covers authentication/private paths, read APIs/four templates, role and finalized
row enforcement, chat/read receipts/attachments/application links, feature flags,
formed protocol creation/cancel/version history/three data tables, real startup and
restart with saved preferences, and appeal completion followed by two controlled
refreshes preserving its snapshot, CPV and manual justification.

Migration planning, backup hashes, before/after counts and deployment acceptance
reports are kept outside this public code tree. The full user-supplied acceptance
checklist remains the acceptance reference; synthetic tests do not claim a live
external Prozorro or Google refresh was performed.

## Rollback

Re-deploy the previous working commit. Additive schema additions alone do not
require reverting the database. Restore data only for a confirmed data problem
from the verified pre-deploy backup; do not replace WEB data with LOCAL state.
