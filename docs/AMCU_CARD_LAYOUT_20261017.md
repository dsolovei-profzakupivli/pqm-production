# Sandbox AMCU task modal layout

Parent: 254e3bc64905b447fc8a2f865e739a854d05905e.

UI only: the AMCU modal renders Basis and Officer decision as equal-width cards,
stacked on narrow screens. Actual basis/decision fields and existing links are
reused. Long words wrap without clipping. The confirmed-Prozorro result label is
suppressed only in the AMCU modal header/terminal display, not in API/table/history.
The existing post-layout no longer adds a duplicate Basis or regroups these new
cards. Editable active-task controls and qualification/history sections remain.

The right card has two internal columns: existing decision/DOCX/PDF links on the
left, saved current-document content on the right. The original generic metadata
renderer preserves every nonempty metadata key/label/value and Copy action; no
filename/task-derived content or older-version fallback. No decorative empty block.
The existing metadata source is generated_documents.metadata_json, resolved once
at generation and exposed per document as resolved_metadata (metadata_key, label,
resolved_text, version, display_order). No fixed AMCU key is assumed. A read-only
Sandbox check found four AMCU documents without metadata and no AMCU metadata
configuration: these correctly show no content block. Synthetic version-specific
metadata tests cover rendering, missing current/available old metadata and multiple
current documents. No new backend data source or retrieval is introduced.

The supplier code value only is bold (700); its label remains normal (400), with
unchanged font size/spacing/text selection, in both modal and floating modes.

No backend/API/DB/schema/generator/document/current-version logic changes.
No Production, runtime, scheduler, Google or kill-switch changes.

Tests: actual renderer units; current-protocol/history compatibility; offline
Chromium with full styles and actual modal renderer/post-layout: light/dark,
100%/125%, 390/768/1440px, long/missing/multiple documents and active/completed tasks.
No real requests or writes. Full Linux/Docker gate on exact candidate required.

After separate approval, user alone manually deploys the exact SHA to pqm-sandbox.
Confirm current Live SHA and no conflicting operations first. Manual acceptance
checks the same layouts, existing current/history links and unchanged qualification
and event sections. Do not generate real documents for tests; use an isolated DB.

Rollback: user manually returns to the previous recorded Sandbox Live SHA
(candidate parent 254e3bc… if it is the current Live at deployment time). No DB
restore, migration or document change is required. No deployment is authorized by
this document.
