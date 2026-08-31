# Local deployment-package audit

## Deployment context

- Runtime source, static assets, Docker layer, Python requirements, pinned EDS adapter, OCR resource and approved DOCX templates are present.
- Docker defaults target Python 3.12/Linux, `HOST=0.0.0.0`, port 10000 and persistent `/var/data`.
- Schedulers, browser, Google, Bids/update and Power BI default to disabled in the image.
- Package was assembled by explicit allowlist rather than copying the whole project.

## Security result

- No SQLite/DB, `.env`, credential/token JSON, private key, archive, log, backup, generated protocol, cache, `node_modules`, temp or Git metadata is included.
- Text scan found no embedded credential value. The only password-related code hit is Basic Auth parsing in `server.py`, not a stored password.
- DOCX files are approved templates, not generated case documents.
- Working LOCAL DB and full ProzorroBids DB are explicitly excluded.

## Local gates

- Docker engine: **not available on this machine**; no installation attempted.
- Container build/smoke must be performed by the manager or CI using `DEPLOY_FOR_MANAGER.md`.
- Earlier Task 1 gates for the unchanged runtime: full suite 156 OK, runtime 5/5, violation reports 30/30, SQLite integrity `ok`, foreign keys 0, isolated TEST_WEB runtime smoke passed.
- This packaging task changes no runtime code or database.

## Feature state for first TEST deploy

- Bids: disabled, full ~31.9 GB database excluded.
- Google: disabled, no OAuth material included.
- Power BI/Bids updater/schedulers/browser: disabled.
- Basic Auth: required with rotated manager-supplied credentials.
- EDS: adapter and pinned `@prozorro/prozorro-eds@1.1.2` included; outbound HTTPS must be checked during container/Render smoke. `issuerCN` is not proof of qualified certificate status.

## Package decision

**READY FOR MANAGER**, subject to manager-only GitHub security scan, Render inventory, snapshot/TEST-DB copy, credential rotation, Docker build and post-deploy smoke. No deployment or push has been performed.

