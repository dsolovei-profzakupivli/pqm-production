# Render environment checklist

Не копіювати значення секретів у цей документ. Для секретів фіксувати тільки `PRESENT/MISSING`.

| ENV name | Required | First deployment | Secret | Notes |
|---|---:|---|---:|---|
| `PQM_ENV` | yes | `test_web` | no | TEST runtime |
| `HOST` | yes | `0.0.0.0` | no | Docker default |
| `PORT` | yes | Render port / `10000` | no | Не hardcode інший порт |
| `PQM_DATA_DIR` | yes | `/var/data` | no | persistent disk mount |
| `PQM_DB_PATH` | yes | нова TEST-копія під `/var/data` | no | Не вказувати старий файл без snapshot/copy |
| `PQM_PROTOCOLS_DIR` | recommended | `/var/data/protocols` | no | generated DOCX |
| `PQM_CACHE_DIR` | recommended | `/var/data/cache` | no | runtime cache |
| `PQM_AUTH_ENABLED` | yes | `1` | no | fail closed |
| `PQM_USERS_JSON` | yes | нові rotated credentials | yes | не комітити |
| `PQM_ENABLE_BROWSER` | yes | `0` | no | server must not open browser |
| `PQM_ENABLE_SCHEDULER` | yes | `0` | no | first deploy |
| `PQM_ENABLE_NAZK_SCHEDULER` | yes | `0` | no | first deploy |
| `PQM_BIDS_MODE` | yes | `disabled` | no | full Bids DB absent |
| `PQM_ENABLE_BIDS_UPDATE` | yes | `0` | no | fail closed |
| `PQM_ENABLE_POWERBI` | yes | `0` | no | local-only |
| `PQM_ENABLE_GOOGLE` | yes | `0` | no | OAuth absent |
| `PQM_NODE_BINARY` | no | empty (use `node` in PATH) | no | Docker installs Node |
| `PQM_EDS_TIMEOUT_SECONDS` | no | code default or explicit bounded value | no | EDS timeout |
| `PQM_TESSERACT_EXE` | yes | `/usr/bin/tesseract` | no | Docker default |
| `PQM_PDFTOPPM_EXE` | yes | `/usr/bin/pdftoppm` | no | Docker default |
| `PQM_REMARKS_CACHE` | no | under `/var/data` if configured | no | optional cache |
| `PQM_BIDS_DB` | no | unset | no | Bids disabled |
| `PQM_BIDS_PROJECT_DIR` | no | unset | no | Bids disabled |
| `PQM_CURRENT_USER` | no | unset | no | request auth identity preferred |
| `PQM_GOOGLE_OAUTH_DIR` | no | unset | no | Google disabled |
| `PQM_GOOGLE_OAUTH_CLIENT` | no | unset | yes | Google disabled |
| `PQM_GOOGLE_OAUTH_TOKEN` | no | unset | yes | Google disabled |
| `PQM_GOOGLE_OAUTH_CLIENT_JSON` | no | unset | yes | Google disabled |
| `PQM_GOOGLE_OAUTH_REDIRECT_URI` | no | unset | no | future: `https://pqm-production-1.onrender.com/api/google-oauth/callback` |

