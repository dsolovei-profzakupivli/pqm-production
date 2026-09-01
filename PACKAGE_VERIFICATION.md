# Package verification — 01.09.2026

Source: актуальний LOCAL READY після виправлення eligibility черги НАЗК та останнього UI-виправлення badge джерела керівника.

Package сформовано allowlist-копіюванням. LOCAL SQLite, OAuth client/token, `.env`, passwords/hashes, secrets, logs, backups, cache, generated protocols, ProzorroBids DB, `node_modules`, `__pycache__` і локальні службові скрипти не включено.

Deployment-only hardening: Windows absolute fallback paths замінено platform-neutral defaults; персональний seed/alias list УО вилучено. Чинний довідник УО зберігається у persistent TEST DB; чисте середовище налаштовується адміністратором.

## Перевірено

- LOCAL full suite: `199 tests = OK`.
- Python syntax: OK.
- JavaScript syntax: OK.
- Node EDS adapter syntax: OK.
- Python dependency check: OK.
- Ізольований TEST-runtime smoke на тимчасовій SQLite: health, Basic Auth, authenticated UI/API, JSON 404, runtime feature flags, templates і DB checks — OK.
- Bids, Power BI, Google та schedulers у smoke — disabled.
- Temporary DB: `integrity_check=ok`, `foreign_key_check=0`.
- Security/secrets scan, forbidden artifacts check і manifest coverage — OK.

## Container gate

Docker Engine, Podman і WSL/Linux на цьому ноутбуці відсутні. Реальний Docker image build/container smoke тут не виконувався і залишається обов'язковим STOP/GO gate керівнику до commit/Auto-Deploy. Dockerfile перевіряється статично, а package-level isolated runtime smoke не замінює Docker build.

GitHub і Render не змінювалися. TEST DB із Render не читалася і не копіювалася; її snapshot/backup є обов'язковою pre-deploy дією керівника.
