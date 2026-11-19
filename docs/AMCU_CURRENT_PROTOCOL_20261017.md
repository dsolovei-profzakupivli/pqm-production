# Sandbox candidate: current AMCU protocol in task table

Baseline: 0f5f344af81167d0f54350ae46a21aaa72a502d0.

The read-only task UI projection now keeps the first generated protocol per
document type in task_documents.documents() order, exactly the newest-first order
used by the existing card. Distinct protocol types remain separate. It does not
pick MAX(version): version numbers restart per protocol date. Supplier request
history remains unchanged. The card's document_generation.documents still contains
the complete version history; v3 is main, v2/v1 remain under Previous versions.

No generator, file, document status, event, qualification link, write API, startup,
schema, scheduler, Google execution or kill-switch changes. No deployment.

Regression coverage: empty/single/three versions, actual three DOCX generations,
immutable files and generation events, list/detail HTTP, read-only invariants,
distinct protocol types and requests, task isolation, timestamp tiebreak, date and
version reset, actual table/card rendering with current DOCX/PDF and history.
Fixtures are disposable and network-isolated. No live DB or documents used.

After exact-SHA Linux/Docker gate and separate approval, user alone deploys this
candidate to pqm-sandbox. Confirm Live SHA, unchanged kill-switch and no conflicting
jobs; accept one versus repeated generation on an isolated DB, not live runtime.
Do not generate or mutate real protocols just for acceptance.

Code rollback: user manually returns pqm-sandbox to its confirmed previous Live
SHA (last confirmed accepted source 0f5f344…; verify current Live before deploy).
No schema rollback or disk restore required. The previous source preserves the
Sandbox kill-switch. No Production port/merge/deploy is included.
