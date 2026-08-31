# Security checklist for public GitHub repository

Repository: `dsolovei-profzakupivli/pqm-production`.

## Before upload

- [ ] Temporarily disable Auto-Deploy or use a review branch/PR; do not upload straight to `main` before review.
- [ ] Scan the proposed tree for `.env*`, `*.json`, `*.sqlite*`, `*.db`, `*.zip`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, logs and generated documents.
- [ ] Inspect `PQM-production.zip`, `PROJECT_JOURNAL.md`, `TEST_WEB_DEPLOY.md`, README and historical deployment/config files.
- [ ] Confirm package `SHA256SUMS.txt` before copying files.
- [ ] Never add TEST DB or secret env values to Git.

## History

- [ ] Search all Git history, not only current tree, for passwords, OAuth client secrets, refresh/access tokens, API keys, private keys and DB/archive files.
- [ ] Treat every secret that ever appeared in a public commit as exposed, even if later deleted.
- [ ] Rotate old TEST credentials and any exposed OAuth/API credentials.
- [ ] If cleanup is required, plan history rewriting separately with repository owners; do not improvise it during deployment.
- [ ] Re-scan current tree and history after cleanup.

Suggested manager-side tools: GitHub secret scanning, `gitleaks` or `trufflehog`, plus explicit filename/history searches. Do not paste findings containing secret values into tickets or documents.

