# Status-event source evidence — 2026-10-13

Official reviewed source SHA: `c05cbed1595b335cd950179bfce1d86ed324e3b9`
in [ProzorroUKR/openprocurement.api](https://github.com/ProzorroUKR/openprocurement.api/tree/c05cbed1595b335cd950179bfce1d86ed324e3b9).
This is external API source evidence, not a claim about the deployed PQM SHA or
availability of each field in a live legacy record.

## Causal sources

- Exclusion: `milestone.dateMet`, `status=met`, a typed activation/ban milestone,
  and the same instant in the enclosing terminated `contract.date`.
  [MilestoneState](https://github.com/ProzorroUKR/openprocurement.api/blob/c05cbed1595b335cd950179bfce1d86ed324e3b9/src/openprocurement/framework/core/procedure/state/milestone.py)
  sets dateMet and the status-specific contract.date during termination.
- 90-day blocking: suspended contract plus scheduled ban milestone. Its creation
  dateModified must match contract.date, with a valid future dueDate. on_post
  sets all of these creation/status timestamps together. A later document edit
  only changes dateModified and does not establish a new blocking event.
  [Milestone model](https://github.com/ProzorroUKR/openprocurement.api/blob/c05cbed1595b335cd950179bfce1d86ed324e3b9/src/openprocurement/framework/core/procedure/models/milestone.py)
  specifies the 90-calendar-day ban. dueDate is never its start timestamp.
- Announcement completion: observed active→complete framework with a later
  framework.date and a passed qualificationPeriod.endDate. The period deadline
  is only a consistency check, not the event timestamp. Generic dateModified
  is not used. The existing
  [update_status_change_revision](https://github.com/ProzorroUKR/openprocurement.api/blob/c05cbed1595b335cd950179bfce1d86ed324e3b9/src/openprocurement/framework/core/procedure/utils.py)
  updates date for the changed status-bearing model. Revisions store reverse
  patches (get_revision_changes(dst,src)); their values must not be interpreted
  as new forward statuses. The producer adds no revision/document fetches.

The public [tutorial](https://prozorro-api-docs.readthedocs.io/en/master/agreements/frameworks/tutorial.html)
also links ban creation to suspension and met milestones to termination.

## Local guarantees

Existing importer transactions append to the existing verification ledger only.
No schema changes, jobs, schedules or primary historical records are introduced.
Identity is bound to framework/agreement/contract/qualification/supplier and
milestone IDs plus the exact source instant. Immutable proof hashes omit mutable
documents and sync/audit time. A repeated identity cannot rewrite the earlier event.

The exact source instant (including microseconds) is retained in immutable proof.
occurred_at uses the existing Europe/Kyiv millisecond representation used by the
Sheets/read-model contract. Google/manual datetime parsing is unchanged.

No structured UO identity is exposed by the reviewed milestone/contract schema.
The producer uses ЕСЗ (technical source), never the supplier contact, marketplace
owner, prior admission officer or technical sync user. It does not search documents.

Missing/invalid timestamps, non-increasing status dates, identity mismatches and
ambiguous or uncorrelated milestones produce no event. Framework completion affects
still-active/suspended memberships, not members already excluded earlier.
First historical observations and unchanged cached states do not trigger backfill.

## Screenshot control

44368854 is suspended, not terminated. The agreed freshness rule remains active:
the later 11.09 Google check is preserved over a 03.09 ban event.
The supplier popup's event_date currently prefers document publication/modification
dates, then milestone modification/contract/qualification dates. That UI timestamp
alone is NOT used as proof for this producer; changing the popup is outside scope.

## Verification

`test_google_status_event_producer`: 14/14 offline tests, including real importer
hooks with mocked network, repeat sync, missing timestamps, preserved receipt and
Kyiv midnight. Actual Render payloads were not inspected or changed.
