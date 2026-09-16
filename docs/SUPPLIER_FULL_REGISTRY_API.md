# PQM full supplier registry integration API

## Endpoint

`GET /api/integrations/suppliers/full-registry`

The endpoint is read-only and returns every non-empty supplier identity that occurs in `submissions`, one item per exact trimmed `supplier_code`. It is the full historical population, not the ClarityChecker queue.

## Authentication

Set the server secret in environment variable `PQM_SUPPLIER_REGISTRY_TOKEN`. Send:

`Authorization: Bearer <token>`

The token belongs in Google Apps Script Script Properties, never in sheet cells or source code. Browser cookies and PQM Basic Auth do not authorize this endpoint. Missing/invalid credentials return `401`; an unconfigured server secret returns `503`. Non-GET methods return `405`.

## Response

```json
{
  "generated_at": "2026-09-10T12:00:00+00:00",
  "count": 14865,
  "items": [{
    "supplier_code": "00110183",
    "entity_type": "legal_entity",
    "supplier_name": "...",
    "current_manager_name": "...",
    "prozorro_status": "🟢 Активний",
    "prozorro_status_canonical": "Активний",
    "prozorro_status_google": "✅ Активний",
    "freshness_marker": "🟢 <30 днів",
    "monitoring_eligible": true,
    "last_application_date": "2025-02-19",
    "last_approved_application_date": "2025-02-19",
    "last_approved_application_uo": "НЕ ВИЗНАЧЕНО",
    "verification_date": "2026-09-01",
    "verification_officer": "...",
    "verification_event_type": "google_clarity"
  }]
}
```

`supplier_code` is always JSON string and preserves leading zeroes and foreign formatting. Dates are ISO `YYYY-MM-DD` or `null`.

`prozorro_status_canonical` uses the shared four-state `edr_sync_v2.prozorro_statuses` resolver. Effective-active evidence takes priority over suspended, historical membership and eligible final application. Existing `prozorro_status` presentation is preserved for compatibility. Writers use `prozorro_status_google`: `✅ Активний`, `⚪️ Неактивний`, `➖ Ще не в реєстрі`, `🟠 Призупинений`.

`freshness_marker` is a non-null string from `edr_sync_v2.marker_for_status` / `freshness_state`, the same helper used by EDR register rows/KPI. Values: `🟣 Неактуально`, `🟢 <30 днів`, `🟡 >30 днів`, `🟠 >60 днів`, `🔴 >90 днів`, `⚪ Не перевірено`. It uses the latest coherent persisted verification/admission event, never unimported Google data. No thresholds are implemented in the integration layer. Google → PQM does not import the marker.

`monitoring_eligible` is an explicit non-null boolean for membership in the EDR register population: existing EDR profile OR supplier registry summary OR application with final `admit/reject`. Shared `MONITORING_POPULATION_SQL` is used by the EDR register and API. Existing legacy profiles remain eligible; pending-only suppliers without profile/registry/final evidence are not. This is register membership, not the narrower active/suspended recurring-check predicate. Entity routing is independent: foreign/unknown records must still be skipped.

`verification_date` (string/null), `verification_officer` (string, empty when absent) and `verification_event_type` (string/null) describe one latest event. They are informational and must NOT overwrite Google-owned verification columns.

`last_application_date` is the newest submission date regardless of outcome. `last_approved_application_date` is the newest submission having a Prozorro qualification with `status='active'`; later unsuccessful/rejected submissions do not move it. `last_approved_application_uo` is that submission's stored `application_fields.protocol_officer`, otherwise `НЕ ВИЗНАЧЕНО`.

## Entity type source priority

1. A non-Ukrainian identifier scheme (`US-EIN`, `PL-NIP`, etc.) → `foreign_legal_entity`.
2. Current `supplier_edr_profiles.source_sheet=ФОП` → `individual_entrepreneur`.
3. Current `supplier_edr_profiles.source_sheet=ЮО` → `legal_entity`.
4. `UA-IPN` without an EDR profile → `individual_entrepreneur`.
5. Otherwise → `unknown`.

Code length is never used. `unknown` is intentional for historical `UA-EDR` identities without a reliable current type source.

The response is about 6.2 MB for 14,865 CURRENT LOCAL suppliers, so pagination is not used. Google Apps Script can fetch it in one request and perform its own non-destructive UPSERT.

## Approved API → Google writer ownership (writer not implemented)

| Google header (ФОП and ЮО) | API source / ownership |
| --- | --- |
| Маркер актуальності | PQM-owned: `freshness_marker`; no Google freshness formulas |
| Код ЄДРПОУ | PQM identity: exact trimmed string `supplier_code`; append only, never rewrite an existing key |
| Найменування | PQM-owned: `supplier_name` |
| Статус (Prozorro) | PQM-owned: `prozorro_status_google` |
| Дата останньої заявки | PQM-owned: `last_application_date` |
| ПІБ для перевірки | Google/Clarity-owned: preserve |
| Статус в реєстрі (ЄДР) | Google/Clarity-owned: preserve |
| Реквізити рішення про припинення | Google/Clarity-owned: preserve |
| Дата перевірки | Google/Clarity-owned: preserve |
| Дата запису / Номер запису | Google/Clarity/formula-owned: preserve |
| УО | Google/Clarity-owned: preserve |
| Примітки | Google/manual-owned: preserve; independent of PQM supplier_notes |
| Повна назва з ЄДР / Скорочена назва з ЄДР | Google/Clarity-owned: preserve |

Route `individual_entrepreneur` → ФОП, `legal_entity` → ЮО; foreign/unknown → skip. Existing matched rows may receive only permitted PQM-owned changes regardless of eligibility. Append only when `monitoring_eligible=true`. Never delete absent/ineligible rows, merge by name, pad codes, convert codes to numbers or move records between tabs. Duplicate codes within/between tabs are conflicts.

Blank/null API values preserve existing cells. A formula in any target PQM-owned cell is a conflict, not permission to overwrite. No clearContents, clearFormats or sheet replacement. Batch writes must touch only authorized changed cells and preserve formatting/validation/manual fields. API URL and Bearer token belong in Script Properties; never log the token. No PQM Google write OAuth is required.

Before implementing the writer, verify actual sheet headers, formula conflicts and row append formatting/validation; provide a reachable HTTPS API URL (Apps Script cannot reach LOCAL 127.0.0.1). The retained legacy eligibility above does not imply appending unknown/foreign identities.
