# Deploy current PQM to the existing TEST WEB

This package updates the existing Render service **`pqm-production-1`** at `https://pqm-production-1.onrender.com`. It does not create a new service/domain and contains no database or credentials.

## 1. Preconditions and inventory

In Render record before any change:

- service, URL, repository `dsolovei-profzakupivli/pqm-production`, branch `main`;
- current deployed commit SHA, latest and previous successful deployments;
- Auto-Deploy state, Dockerfile path/build context, health path `/api/health`, plan;
- persistent disk size (expected 10 GB), mount path (expected `/var/data`), used/free capacity and newest snapshot;
- all environment **names** with `PRESENT/MISSING`, never copy secret values.

If any expected item differs, stop and reconcile it before deployment.

## 2. GitHub safety gate

Complete `GITHUB_SECURITY_CHECKLIST.md`. Because Auto-Deploy is On Commit, disable it temporarily or prepare a review branch/PR. Verify `SHA256SUMS.txt`; copy only files in this package. Never upload databases, archives, OAuth files, `.env`, logs, cache, generated documents or secrets.

## 3. Data and rollback preparation

1. Create/verify a current Render disk snapshot.
2. Follow `TEST_DATA/README.md`: copy the old TEST SQLite into a **new filename** and validate the copy. Do not overwrite/delete the old DB.
3. Set `PQM_DB_PATH` to the new copy only after checks pass.
4. Confirm code rollback and data rollback per `ROLLBACK.md`.

## 4. Credentials and environment

Rotate old TEST credentials. Generate a strong new password outside Git and set a supported `PQM_USERS_JSON` value as a Render secret. Do not put the value in documentation or shell history. Apply every first-deploy state from `RENDER_ENV_CHECKLIST.md`; in particular disable schedulers, Google, Bids/update, Power BI and browser auto-open.

## 5. Optional container build gate

From the package root on a host with Docker:

```powershell
docker build --pull -t pqm-test-web:20260830 .
docker image inspect pqm-test-web:20260830
```

For an isolated smoke, create an empty disposable directory outside the repository and an env file containing a newly generated TEST credential. Never mount LOCAL PQM or ProzorroBids DB.

```powershell
New-Item -ItemType Directory -Force C:\Temp\pqm-container-smoke | Out-Null
docker run --rm --name pqm-test-web-smoke -p 10000:10000 --env-file C:\Temp\pqm-test-web.env -v C:\Temp\pqm-container-smoke:/var/data pqm-test-web:20260830
```

Required env-file states are listed in `RENDER_ENV_CHECKLIST.md`. From another terminal verify:

```powershell
curl.exe -i http://127.0.0.1:10000/api/health
curl.exe -i http://127.0.0.1:10000/api/applications?page=1&size=1
curl.exe -i -u "manager:<NEW_TEST_PASSWORD>" "http://127.0.0.1:10000/api/applications?page=1&size=1"
curl.exe -i -u "manager:<NEW_TEST_PASSWORD>" "http://127.0.0.1:10000/api/framework-analytics?page=1&size=1"
```

Expect health 200 without auth, protected API 401 JSON without auth, 200 with auth, and controlled JSON for disabled Bids/Power BI. Delete the disposable env file after the test.

## 6. Upload and deploy

1. Copy the verified package files into a clean checkout/review branch of the existing repository.
2. Re-run secret scan and inspect `git diff --stat` plus `git diff --cached`.
3. Commit to the review branch and review it. Do not include `SHA256SUMS.txt` if repository policy excludes transfer manifests; otherwise it is safe documentation.
4. Merge/push to `main` only when Render inventory, DB copy, snapshot, env, rollback and security gates are confirmed.
5. Observe Docker build: Python 3.12, Node/npm, pnpm 9, LibreOffice, Poppler, Tesseract Ukrainian, Python requirements and pinned `@prozorro/prozorro-eds@1.1.2` must install.
6. Watch startup logs without exposing secret values.

## 7. Acceptance

Complete `POST_DEPLOY_SMOKE_CHECKLIST.md`. Also test one DOCX generation and one EDS request on approved TEST data. EDS outbound/service failure must be controlled and must not crash the app. Google and Bids remain disabled for this first deployment.

Deployment succeeds only if health/auth/API/UI/manual persistence/DOCX checks pass, no hidden sync starts, and old deployment plus DB snapshot remain recoverable. If not, stop and follow `ROLLBACK.md`.

