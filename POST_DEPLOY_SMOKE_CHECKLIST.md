# Post-deployment smoke checklist

- [ ] URL `https://pqm-production-1.onrender.com` opens.
- [ ] `GET /api/health` without auth returns HTTP 200 JSON.
- [ ] Protected API without auth returns HTTP 401 JSON (not HTML).
- [ ] Wrong credentials fail; new rotated credentials return 200.
- [ ] Unknown `/api/...` returns JSON 404.
- [ ] HTML/CSS/JS load without console/network errors.
- [ ] Реєстр заявок loads; search, filters and pagination work.
- [ ] Application modal opens.
- [ ] A TEST manual decision saves; refresh proves persistence.
- [ ] База постачальників, Відбори, Довідники, Звернення, Адміністрування and Журнал open.
- [ ] Document checks work on TEST data.
- [ ] DOCX generation downloads a readable document and preserves the approved template formatting.
- [ ] EDS adapter returns a controlled success/error; outage must not crash PQM.
- [ ] Do not infer certificate qualification from `issuerCN`.
- [ ] Bids page reports controlled unavailability; no `Failed to fetch`.
- [ ] Google reports controlled disabled state.
- [ ] Power BI is disabled/controlled.
- [ ] No scheduler, NACP scheduler, browser auto-open, Bids update or unexpected Prozorro sync starts.
- [ ] Server logs contain no startup traceback and API errors are JSON, not `<!DOCTYPE...`.

Success requires all applicable checks. On failure: stop acceptance, preserve logs without secrets, prefer code rollback; use disk restore only under the conditions in `ROLLBACK.md`.

