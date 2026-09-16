# NEXT LOCAL operational templates pre-release audit

## Blocker closure continuation

The original findings below are retained as audit history. Current implementation supersedes the termination registration/generation/UI gap and NAZK PDF endpoint gap.

| Workflow | Canonical packaged template | DOCX | PDF | Gate / release state |
| --- | --- | --- | --- | --- |
| AMKU | templates/amcu_exclusion_protocol.docx | Existing fixture generation regression passed | Existing same-version generic export route | Existing business/declension gates unchanged |
| Appeals | templates/violation_protocols/{warning,decline_p49_1_2,decline_p49_3}.docx | Actual-template generation regression passed | Existing report PDF flow | Source/runtime parity restored for decline 1/2 |
| Termination FOP | templates/termination_exclusion_protocol.docx | New registration, source aliases and shared renderer/version storage; synthetic v1/v2 generated with marker residue 0 and dd.MM.yyyy date | Reuses existing operational PDF route/converter; current document type supported | FOP only; required full-name cases, persisted protocol pair, termination reference, UO, all linked decisions and at least one effective-active exclude target required; reviewed/completed blocked |
| Termination legal entity | No approved legal template | Blocked | No generated artifact | Generic operational workflow retained; separate legal text still deferred |
| NAZK supplier request | templates/nazk_supplier_request.docx | Existing fixture generation passed | Existing operational PDF route now supports this type; shared download action wired | Existing NAZK predicates unchanged |

### Decline p49 1/2 version evidence and difference

Retained logs/server.log.1 contains successful operator template replacements on 2026-09-14 at 11:28:33, 11:30:49 and 12:49:26. The current runtime is the latest operator-managed artifact, and was selected to reproduce current behavior, not a new legal rewrite. Compared with the old packaged file, the only extracted paragraph-text changes are semicolons appended after the three Ministry URL paragraphs. Word package also differs in content types, root/document/font relationships, core/app metadata, font table, four embedded fonts, settings, styles, numbering and Word paragraph/revision identifiers. The whole runtime artifact was copied, preserving its formatting and relationships.

Old packaged version retained at templates/violation_protocols/_versions/decline_p49_1_2_before_release_parity_20260916.docx. New packaged and runtime files are byte-identical (SHA256 525cb13508d5db3c994fde50b342b79fdc1e5b3673f4fa1e09155efb87e81016). The parity regression checks actual bytes.

### Termination source preservation and mapping

Approved Downloads input was copied unchanged to templates/termination_exclusion_protocol.docx, SHA256 00cb3869715e4f40ec1d10c246844e86149bb6b831b3dd54dfc7d6c6c35b046d. Original legal text/package untouched. metadata/runtime_templates.v1.json declares the nine previously confirmed placeholder_aliases. Validation/render normalize those aliases in memory and use the established canonical field validation, run-safe replacement and renderer; no second document renderer was introduced.

Shared AMKU artifact/version persistence is reused internally for termination, with server-owned document type/action mapping and its own event name. Generation never completes a task, changes qualifications or excludes a supplier. Required genitive/accusative have no nominative fallback. The template's short_name remains nominative as explicitly mapped; an unused short-name genitive does not become a generation requirement.

Operational cards now expose shared document actions/history; completed termination cards no longer show the obsolete candidate-template hint or readiness errors. NAZK PDF is supported by the same task/document scoped source resolver rather than a new PDF subsystem.

Checks: 52 focused tests passed, followed by one new required-case/completed regression (5 termination document tests passed); total 53 distinct targeted checks. Browser synthetic document-action smoke passed: enabled FOP, version/history, DOCX/PDF controls, mocked generation request/return, legal entity disabled, completed hints absent, NAZK actions; exceptions 0. No real task/business DB writes, sync, ZIP, deploy or runtime restart.

Implementation files: task_documents.py, server.py, app.js, protocol_template.py, docx_conditionals.py, template_catalog.py, template_runtime.py; metadata/runtime_templates.v1.json and template_fields.v1.json; two canonical template assets plus retained old packaged backup; test_task_documents.py, test_termination_documents.py, tests/browser_template_actions.mjs; this report.

WEB still requires a working faithful PDF converter (LibreOffice). No WEB deployment/converter check occurred. Actual local synthetic converter acceptance is reported separately; API tests use controlled mocks and are not a WEB runtime guarantee.

Actual LOCAL synthetic termination export succeeded outside the sandbox through the established Word converter: valid %PDF header, 111712 bytes, source exactly the generated DOCX version. Initial sandbox invocation failed with COM logon-session 80070520; no fallback approximation was used. Synthetic DB/document/converter artifacts were cleaned by the fixture mechanism. This verifies local conversion, not visual/legal acceptance of a real supplier protocol or WEB LibreOffice availability.

No ZIP, deployment, external sync, real document generation or business-data mutation was performed. Legal text was not edited. Fixture generation tests do not constitute visual acceptance of a production PDF.

## Navigation

Established declension implementation: declension.py / declension_overrides.py, shared task_documents declension review and document gates; GET /api/declension-overrides, admin-only POST/PATCH/DELETE /api/admin/declension-overrides. Existing References → Declension UI remains authoritative. Operational task toolbar now opens that module and returns to/reloads the task list with filters preserved. tasks.read governs button availability; editing retains existing admin restrictions.

Adjacent Templates action uses showModule('administration') and setAdminTab('templates'). It follows existing admin-only administration visibility. Existing localStorage pqm.adminTab and pqm.activeModule persistence is reused. No URL reload or template logic was introduced.

Browser check at 1440×900: permissions, declension opening/read loading, return, filters, template main/subsection navigation, saved subsection state, subsequent navigation and desktop fit passed; runtime exceptions 0. Refresh itself was not separately automated; existing persisted tab mechanism was verified.

## Template matrix

All paths below are relative to D:/AI/Codex/Projects/PQM-0.1.

| Workflow | Current runtime file | Payload / placeholders | DOCX / PDF / wiring |
| --- | --- | --- | --- |
| AMKU exclusion | data/templates/amcu_exclusion_protocol.docx | decision.number/date; supplier.name_genitive/name_accusative/short_name_genitive/short_name_accusative/code/code_label; uo.full_name; amcu.decision_basis_phrase; repeat amcu.decisions[] with linked_reference | Registered active; canonical validation true; fixture generation/hyperlink/count/declension tests passed. PDF uses same version via amcu_pdf_source and ensure_pdf; route/error behavior mock-tested. Card has document/version/history/download controls. |
| Appeals warning | data/templates/violation_protocols/warning.docx | Legacy context: report, supplier/customer identity and cases, protocol, procurement, grounds, response/documents, structured civil-code conditional | Established legacy renderer; targeted actual-template fixture generation and unknown-token rejection passed. Shared Protocol Decision section and DOCX/PDF actions wired. |
| Appeals decline p49 1/2 | data/templates/violation_protocols/decline_p49_1_2.docx | Warning context plus contract and refusal/rejection details | Same established flow; runtime file differs from packaged templates/violation_protocols/decline_p49_1_2.docx. Must decide/package the current intended operator version before ZIP; no automatic replacement performed. |
| Appeals decline p49 3 | data/templates/violation_protocols/decline_p49_3.docx | Report, protocol, supplier/customer cases, grounds, procurement/contract, response/documents | Same established flow; runtime and source match. |
| Termination exclusion | No registered runtime template | Canonical payload below; legal DOCX only D:/Downloads/Дискваліфікація_ПРИПИНЕННЯ.docx | Boundary only: readiness always false, FOP candidate not activated, legal entity blocked. No termination generator/PDF route wiring; card has disabled generation button, no working generated-version/download UI. |
| NAZK supplier request | data/templates/nazk_supplier_request.docx | supplier.name/name_genitive/code/code_label/email; manager.full_name/full_name_genitive/rnokpp; supplier.entity_type conditionals | Registered active; canonical validation true; fixture DOCX/history/metadata tests passed. Generic PDF link is exposed by public_document but operational PDF endpoint restricts amcu_exclusion_protocol: NAZK PDF gap. |
| Application protocol (adjacent workflow) | data/templates/application_protocol.docx | protocol_number/date; officer_name/signature_name/verb; period_start/end; count_all/admitted/rejected; applications_all/admitted/rejected row fields | Existing managed legacy application renderer, not an operational exclusion template. Include source file; separate workflow. |

Legacy appeals templates are not new canonical runtime templates. Generic catalog scan reports advisory legacy mode; those findings are not evidence that the established legacy generation path is broken. Its own renderer validation and fixture tests govern it.

### Exact AMKU markers

{{decision.number}}, {{decision.date}}, {{supplier.name_genitive}}, {{supplier.name_accusative}}, {{supplier.short_name_accusative}}, {{supplier.short_name_genitive}}, {{supplier.code}}, {{supplier.code_label}}, {{uo.full_name}}, {{amcu.decision_basis_phrase}}, {{#repeat amcu.decisions[]}}, {{linked_reference}}, {{/repeat}}.

### Appeals placeholder inventory

Shared tokens across the current appeal templates: report_id, protocol_number, protocol_date, officer_name, supplier_name, supplier_name_genitive, supplier_name_accusative, supplier_code, supplier_code_label, supplier_deadline, supplier_response, supplier_documents, customer_name, customer_name_genitive, customer_name_accusative, customer_code, customer_documents, cpv_category, p49_reference, reason_label, reason_text, decision_justification, procurement_id, procurement_date, winner_date, violation_description.

Warning additionally uses supplier_name_dative, supplier_short_name, refusal_date, refusal_document, refusal_outgoing_number, rejection_date, rejection_reason. Decline p49 1/2 additionally uses supplier_short_name, contract_date, contract_number and those refusal/rejection tokens. Decline p49 3 additionally uses contract_date, contract_number. All three have the established decision.civil_code_basis applicable conditional.

## Termination mapping confirmed in source

| Canonical field | Existing legal DOCX token |
| --- | --- |
| decision.number | № Протоколу |
| decision.date | Дата протоколу |
| supplier.name_genitive | Постачальник родовий |
| supplier.short_name | Постачальник скорочено |
| supplier.name_accusative | Постачальник знахідний |
| supplier.code_label | код ЄДРПОУ/ІПН |
| supplier.code | Код ЄДРПОУ |
| termination.reference | Реквізити рішення (постанови) |
| uo.full_name | УО |

This is the semantic mapping, NOT an installed legacy-token binding adapter. Current payload also includes supplier.name, supplier.short_name_genitive and termination.details/record_date/record_number. termination.reference joins those three source fields with ' · '. decision.date currently carries the persisted task value; termination document dd.MM.yyyy formatting is not implemented because generation is not wired.

FOP/ЮО operational workflow remains generic. The FOP-specific DOCX cannot be automatically applied to legal entities. Legal-entity readiness explicitly returns legal_entity_blocked, without blocking the operational data/decision lifecycle. Both document branches remain unready pending template implementation/approval.

## Required source templates for future ZIP

- templates/amcu_exclusion_protocol.docx (byte-identical to current runtime; SHA256 3dff890ba125b9f0d95d4e22096feca74de4d290fb5851101f5c0eeceb1fbb0d).
- templates/nazk_supplier_request.docx (byte-identical to runtime).
- templates/application_protocol.docx (byte-identical to runtime).
- templates/violation_protocols/warning.docx (byte-identical to runtime).
- templates/violation_protocols/decline_p49_3.docx (byte-identical to runtime).
- templates/violation_protocols/decline_p49_1_2.docx: intended current version must first be reconciled; current runtime SHA256 525cb13508d5db3c994fde50b342b79fdc1e5b3673f4fa1e09155efb87e81016.
- Proposed, currently absent destination: templates/termination_exclusion_protocol.docx, followed by registry/mapping/generator wiring. Approved input remains D:/Downloads/Дискваліфікація_ПРИПИНЕННЯ.docx (SHA256 00cb3869715e4f40ec1d10c246844e86149bb6b831b3dd54dfc7d6c6c35b046d).

Include metadata/runtime_templates.v1.json, template_fields.v1.json, template_legacy_tokens.v1.json and document/schema metadata plus renderer code. Generated documents, .new files, historical _versions and output artifacts are not source templates.

Runtime resolution uses project-relative templates and PQM_DATA_DIR/data writable storage; it does not require a user Downloads path for current registered templates. Clean WEB runtime seeds missing runtime templates from packaged source without overwriting operator versions. Therefore the decline 1/2 source/runtime mismatch is a concrete packaging risk.

PDF conversion requires Word COM on Windows or LibreOffice on WEB. LOCAL helper reports Word available, LibreOffice absent; real conversion was not exercised in this audit. WEB converter availability was not verified and remains an environment prerequisite, not a template guarantee.

## Remaining gaps / verdict

NOT READY to declare all requested document workflows complete: termination registration/mapping/generation/PDF/version controls missing; separate ЮО legal text deferred; decline p49 1/2 packaged/runtime version mismatch; NAZK PDF link has no supported matching endpoint; WEB converter not confirmed. Completed termination card still contains the unconditional candidate-template hint and may show obsolete readiness errors. No legal text rewrite or automatic recovery was performed.

Tests: 46 focused termination/task-document/PDF/declension tests passed; 2 targeted appeal actual-template generation/unknown-placeholder tests passed. Browser navigation acceptance passed with 0 exceptions. PDF tests are controlled mocks, not real production PDF generation.

Changed implementation files: index.html, app.js, test_declension_navigation_ui.py, tests/browser_task_declension.mjs. This audit report is new. No template binary, registry configuration, DB or frozen WEB change.
