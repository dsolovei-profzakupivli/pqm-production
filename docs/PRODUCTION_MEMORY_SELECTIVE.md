# Selective Production memory integration

Baseline: `a53234f1d4a4c32032bc0b1c311b1a279ab17e22`.
Package 1: `49afd73c23bef4cab9f5f6cdbd5768b14e49a271`.

## Scope

- Closing SQLite contexts retain commit/rollback semantics; connection setup
  failures also close the handle. WAL and busy timeouts are unchanged.
- Contract cache: 1024 entries, 16 MiB serialized budget, physical expiry on
  access. Document jobs: 16 active, 256 terminal metadata entries, one-hour TTL.
  Full verification evidence remains in the existing SQLite result field.
- Saved checks are read as saved, without fingerprint-based warning/status
  substitutions. Fingerprints remain in the verification/cache mechanisms.
- Completed manual checks replace manual categories; interrupted/technical
  failures and newly locked applications preserve previous evidence. The
  independently populated experience category remains separate.
- Full Registry revision distinguishes committed data from an empty recreated
  WAL; transactions bypass process-wide cached data. Writer logic is unchanged.

## Production queue

The existing ingestion hook feeds a two-worker FIFO queue, initially 128 owned
IDs and a 32-item pump quantum. Ownership includes active, ready and waiting
retry IDs. Admission backpressure occurs after ingestion's DB context closes.
It does not discard overflow, add futures per application, or change schedules.
It can delay the end of a sync while background work makes space. This delay
must be monitored under real upstream latency; it is not an HTTP SLA improvement.

The actual search criteria, six-hour freshness, algorithm version, HTTP interval,
page limits, 60-second retry delay and maximum two extra attempts are retained.
Production does not acquire the Sandbox exception, pending-only scan, permanent
saved-result skip, environment restrictions, or new startup automation.

Production's exhausted budget also remains exhausted across later admissions
until success or process restart. A small `background_retry` annotation in the
existing experience check stores attempts and a process epoch. It is included
in the existing result write, without another transaction or a schema change.
It changes no verdict, counter, source, manual result or verification timestamp.
The current epoch restores counters on demand, avoiding an unbounded RAM map.
A new epoch after restart reproduces the old process-local reset. Old readers
ignore the annotation. No historical rows are migrated or rewritten in bulk.

Timer/dispatch faults retain reserved work. A failed dispatch wakes blocked
producers with an explicit error instead of hanging; a later admission can
retry dispatch. A permanently broken executor cannot promise forward progress.

This is not a durable job journal. After process loss, unfinished searches need
re-admission by the existing ingestion path; no new startup scan is introduced.
The crash probe explicitly tests that re-admission, not automatic boot recovery.
Exactly-once external reads across a crash are not guaranteed. Saved results
remain in SQLite and fresh results are skipped under the original rule.

## Validation and promotion

`validation/run_production_memory.py` provides disposable targeted suites.
`validation/production_memory_entrypoints.py` checks direct shared routing in a
disposable no-Git copy. Historical manifests and mutation assertions are intact;
current v1/v2 additive contracts protect the actual Production inputs.

Browser probes use the shipped Production HTML and local synthetic API replies,
with external traffic denied. Benchmarks use generated pages, temporary SQLite
and mock searches. They do not prove real Render throughput or peak document RAM.

The full Linux/Container Gate remains required on the final candidate SHA.
After separate deployment approval, observe hourly syncs, documents, Google
reads, requests, registry refreshes and an overnight period, including disk
snapshot time. Track memory after drain, API p95, backlog age and errors.

Rollback is a separately approved deployment of the previous exact Production
revision, without a database restore. There is no schema migration. Do not
automatically replay interrupted searches or roll back saved verification data.
