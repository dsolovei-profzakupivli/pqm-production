# V31.1 field direction addendum

This additive matrix clarification does not change the approved V31.1 business rules.

| Google column | Meaning | Google → PQM Preview / Apply |
|---|---|---|
| A | Freshness marker | Excluded. It is not read for comparison, conflict detection, plans, details, XLSX, counters, writes, or the Preview state digest. |
| F | Prozorro status | PQM-owned, outbound-only. Excluded from Google → PQM comparison and Apply. |
| H | Date of latest application | PQM-owned, outbound-only. Excluded from Google → PQM comparison and Apply. |
| B–E, G, I–O | Existing V31.1 mapped fields | Keep the previously approved field-specific mapping, conflict, timestamp, and write rules. Current PQM values for fields actually compared come from `edr_monitoring_projection`. |

The existing source fingerprint remains a freshness guard over the Google source snapshot. It is not the business Preview state digest. A/F/H do not enter the business plan or state digest; changing any source cell may still invalidate an old source fingerprint and require a new Preview.

PQM → Google behavior is unchanged. This addendum does not introduce a new projection, write, or field mapping.
